"""
SkyOptimizer AI — Global Waypoint Graf Oluşturucu

Herhangi iki havalimanı arası dinamik waypoint ağı üretir. Great-circle
rota üzerinde ve koridor boyunca noktalar oluşturulur; A* bu graf
üzerinde optimum rotayı bulur.

Performans (madde: ölçeklenme):
  • Kenar eşleştirmesi O(n²) yerine mekânsal ızgara (spatial hash) ile
    yalnızca komşu hücrelerde yapılır.
  • Topoloji (düğüm/kenar yapısı) rotaya göre LRU cache'lenir; her istekte
    yalnızca kopya alınıp maliyetler yazılır. Rüzgâr/maliyet asla cache'e
    girmez.

Kısıtlı hava sahaları (services.airspace_service) kenar bazında elenir.
Eleme rotayı tıkarsa graf kısıtsız yeniden kurulur ve durum raporlanır.
"""

import math
from functools import lru_cache
from typing import Optional

import networkx as nx

from services.airport_service import get_airport, get_corridor_airports
from services.airspace_service import point_blocked, segment_blocked
from utils.geo import haversine_nm, initial_bearing, great_circle_waypoints

# Direkt origin→dest kenarı endeksi (kenar üretiminde atlanır)
_DIRECT_EDGE = "__direct__"


def build_waypoint_graph(
    origin_icao: str,
    destination_icao: str,
    intermediate_airports: Optional[list] = None,
    max_edge_distance_nm: float = 350,
    grid_spacing_deg: float = 1.0,
    avoid_airspace: bool = True,
) -> nx.DiGraph:
    """
    Kalkış ve varış arasında dinamik waypoint grafiği oluşturur.

    Yaklaşım:
    1. Kalkış ve varış havalimanlarını ekle
    2. Great-circle üzerinde ~100 NM aralıklarla ana waypoint'ler
    3. Koridor boyunca (±30, ±60, ±100 NM) alternatif noktalar
    4. Koridordaki gerçek havalimanlarını dahil et
    5. Mekânsal ızgara ile mesafe bazlı kenarlar
    6. Kısıtlı hava sahalarını kesen kenarları at

    Returns:
        networkx DiGraph — A* ile optimize edilecek graf. `G.graph`
        içinde hava sahası ve topoloji bilgisi bulunur.
    """
    intermediate_key = tuple(sorted(intermediate_airports or []))
    G = _build_topology_cached(
        origin_icao.upper(),
        destination_icao.upper(),
        intermediate_key,
        float(max_edge_distance_nm),
        float(grid_spacing_deg),
        bool(avoid_airspace),
    )
    # Cache'teki topolojiye asla yazmayalım: kenar attribute'ları kopyalanır
    return G.copy()


@lru_cache(maxsize=32)
def _build_topology_cached(
    origin_icao: str,
    destination_icao: str,
    intermediate_airports: tuple,
    max_edge_distance_nm: float,
    grid_spacing_deg: float,
    avoid_airspace: bool,
) -> nx.DiGraph:
    """Topoloji üretimi (cache'li). Dönen graf SALT OKUNMALIDIR."""
    G, blocked_count = _build_topology(
        origin_icao, destination_icao, list(intermediate_airports),
        max_edge_distance_nm, grid_spacing_deg, avoid_airspace,
    )

    # Hava sahası elemesi rotayı tıkadıysa kısıtsız yeniden kur
    if avoid_airspace and not nx.has_path(G, origin_icao, destination_icao):
        G, _ = _build_topology(
            origin_icao, destination_icao, list(intermediate_airports),
            max_edge_distance_nm, grid_spacing_deg, False,
        )
        G.graph["airspace_avoidance"] = "disabled"
        G.graph["airspace_note"] = (
            "Kısıtlı hava sahası elemesi rotayı tıkadı; kısıtsız graf kullanıldı."
        )
    else:
        G.graph["airspace_avoidance"] = "active" if avoid_airspace else "off"
        G.graph["airspace_blocked_edges"] = blocked_count

    return G


def _build_topology(
    origin_icao: str,
    destination_icao: str,
    intermediate_airports: list,
    max_edge_distance_nm: float,
    grid_spacing_deg: float,
    avoid_airspace: bool,
) -> tuple:
    """Graf topolojisini (mesafe/yön ile) üretir; maliyetleri değil."""
    G = nx.DiGraph()
    G.graph["origin"] = origin_icao
    G.graph["destination"] = destination_icao

    origin = get_airport(origin_icao)
    dest = get_airport(destination_icao)
    if not origin or not dest:
        return G, 0

    G.add_node(origin_icao, **_airport_node(origin))
    G.add_node(destination_icao, **_airport_node(dest))

    olat, olon = origin["latitude"], origin["longitude"]
    dlat, dlon = dest["latitude"], dest["longitude"]
    total_dist = haversine_nm(olat, olon, dlat, dlon)
    G.graph["great_circle_nm"] = round(total_dist, 1)

    # ── 2. Great-circle ana waypoint'leri ──────────────────────────
    # Kısa rotalarda daha sık aralık → daha fazla alternatif yol
    if total_dist > 500:
        spacing_nm = 100
    elif total_dist > 300:
        spacing_nm = 50
    elif total_dist > 150:
        spacing_nm = 30
    else:
        spacing_nm = 20
    num_gc_points = max(5, int(total_dist / spacing_nm))
    gc_waypoints = great_circle_waypoints(olat, olon, dlat, dlon, num_gc_points)

    for i, (lat, lon) in enumerate(gc_waypoints[1:-1], 1):
        wp_id = f"WP_{i:03d}"
        G.add_node(wp_id, latitude=lat, longitude=lon,
                   type="waypoint", name=f"WP-{i}")

    # ── 3. Koridor waypoint'leri (rota ekseninin sağ/solunda) ──────
    if total_dist > 2000:
        offsets_nm = [-200, -120, -60, 60, 120, 200]  # Transatlantik — jet stream
    elif total_dist > 1000:
        offsets_nm = [-150, -80, -40, 40, 80, 150]
    elif total_dist > 400:
        offsets_nm = [-80, -40, 40, 80]
    elif total_dist > 150:
        offsets_nm = [-60, -40, -25, -10, 10, 25, 40, 60]
    else:
        offsets_nm = [-40, -25, -10, 10, 25, 40]

    route_bearing = initial_bearing(olat, olon, dlat, dlon)
    for i, (lat, lon) in enumerate(gc_waypoints[1:-1], 1):
        for j, offset in enumerate(offsets_nm):
            offset_deg = offset / 60  # 1 derece ≈ 60 NM
            perp_bearing = (route_bearing + 90) % 360
            dlat_off = offset_deg * math.cos(math.radians(perp_bearing))
            dlon_off = offset_deg * math.sin(math.radians(perp_bearing)) / max(
                math.cos(math.radians(lat)), 0.01
            )
            wp_id = f"COR_{j}_{i:03d}"
            node_lon = ((lon + dlon_off + 180) % 360) - 180
            G.add_node(wp_id, latitude=lat + dlat_off, longitude=node_lon,
                       type="corridor", name=f"C{j}-{i}")

    # ── 4. Koridordaki gerçek havalimanları ───────────────────────
    corridor_airports = get_corridor_airports(
        olat, olon, dlat, dlon,
        radius_nm=min(total_dist * 0.4, 300),
    )
    for ap in corridor_airports:
        if ap["icao"] in (origin_icao, destination_icao):
            continue
        G.add_node(ap["icao"], **_airport_node(ap))

    # ── 5. Ara havalimanları ──────────────────────────────────────
    for ap_icao in intermediate_airports:
        ap = get_airport(ap_icao)
        if ap:
            G.add_node(ap_icao, **_airport_node(ap))

    # ── 6. Kenarlar ───────────────────────────────────────────────
    if total_dist <= 500:
        effective_max_edge = max(total_dist * 0.35, 60)
    else:
        effective_max_edge = max(min(max_edge_distance_nm, total_dist * 0.5), 200)

    nodes = list(G.nodes(data=True))
    if grid_spacing_deg <= 0:
        grid_spacing_deg = 1.0

    blocked_count = 0
    seen_pairs = set()

    for n1, d1, n2, d2 in _neighbor_pairs(nodes, effective_max_edge):
        # Direkt origin→dest kenarını engelle (ara düğüm zorunlu)
        if {n1, n2} == {origin_icao, destination_icao}:
            continue

        lat1 = d1.get("latitude", 0)
        lon1 = d1.get("longitude", 0)
        lat2 = d2.get("latitude", 0)
        lon2 = d2.get("longitude", 0)

        dist = haversine_nm(lat1, lon1, lat2, lon2)
        if not (0 < dist <= effective_max_edge):
            continue

        if avoid_airspace and segment_blocked(lat1, lon1, lat2, lon2):
            blocked_count += 1
            continue

        bearing = initial_bearing(lat1, lon1, lat2, lon2)
        G.add_edge(n1, n2, distance_nm=dist, bearing=bearing)
        G.add_edge(n2, n1, distance_nm=dist, bearing=(bearing + 180) % 360)

    G.graph["effective_max_edge_nm"] = round(effective_max_edge, 1)
    return G, blocked_count


def _neighbor_pairs(nodes: list, max_edge_nm: float):
    """
    Mekânsal ızgara ile yakın düğüm çiftlerini üret.

    Izgara yerel düzlemde kurulur (x = lon·cos(lat)·60 NM, y = lat·60 NM),
    hücre boyutu = max_edge_nm. Böylece max_edge_nm'den kısa her çift aynı
    ya da komşu hücrededir; O(n²) tarama gerekmez.

    Tarih çizgisi (±180°): her düğüm ızgaraya üç boylam kopyasıyla
    (lon, lon±360°) yerleştirilir; böylece 179°E ile 179°W komşu sayılır.

    Her hücre yalnızca dört ileri komşusuyla eşleştirilir; böylece her
    sırasız hücre çifti bir kez taranır. Aynı düğüm çifti birden fazla
    kopya yüzünden tekrar üretilirse atlanır.
    """
    cell = max(20.0, float(max_edge_nm))
    buckets: dict = {}

    for idx, (node_id, data) in enumerate(nodes):
        lat = data.get("latitude", 0.0)
        lon = data.get("longitude", 0.0)
        cos_lat = math.cos(math.radians(lat))
        y = lat * 60.0
        for shift in (0.0, 360.0, -360.0):
            x = (lon + shift) * cos_lat * 60.0
            key = (int(math.floor(x / cell)), int(math.floor(y / cell)))
            buckets.setdefault(key, []).append((idx, node_id, data))

    emitted: set = set()

    def unique(a, b):
        lo, hi = (a, b) if a[0] < b[0] else (b, a)
        key = (lo[0], hi[0])
        if key in emitted:
            return None
        emitted.add(key)
        return _pair(lo, hi)

    # 1) Aynı hücredeki çiftler
    for items in buckets.values():
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                pair = unique(items[i], items[j])
                if pair:
                    yield pair

    # 2) Komşu hücreler: her hücre yalnızca (1,0), (1,1), (1,-1), (0,1)
    forward_offsets = ((1, 0), (1, 1), (1, -1), (0, 1))
    for (cx, cy), items in buckets.items():
        for dx, dy in forward_offsets:
            other = buckets.get((cx + dx, cy + dy))
            if not other:
                continue
            for a in items:
                for b in other:
                    if a[0] == b[0]:
                        continue
                    pair = unique(a, b)
                    if pair:
                        yield pair


def _pair(a, b):
    _, n1, d1 = a
    _, n2, d2 = b
    return n1, d1, n2, d2


def _airport_node(airport: dict) -> dict:
    """Havalimanı bilgisini graf düğüm formatına dönüştür."""
    return {
        "latitude": airport["latitude"],
        "longitude": airport["longitude"],
        "type": "airport",
        "name": airport.get("name", ""),
        "icao": airport.get("icao", ""),
        "iata": airport.get("iata", ""),
        "elevation_ft": airport.get("elevation_ft"),
    }


def graph_stats(G: nx.DiGraph) -> dict:
    """Graf boyutu ve hava sahası bilgisi."""
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "great_circle_nm": G.graph.get("great_circle_nm"),
        "effective_max_edge_nm": G.graph.get("effective_max_edge_nm"),
        "airspace_avoidance": G.graph.get("airspace_avoidance", "off"),
        "airspace_blocked_edges": G.graph.get("airspace_blocked_edges", 0),
        "airspace_note": G.graph.get("airspace_note"),
    }
