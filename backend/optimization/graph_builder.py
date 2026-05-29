"""
SkyOptimizer AI — Global Waypoint Graf Oluşturucu
Herhangi iki havalimanı arası dinamik waypoint ağı üretir.
Great-circle rota üzerinde ve koridor boyunca noktalar oluşturulur.
A* algoritması bu graf üzerinde optimum rotayı bulur.

Desteklenen menzil: 50 NM — 12,000 NM (yerel → transatlantik)
"""

import math
import networkx as nx
from typing import Optional

from services.airport_service import get_airport, get_corridor_airports
from utils.geo import haversine_nm, initial_bearing, great_circle_waypoints


def build_waypoint_graph(
    origin_icao: str,
    destination_icao: str,
    intermediate_airports: Optional[list] = None,
    max_edge_distance_nm: float = 350,
    grid_spacing_deg: float = 1.0,
) -> nx.DiGraph:
    """
    Kalkış ve varış arasında dinamik waypoint grafiği oluşturur.

    Yaklaşım:
    1. Kalkış ve varış havalimanlarını ekle
    2. Great-circle üzerinde ~100 NM aralıklarla ana waypoint'ler
    3. Koridor boyunca (±30, ±60, ±100 NM) alternatif noktalar
    4. Koridordaki gerçek havalimanlarını dahil et
    5. Mesafe bazlı kenarlar oluştur

    Bu yapı herhangi iki havalimanı arasında çalışır (LTFM-LTAI, KJFK-EGLL vb.)

    Returns:
        networkx DiGraph — A* ile optimize edilecek graf
    """
    G = nx.DiGraph()

    # 1. Kalkış ve varış havalimanları
    origin = get_airport(origin_icao)
    dest = get_airport(destination_icao)

    if not origin or not dest:
        return G

    G.add_node(origin_icao, **_airport_node(origin))
    G.add_node(destination_icao, **_airport_node(dest))

    olat, olon = origin["latitude"], origin["longitude"]
    dlat, dlon = dest["latitude"], dest["longitude"]
    total_dist = haversine_nm(olat, olon, dlat, dlon)

    # 2. Great-circle üzerinde ana waypoint'ler
    # Kısa rotalarda çok daha sık aralık → daha fazla alternatif yol
    if total_dist > 500:
        spacing_nm = 100
    elif total_dist > 300:
        spacing_nm = 50
    elif total_dist > 150:
        spacing_nm = 30  # Kısa iç hat rotaları için 30 NM aralık
    else:
        spacing_nm = 20  # Çok kısa rotalar için 20 NM aralık
    num_gc_points = max(5, int(total_dist / spacing_nm))  # En az 5 nokta
    gc_waypoints = great_circle_waypoints(olat, olon, dlat, dlon, num_gc_points)

    for i, (lat, lon) in enumerate(gc_waypoints[1:-1], 1):
        wp_id = f"WP_{i:03d}"
        G.add_node(wp_id, latitude=lat, longitude=lon,
                   type="waypoint", name=f"WP-{i}")

    # 3. Koridor waypoint'leri (rota ekseninin sağ/solunda)
    # Uzun rotalarda daha geniş koridor, kısa rotalarda daha sık ve dar koridor
    if total_dist > 2000:
        offsets_nm = [-200, -120, -60, 60, 120, 200]  # Transatlantik — jet stream yakalar
    elif total_dist > 1000:
        offsets_nm = [-150, -80, -40, 40, 80, 150]  # Kıtalar arası
    elif total_dist > 400:
        offsets_nm = [-80, -40, 40, 80]
    elif total_dist > 150:
        offsets_nm = [-60, -40, -25, -10, 10, 25, 40, 60]
    else:
        offsets_nm = [-40, -25, -10, 10, 25, 40]

    route_bearing = initial_bearing(olat, olon, dlat, dlon)

    for i, (lat, lon) in enumerate(gc_waypoints[1:-1], 1):
        for j, offset in enumerate(offsets_nm):
            # Rota eksenine dik yönde sapma
            offset_deg = offset / 60  # 1 derece ≈ 60 NM
            perp_bearing = (route_bearing + 90) % 360
            dlat_off = offset_deg * math.cos(math.radians(perp_bearing))
            dlon_off = offset_deg * math.sin(math.radians(perp_bearing)) / max(
                math.cos(math.radians(lat)), 0.01
            )

            wp_id = f"COR_{j}_{i:03d}"
            G.add_node(wp_id, latitude=lat + dlat_off, longitude=lon + dlon_off,
                       type="corridor", name=f"C{j}-{i}")

    # 4. Koridordaki gerçek havalimanlarını dahil et
    corridor_airports = get_corridor_airports(
        olat, olon, dlat, dlon,
        radius_nm=min(total_dist * 0.4, 300),
    )
    for ap in corridor_airports:
        if ap["icao"] in (origin_icao, destination_icao):
            continue
        G.add_node(ap["icao"], **_airport_node(ap))

    # 5. Ara havalimanları (varsa)
    if intermediate_airports:
        for ap_icao in intermediate_airports:
            ap = get_airport(ap_icao)
            if ap:
                G.add_node(ap_icao, **_airport_node(ap))

    # 6. Kenarları oluştur
    # Direkt origin→dest kenarı OLUŞTURULMAZ — A* ara waypoint'lerden geçmek zorunda
    if total_dist <= 500:
        effective_max_edge = total_dist * 0.35  # Daha fazla ara waypoint kullanmaya zorla
        effective_max_edge = max(effective_max_edge, 60)  # En az 60 NM
    else:
        effective_max_edge = min(max_edge_distance_nm, total_dist * 0.5)
        effective_max_edge = max(effective_max_edge, 200)

    nodes = list(G.nodes(data=True))
    for i, (n1, d1) in enumerate(nodes):
        for n2, d2 in nodes[i + 1:]:
            # Direkt origin→dest kenarını engelle
            if {n1, n2} == {origin_icao, destination_icao}:
                continue

            lat1 = d1.get("latitude", 0)
            lon1 = d1.get("longitude", 0)
            lat2 = d2.get("latitude", 0)
            lon2 = d2.get("longitude", 0)

            dist = haversine_nm(lat1, lon1, lat2, lon2)
            if 0 < dist <= effective_max_edge:
                bearing = initial_bearing(lat1, lon1, lat2, lon2)
                G.add_edge(n1, n2, distance_nm=dist, bearing=bearing)
                G.add_edge(n2, n1, distance_nm=dist,
                           bearing=(bearing + 180) % 360)

    return G


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
