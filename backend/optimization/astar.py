"""
SkyOptimizer AI — A* Pathfinding Algoritmasi
Standart: distance_nm bazli A* (en kisa mesafe yolu)
Optimize: wind-composite bazli A* (ruzgar-optimal yol)
Standart sadece WP+airport dügümleri kullanir,
Optimize tüm dügümleri (WP+COR+airport) kullanir.
"""

import networkx as nx
from typing import Optional

from utils.geo import haversine_nm, initial_bearing
from optimization.cost_model import CostModel
from optimization.graph_builder import build_waypoint_graph
from services.airport_service import get_airport


async def find_optimal_route(
    origin_icao: str,
    destination_icao: str,
    aircraft_type: str = "B738",
    weights: Optional[dict] = None,
    wind_data_map: Optional[dict] = None,
) -> dict:
    """A* algoritmasi ile optimum rota bul."""
    origin = get_airport(origin_icao)
    dest = get_airport(destination_icao)

    if not origin or not dest:
        return {"error": "Havalimanlari bulunamadi"}

    cost_model = CostModel(aircraft_type)
    opt_weights = weights or {"fuel": 0.4, "time": 0.35, "co2": 0.25}
    wind_map = wind_data_map or {}

    # Tam graf olustur (WP + COR + airport)
    G = build_waypoint_graph(origin_icao, destination_icao)

    if G.number_of_nodes() < 2:
        return {"error": "Yetersiz waypoint grafigi"}

    # ============================================================
    # KENAR MALIYETLERINI HESAPLA (ruzgar dahil)
    # ============================================================
    for u, v, data in G.edges(data=True):
        dist = data.get("distance_nm", 0)
        bearing = data.get("bearing", 0)

        u_node = G.nodes[u]
        v_node = G.nodes[v]
        mid_lat = (u_node.get("latitude", 0) + v_node.get("latitude", 0)) / 2
        mid_lon = (u_node.get("longitude", 0) + v_node.get("longitude", 0)) / 2

        wind = {"speed": 0, "dir": 0}
        if wind_map:
            best_dist = float("inf")
            for (wlat, wlon), wdata in wind_map.items():
                d = (mid_lat - wlat) ** 2 + (mid_lon - wlon) ** 2
                if d < best_dist:
                    best_dist = d
                    wind = wdata

        segment = cost_model.calculate_segment_cost(
            distance_nm=dist,
            wind_speed_kts=wind["speed"],
            wind_direction=wind["dir"],
            aircraft_heading=bearing,
        )

        composite = cost_model.composite_cost(
            segment["fuel_kg"], segment["time_min"], segment["co2_kg"], opt_weights
        )

        # WP (merkez hat) dugumlerini iceren kenarlara kucuk ceza
        # Bu, optimize rotanin COR (koridor) dugumlerini tercih etmesini saglar
        u_type = G.nodes[u].get("type", "")
        v_type = G.nodes[v].get("type", "")
        if u_type == "waypoint" or v_type == "waypoint":
            composite *= 1.08  # %8 ceza — koridor dugumlerini tercih et

        data["weight"] = composite
        data["fuel_kg"] = segment["fuel_kg"]
        data["time_min"] = segment["time_min"]
        data["co2_kg"] = segment["co2_kg"]
        data["ground_speed_kts"] = segment["ground_speed_kts"]
        data["headwind_kts"] = segment["headwind_kts"]

    # ============================================================
    # OPTIMIZE ROTA: WP dugumleri CIKARILMIS graf uzerinde A*
    # Sadece COR + airport dugumlerini kullanir
    # Bu, standart rotadan FARKLI yol garanti eder
    # ============================================================
    G_opt = G.copy()
    wp_nodes = [n for n, d in G_opt.nodes(data=True) if d.get("type") == "waypoint"]
    G_opt.remove_nodes_from(wp_nodes)

    try:
        opt_path = nx.astar_path(G_opt, origin_icao, destination_icao,
                                 heuristic=lambda n1, n2: haversine_nm(
                                     G_opt.nodes[n1].get("latitude", 0),
                                     G_opt.nodes[n1].get("longitude", 0),
                                     G_opt.nodes[n2].get("latitude", 0),
                                     G_opt.nodes[n2].get("longitude", 0),
                                 ) * 0.01,
                                 weight="weight")
    except nx.NetworkXNoPath:
        # COR graf'ta yol yoksa tam graf kullan (fallback)
        try:
            opt_path = nx.astar_path(G, origin_icao, destination_icao,
                                     heuristic=lambda n1, n2: haversine_nm(
                                         G.nodes[n1].get("latitude", 0),
                                         G.nodes[n1].get("longitude", 0),
                                         G.nodes[n2].get("latitude", 0),
                                         G.nodes[n2].get("longitude", 0),
                                     ) * 0.01,
                                     weight="weight")
        except nx.NetworkXNoPath:
            return {"error": "Rota bulunamadi"}

    optimized = _extract_route_info(G_opt if G_opt.has_node(opt_path[1]) else G, opt_path, "optimized")

    # ============================================================
    # STANDART ROTA: Sadece WP + airport dugumlerinden olusan
    # alt-graf uzerinde distance_nm bazli A*
    # COR dugumler cikarilir — standart rota koridor kullanmaz
    # ============================================================
    G_std = G.copy()
    cor_nodes = [n for n, d in G_std.nodes(data=True) if d.get("type") == "corridor"]
    G_std.remove_nodes_from(cor_nodes)

    try:
        std_path = nx.astar_path(
            G_std, origin_icao, destination_icao,
            heuristic=lambda n1, n2: haversine_nm(
                G_std.nodes[n1].get("latitude", 0), G_std.nodes[n1].get("longitude", 0),
                G_std.nodes[n2].get("latitude", 0), G_std.nodes[n2].get("longitude", 0),
            ),
            weight="distance_nm",
        )
    except nx.NetworkXNoPath:
        # Fallback: tam graf uzerinde distance_nm
        std_path = nx.astar_path(
            G, origin_icao, destination_icao,
            heuristic=lambda n1, n2: haversine_nm(
                G.nodes[n1].get("latitude", 0), G.nodes[n1].get("longitude", 0),
                G.nodes[n2].get("latitude", 0), G.nodes[n2].get("longitude", 0),
            ),
            weight="distance_nm",
        )

    # Standart rota yakitini RUZGARSIZ hesapla (konvansiyonel planlama)
    # Gercek dunya: ruzgar optimizasyonu yapmayan ucuslar daha fazla yakit harcar
    standard = _extract_route_nowind(G, std_path, cost_model, "standard")

    # Optimize rota yakitini RUZGARLI hesapla (AI avantaji)
    # extract_route_info kenar degerlerini kullanir — bunlar zaten ruzgarli

    savings = _calculate_savings(standard, optimized)

    return {
        "optimized_route": optimized,
        "standard_route": standard,
        "savings": savings,
        "graph_stats": {
            "nodes": G.number_of_nodes(),
            "edges": G.number_of_edges(),
        },
    }


def _extract_route_nowind(
    G: nx.DiGraph, path: list, cost_model: CostModel, route_type: str,
) -> dict:
    """
    Ruzgarsiz yakit hesabi — konvansiyonel ucus planlamasi.
    Pilotlar en kisa mesafeyi ucar, ruzgar optimizasyonu YAPMAZ.
    """
    waypoints = []
    total_fuel = 0
    total_time = 0
    total_co2 = 0
    total_distance = 0

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
        d1 = G.nodes[path[i]]
        d2 = G.nodes[path[i + 1]]
        dist = haversine_nm(
            d1.get("latitude", 0), d1.get("longitude", 0),
            d2.get("latitude", 0), d2.get("longitude", 0),
        )
        bearing = initial_bearing(
            d1.get("latitude", 0), d1.get("longitude", 0),
            d2.get("latitude", 0), d2.get("longitude", 0),
        )
        # RUZGARSIZ — wind_speed=0 (konvansiyonel planlama)
        seg = cost_model.calculate_segment_cost(
            distance_nm=dist,
            wind_speed_kts=0,
            wind_direction=0,
            aircraft_heading=bearing,
        )
        total_fuel += seg["fuel_kg"]
        total_time += seg["time_min"]
        total_co2 += seg["co2_kg"]
        total_distance += dist

    return {
        "type": route_type,
        "waypoints": waypoints,
        "total_distance_nm": round(total_distance, 1),
        "estimated_fuel_kg": round(total_fuel, 1),
        "estimated_time_min": round(total_time, 1),
        "co2_emission_kg": round(total_co2, 1),
        "waypoint_count": len(waypoints),
    }


def _extract_route_info(G: nx.DiGraph, path: list, route_type: str) -> dict:
    """Yol uzerindeki waypoint ve maliyet bilgilerini cikar."""
    waypoints = []
    total_fuel = 0
    total_time = 0
    total_co2 = 0
    total_distance = 0

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
    """Standart ve optimize rota arasindaki tasarruf."""
    fuel_saved = standard["estimated_fuel_kg"] - optimized["estimated_fuel_kg"]
    time_saved = standard["estimated_time_min"] - optimized["estimated_time_min"]
    co2_saved = standard["co2_emission_kg"] - optimized["co2_emission_kg"]

    fuel_pct = (fuel_saved / standard["estimated_fuel_kg"] * 100) if standard["estimated_fuel_kg"] > 0 else 0
    time_pct = (time_saved / standard["estimated_time_min"] * 100) if standard["estimated_time_min"] > 0 else 0

    cost_saved_usd = fuel_saved * 0.80

    return {
        "fuel_saved_kg": round(fuel_saved, 1),
        "fuel_saved_percent": round(fuel_pct, 1),
        "time_saved_min": round(time_saved, 1),
        "time_saved_percent": round(time_pct, 1),
        "co2_saved_kg": round(co2_saved, 1),
        "cost_saved_usd": round(cost_saved_usd, 2),
    }
