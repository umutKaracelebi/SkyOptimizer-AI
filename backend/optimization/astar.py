"""
SkyOptimizer AI — A* Rota Optimizasyonu

İki rota AYNI graf, AYNI rüzgâr verisi ve AYNI fizik motoruyla aranır;
tek fark amaç fonksiyonudur:

  • standart rota  → en kısa mesafe (weight="distance_nm")
  • optimize rota  → en düşük kompozit maliyet (yakıt/süre/CO₂)

Bu, "rüzgâr-optimizasyonu yapmayan pilot en kısa yolu uçar" varsayımının
dürüst karşılığıdır: aynı hava koşullarında iki farklı hedef. Tasarruf
sıfır da çıkabilir — bu durum `routes_identical` ile bildirilir.
"""

from typing import Optional

import networkx as nx

from optimization.cost_model import CostModel
from optimization.graph_builder import build_waypoint_graph
from services.airport_service import get_airport
from utils.geo import haversine_nm

DEFAULT_WEIGHTS = {"fuel": 0.4, "time": 0.35, "co2": 0.25}


async def find_optimal_route(
    origin_icao: str,
    destination_icao: str,
    aircraft_type: str = "B738",
    weights: Optional[dict] = None,
    wind_data_map: Optional[dict] = None,
) -> dict:
    """
    Aynı hava koşullarında iki rota hesaplar ve karşılaştırır.

    Args:
        wind_data_map: {(lat, lon): {"speed": kts, "dir": deg}} — rota boyunca
            örneklenmiş rüzgârlar. Boşsa her iki rota da rüzgârsız hesaplanır
            ve sonuçlar büyük olasılıkla çakışır.
    """
    origin = get_airport(origin_icao)
    dest = get_airport(destination_icao)

    if not origin or not dest:
        return {"error": "Havalimanları bulunamadı"}

    cost_model = CostModel(aircraft_type)
    opt_weights = cost_model._normalize_weights(weights or DEFAULT_WEIGHTS)
    wind_map = wind_data_map or {}

    G = build_waypoint_graph(origin_icao, destination_icao)
    if G.number_of_nodes() < 3 or not nx.has_path(G, origin_icao, destination_icao):
        return {"error": "Yetersiz waypoint grafiği"}

    # ─── 1) Kenar maliyetleri (rüzgâr dahil, her iki rota için ortak) ──
    _cost_edges(G, cost_model, wind_map)

    # ─── 2) Standart rota: en kısa mesafe ──────────────────────────────
    std_path = nx.astar_path(
        G, origin_icao, destination_icao,
        heuristic=lambda n1, n2: _dist(G, n1, n2),
        weight="distance_nm",
    )
    standard = _extract_route_info(G, std_path, "standard")

    # ─── 3) Normalizasyon referansı = standart rota ────────────────────
    # Ağırlıklar standart rotanın toplamlarına göre normalize edilir, böylece
    # standart rotanın kompozit maliyeti 1.0 olur ve optimize rota ≤ 1.0 bulur.
    reference = {
        "fuel_kg": standard["estimated_fuel_kg"],
        "time_min": standard["estimated_time_min"],
        "co2_kg": standard["co2_emission_kg"],
    }

    # ─── 4) Kenar ağırlıkları: kompozit maliyet ────────────────────────
    min_cost_per_nm = _apply_composite_weights(G, cost_model, opt_weights, reference)

    # ─── 5) Optimize rota: en düşük kompozit maliyet ───────────────────
    # Heuristic: haversine × kenar başına en düşük maliyet → admissible
    # ve tutarlı (consistent) bir alt sınır.
    opt_path = nx.astar_path(
        G, origin_icao, destination_icao,
        heuristic=lambda n1, n2: _dist(G, n1, n2) * min_cost_per_nm,
        weight="weight",
    )
    optimized = _extract_route_info(G, opt_path, "optimized")

    # ─── 6) Karşılaştırma ──────────────────────────────────────────────
    savings = _calculate_savings(standard, optimized)

    # Ölçülebilir tasarruf eşiği: %0.1'in altındaki fark yuvarlama/örnekleme
    # gürültüsüdür, optimizasyon kazancı olarak sunulmamalı.
    has_savings = (
        abs(savings["fuel_saved_percent"]) >= 0.1
        or abs(savings["time_saved_percent"]) >= 0.1
    )

    return {
        "optimized_route": optimized,
        "standard_route": standard,
        "savings": savings,
        # Düğüm dizisi birebir aynıysa (rüzgârsız rotada beklenir)
        "routes_identical": std_path == opt_path,
        # Ölçülebilir kazanç var mı — arayüz "fark yok" mesajını buna göre verir
        "has_measurable_savings": has_savings,
        "comparison_basis": {
            "description": (
                "İki rota aynı rüzgâr verisi ve aynı fizik motoruyla hesaplandı. "
                "Standart rota en kısa mesafeyi, optimize rota en düşük kompozit "
                "maliyeti (yakıt/süre/CO₂) minimize eder."
            ),
            "weights": {k: round(v, 3) for k, v in opt_weights.items()},
            "wind_samples": len(wind_map),
        },
        "graph_stats": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  Yardımcılar
# ═══════════════════════════════════════════════════════════════════

def _dist(G: nx.DiGraph, n1: str, n2: str) -> float:
    """İki düğüm arası haversine mesafesi (NM)."""
    d1, d2 = G.nodes[n1], G.nodes[n2]
    return haversine_nm(
        d1.get("latitude", 0), d1.get("longitude", 0),
        d2.get("latitude", 0), d2.get("longitude", 0),
    )


def _nearest_wind(G: nx.DiGraph, u: str, v: str, wind_map: dict) -> dict:
    """Kenar orta noktasına en yakın rüzgâr örneğini bul."""
    if not wind_map:
        return {"speed": 0, "dir": 0}

    u_node, v_node = G.nodes[u], G.nodes[v]
    mid_lat = (u_node.get("latitude", 0) + v_node.get("latitude", 0)) / 2
    mid_lon = (u_node.get("longitude", 0) + v_node.get("longitude", 0)) / 2

    best_wind, best_dist = {"speed": 0, "dir": 0}, float("inf")
    for (wlat, wlon), wdata in wind_map.items():
        d = (mid_lat - wlat) ** 2 + (mid_lon - wlon) ** 2
        if d < best_dist:
            best_dist, best_wind = d, wdata
    return best_wind


def _cost_edges(G: nx.DiGraph, cost_model: CostModel, wind_map: dict) -> None:
    """
    Her kenar için rüzgârlı yakıt/süre/CO₂ maliyetlerini hesaplar.

    KENAR BAŞINA AYNI FİZİK: standart ve optimize rota aynı kenar
    değerlerini kullanır, böylece karşılaştırma eşit koşullarda olur.
    """
    for u, v, data in G.edges(data=True):
        wind = _nearest_wind(G, u, v, wind_map)
        segment = cost_model.calculate_segment_cost(
            distance_nm=data.get("distance_nm", 0),
            wind_speed_kts=wind["speed"],
            wind_direction=wind["dir"],
            aircraft_heading=data.get("bearing", 0),
        )
        data["fuel_kg"] = segment["fuel_kg"]
        data["time_min"] = segment["time_min"]
        data["co2_kg"] = segment["co2_kg"]
        data["ground_speed_kts"] = segment["ground_speed_kts"]
        data["headwind_kts"] = segment["headwind_kts"]


def _apply_composite_weights(
    G: nx.DiGraph,
    cost_model: CostModel,
    weights: dict,
    reference: dict,
) -> float:
    """
    Kenarlara kompozit maliyet ağırlığı yazar ve kenar başına en düşük
    maliyeti (NM başına) döndürür — A* heuristic'i için alt sınır.
    """
    min_per_nm = float("inf")

    for _, _, data in G.edges(data=True):
        composite = cost_model.composite_cost(
            fuel_kg=data.get("fuel_kg", 0),
            time_min=data.get("time_min", 0),
            co2_kg=data.get("co2_kg", 0),
            weights=weights,
            reference=reference,
        )
        data["weight"] = composite

        distance = data.get("distance_nm", 0)
        if distance > 0:
            min_per_nm = min(min_per_nm, composite / distance)

    return 0.0 if min_per_nm == float("inf") else min_per_nm


def _extract_route_info(G: nx.DiGraph, path: list, route_type: str) -> dict:
    """Yol üzerindeki waypoint ve maliyet bilgilerini çıkar."""
    waypoints = []
    total_fuel = 0.0
    total_time = 0.0
    total_co2 = 0.0
    total_distance = 0.0

    for node in path:
        nd = G.nodes[node]
        waypoints.append({
            "id": node,
            "name": nd.get("name", node),
            "latitude": nd.get("latitude", 0),
            "longitude": nd.get("longitude", 0),
            "type": nd.get("type", "waypoint"),
        })

    for i in range(len(path) - 1):
        edge = G.edges[path[i], path[i + 1]]
        total_fuel += edge.get("fuel_kg", 0)
        total_time += edge.get("time_min", 0)
        total_co2 += edge.get("co2_kg", 0)
        total_distance += edge.get("distance_nm", 0)

    return {
        "type": route_type,
        "waypoints": waypoints,
        "total_distance_nm": round(total_distance, 1),
        "estimated_fuel_kg": round(total_fuel, 1),
        "estimated_time_min": round(total_time, 1),
        "co2_emission_kg": round(total_co2, 1),
        "waypoint_count": len(waypoints),
    }


def _calculate_savings(standard: dict, optimized: dict) -> dict:
    """
    Standart ve optimize rota arasındaki tasarruf.

    Negatif değerler 0'a kırpılmaz — optimize rota kötü çıkarsa bu
    görünür olmalı (heuristic/ağırlık hatası belirtisidir).
    """
    fuel_saved = standard["estimated_fuel_kg"] - optimized["estimated_fuel_kg"]
    time_saved = standard["estimated_time_min"] - optimized["estimated_time_min"]
    co2_saved = standard["co2_emission_kg"] - optimized["co2_emission_kg"]
    distance_delta = (
        optimized["total_distance_nm"] - standard["total_distance_nm"]
    )

    fuel_pct = (
        fuel_saved / standard["estimated_fuel_kg"] * 100
        if standard["estimated_fuel_kg"] > 0 else 0.0
    )
    time_pct = (
        time_saved / standard["estimated_time_min"] * 100
        if standard["estimated_time_min"] > 0 else 0.0
    )

    return {
        "fuel_saved_kg": round(fuel_saved, 1),
        "fuel_saved_percent": round(fuel_pct, 2),
        "time_saved_min": round(time_saved, 1),
        "time_saved_percent": round(time_pct, 2),
        "co2_saved_kg": round(co2_saved, 1),
        "cost_saved_usd": round(fuel_saved * 0.80, 2),
        # Optimize rota daha uzun olabilir (rüzgârdan kaçınmak için) —
        # bunu gizlemek yerine raporla.
        "distance_delta_nm": round(distance_delta, 1),
    }
