"""
SkyOptimizer AI — A* Rota Optimizasyonu (4B)

İki rota AYNI graf, AYNI rüzgâr verisi ve AYNI fizik motoruyla aranır;
tek fark amaç fonksiyonudur:

  • standart rota  → en kısa mesafe (weight="distance_nm")
  • optimize rota  → en düşük kompozit maliyet (yakıt/süre/CO₂)

Ek boyutlar:
  • Cost index (CI)     → cruise hızı; yakıt–zaman takası
  • İrtifa katmanları   → FL240/300/340/390 arasında seçim
  • Kütle azalması      → rota profili yakıt yandıkça hafifler
  • Tırmanma/alçalma    → toplam süre ve yakıta eklenir
  • Kısıtlı hava sahası → graf kenarları elenir

Tasarruf sıfır da çıkabilir — bu durum `routes_identical` ve
`has_measurable_savings` ile dürüstçe bildirilir.
"""

from functools import lru_cache
import math
import time
from typing import Optional

import networkx as nx

from optimization.cost_model import CostModel
from optimization.graph_builder import build_waypoint_graph, graph_stats
from optimization.performance import (
    CI_DEFAULT,
    FUEL_PRICE_USD_PER_KG,
    METHOD_NOTES,
    get_performance,
)
from services.airport_service import get_airport
from services.airspace_service import relevant_features
from utils.geo import haversine_nm

DEFAULT_WEIGHTS = {"fuel": 0.4, "time": 0.35, "co2": 0.25}

# Ağırlıklandırılmış mutlak maliyet için birim fiyatlar (USD).
# Yakıt fiyatı performance modülünden gelir; süre ve karbon maliyeti
# havayolu işletme maliyeti mertebesindedir (uçuş ekibi, bakım, sahiplik).
TIME_COST_USD_PER_MIN = 25.0
CARBON_PRICE_USD_PER_KG = 0.08


async def find_optimal_route(
    origin_icao: str,
    destination_icao: str,
    aircraft_type: str = "B738",
    weights: Optional[dict] = None,
    wind_data_map: Optional[dict] = None,
    cost_index: float = CI_DEFAULT,
    wind_levels: Optional[dict] = None,
    avoid_airspace: bool = True,
) -> dict:
    """
    Aynı hava koşullarında iki rota hesaplar ve karşılaştırır.

    Args:
        wind_data_map: {(lat, lon): {"speed": kts, "dir": deg}} — tek seviye
            (geriye uyumlu; tüm katmanlarda kullanılır).
        wind_levels: {level_mb: wind_data_map} — 3B rüzgâr. Örn.
            {300: {...}, 250: {...}, 200: {...}}
        cost_index: 0-200. Cruise hızını belirler.
        avoid_airspace: kısıtlı hava sahalarını kesen kenarları ele.
    """
    origin = get_airport(origin_icao)
    dest = get_airport(destination_icao)
    if not origin or not dest:
        return {"error": "Havalimanları bulunamadı"}

    perf = get_performance(aircraft_type)
    cost_model = CostModel(
        aircraft_type,
        cost_index=cost_index,
    )
    opt_weights = cost_model._normalize_weights(weights or DEFAULT_WEIGHTS)
    ci = float(max(0.0, min(200.0, cost_index)))

    gc_distance = haversine_nm(
        origin["latitude"], origin["longitude"],
        dest["latitude"], dest["longitude"],
    )
    started_at = time.perf_counter()
    G = build_waypoint_graph(
        origin_icao, destination_icao, avoid_airspace=avoid_airspace
    )
    topology_ms = (time.perf_counter() - started_at) * 1000.0
    if G.number_of_nodes() < 3 or not nx.has_path(G, origin_icao, destination_icao):
        return {"error": "Yetersiz waypoint grafiği"}

    # ─── Rüzgâr katmanları ─────────────────────────────────────────
    single_level_map = wind_data_map or None
    levels = wind_levels or {}
    candidates = perf.candidate_levels(gc_distance)

    # Tek seviye verilmişse her adayda onu kullan (geriye uyumluluk)
    fallback_map = single_level_map if single_level_map is not None else {}
    available_maps = {
        lv: (levels.get(lv) or fallback_map) for lv, _ in candidates
    }
    level_wind_counts = {
        lv: len(m) for lv, m in available_maps.items()
    }

    # ─── Her katman için iki rota ──────────────────────────────────
    level_results = []
    baseline_choice = None
    best_opt = None

    for level_mb, alt_ft in candidates:
        wind_map = available_maps[level_mb]
        node_winds = _node_winds(G, wind_map)

        std_path = nx.astar_path(
            G, origin_icao, destination_icao,
            heuristic=lambda n1, n2: _dist(G, n1, n2),
            weight="distance_nm",
        )
        std_profile = _profile_for_path(
            G, std_path, perf, alt_ft, ci,
            origin, dest, node_winds,
        )

        reference = {
            "fuel_kg": std_profile["fuel_kg"],
            "time_min": std_profile["time_min"],
            "co2_kg": std_profile["co2_kg"],
        }
        min_cost_per_nm = _apply_composite_edge_costs(
            G, perf, alt_ft, ci, opt_weights, reference, node_winds,
            mass_kg=std_profile["takeoff_mass_kg"]
            - 0.5 * std_profile["fuel_kg"],
        )

        opt_path = nx.astar_path(
            G, origin_icao, destination_icao,
            heuristic=lambda n1, n2: _dist(G, n1, n2) * min_cost_per_nm,
            weight="weight",
        )
        opt_profile = _profile_for_path(
            G, opt_path, perf, alt_ft, ci,
            origin, dest, node_winds,
        )

        entry = {
            "level_mb": level_mb,
            "altitude_ft": alt_ft,
            "label": f"FL{int(round(alt_ft / 100)):03d}",
            "wind_samples": len(wind_map),
            "standard": {
                "waypoints": _waypoints(G, std_path),
                "profile": std_profile,
                "score_usd": _weighted_score(std_profile, opt_weights),
            },
            "optimized": {
                "waypoints": _waypoints(G, opt_path),
                "profile": opt_profile,
                "score_usd": _weighted_score(opt_profile, opt_weights),
                "same_path_as_standard": std_path == opt_path,
            },
            "metric": _level_metric(std_profile, opt_profile, opt_weights),
        }
        level_results.append(entry)

        if baseline_choice is None or entry["standard"]["score_usd"] < baseline_choice["standard"]["score_usd"]:
            baseline_choice = entry
        if best_opt is None or entry["optimized"]["score_usd"] < best_opt["optimized"]["score_usd"]:
            best_opt = entry

    if baseline_choice is None or best_opt is None:  # pragma: no cover
        return {"error": "Uygun irtifa katmanı bulunamadı"}

    # ─── Güvenlik ağı: profil değerlendirmesi standarttan kötüyse ───
    reverted = False
    if best_opt["optimized"]["score_usd"] > baseline_choice["standard"]["score_usd"] + 1e-6:
        reverted = True
        chosen_opt = baseline_choice
        opt_waypoints = baseline_choice["standard"]["waypoints"]
        opt_profile = baseline_choice["standard"]["profile"]
        opt_level = baseline_choice
    else:
        chosen_opt = best_opt
        opt_waypoints = best_opt["optimized"]["waypoints"]
        opt_profile = best_opt["optimized"]["profile"]
        opt_level = best_opt

    std_waypoints = baseline_choice["standard"]["waypoints"]
    std_profile = baseline_choice["standard"]["profile"]

    standard = _route_info(
        std_waypoints, std_profile, "standard",
        baseline_choice["level_mb"], baseline_choice["altitude_ft"],
    )
    optimized = _route_info(
        opt_waypoints, opt_profile, "optimized",
        opt_level["level_mb"], opt_level["altitude_ft"],
    )

    savings = _calculate_savings(standard, optimized)
    score_standard = _weighted_score(std_profile, opt_weights)
    score_optimized = _weighted_score(opt_profile, opt_weights)
    savings["score_standard_usd"] = score_standard
    savings["score_optimized_usd"] = score_optimized
    savings["score_saved_usd"] = round(score_standard - score_optimized, 2)
    savings["score_saved_percent"] = round(
        (score_standard - score_optimized) / score_standard * 100
        if score_standard else 0.0, 2
    )
    has_savings = (
        abs(savings["fuel_saved_percent"]) >= 0.1
        or abs(savings["time_saved_percent"]) >= 0.1
        or abs(savings["score_saved_percent"]) >= 0.1
    )

    # Aynı düğüm dizisi mi?
    routes_identical = _waypoint_ids(std_waypoints) == _waypoint_ids(opt_waypoints)

    # Katman karşılaştırma tablosu (arayüzde gösterilir)
    level_table = [
        {
            "level_mb": lv["level_mb"],
            "label": lv["label"],
            "altitude_ft": lv["altitude_ft"],
            "wind_samples": lv["wind_samples"],
            "standard_fuel_kg": lv["standard"]["profile"]["fuel_kg"],
            "optimized_fuel_kg": lv["optimized"]["profile"]["fuel_kg"],
            "standard_time_min": lv["standard"]["profile"]["time_min"],
            "optimized_time_min": lv["optimized"]["profile"]["time_min"],
            "score_usd": lv["optimized"]["score_usd"],
            "selected_standard": lv is baseline_choice,
            "selected_optimized": lv is opt_level,
        }
        for lv in level_results
    ]

    feasibility = {
        "feasible": bool(optimized.get("feasible", True)),
        "fuel_capacity_kg": optimized.get("fuel_capacity_kg"),
        "fuel_margin_kg": optimized.get("fuel_margin_kg"),
        "note": (
            None if optimized.get("feasible", True) else
            "Tahmini yakıt, uçağın yakıt kapasitesini aşıyor; bu rota "
            "tek yakıt ikmaliyle uçulamaz. Daha uzun menzilli bir uçak "
            "tipi seçin veya ara iniş ekleyin."
        ),
    }

    airspace = {
        "avoidance": G.graph.get("airspace_avoidance", "off"),
        "blocked_edges": G.graph.get("airspace_blocked_edges", 0),
        "note": G.graph.get("airspace_note"),
        "areas_on_route": relevant_features(
            (origin["latitude"], origin["longitude"]),
            (dest["latitude"], dest["longitude"]),
        ),
    }

    if not perf.known_type:
        warning = (
            f"{aircraft_type} OpenAP veritabanında bulunamadı; B738 "
            "performansıyla yaklaşık hesaplandı."
        )
    elif perf.is_proxy:
        warning = (
            f"{aircraft_type} için OpenAP'ta doğrudan model yok; "
            f"{perf.performance_type} vekil performansı kullanıldı (±%5)."
        )
    else:
        warning = None

    return {
        "optimized_route": optimized,
        "standard_route": standard,
        "savings": savings,
        "routes_identical": routes_identical,
        "has_measurable_savings": has_savings,
        "comparison_basis": {
            "description": (
                "İki rota aynı rüzgâr verisi, aynı cost index ve aynı fizik "
                "motoruyla hesaplandı. Standart rota en kısa mesafeyi, optimize "
                "rota en düşük kompozit maliyeti (yakıt/süre/CO₂) minimize eder; "
                "irtifa katmanı her iki rota için de ayrı ayrı en iyi seçilir."
            ),
            "weights": {k: round(v, 3) for k, v in opt_weights.items()},
            "wind_samples": sum(level_wind_counts.values()),
            "wind_levels": level_wind_counts,
            "cost_index": int(ci),
            "time_cost_usd_per_min": TIME_COST_USD_PER_MIN,
            "fuel_price_usd_per_kg": FUEL_PRICE_USD_PER_KG,
        },
        "levels": level_table,
        "airspace": airspace,
        "feasibility": feasibility,
        "optimization_reverted": reverted,
        "graph_stats": {
            **graph_stats(G),
            "topology_ms": round(topology_ms, 1),
            "total_ms": round((time.perf_counter() - started_at) * 1000.0, 1),
        },
        "aircraft_performance": {
            "aircraft_type": aircraft_type,
            "known_type": perf.known_type,
            "performance_type": perf.performance_type,
            "is_proxy": perf.is_proxy,
            "cost_index": int(ci),
            "mach": round(perf.mach_for_ci(ci), 3),
            "cruise_altitude_ft": optimized["cruise_altitude_ft"],
            "takeoff_mass_kg": optimized["takeoff_mass_kg"],
            "landing_mass_kg": optimized["landing_mass_kg"],
            "method_notes": METHOD_NOTES,
        },
        "method_notes": METHOD_NOTES,
        "warnings": (
            [] if not warning else [warning]
        ),
    }


# ═══════════════════════════════════════════════════════════════════
#  Rüzgâr ataması
# ═══════════════════════════════════════════════════════════════════

@lru_cache(maxsize=16)
def _wind_vectors(wind_map_items: tuple) -> tuple:
    """Rüzgâr haritasını (lat, lon, u, v) demetine çevir (cache'li)."""
    out = []
    for lat, lon, speed, direction in wind_map_items:
        rad = math.radians(direction)
        # Meteorolojik yön "geldiği" yöndür; vektör "gittiği" yöne bakar.
        u = -speed * math.sin(rad)
        v = -speed * math.cos(rad)
        out.append((lat, lon, u, v))
    return tuple(out)


def _node_winds(G: nx.DiGraph, wind_map: dict) -> dict:
    """
    Her düğüme en yakın rüzgâr örneğinin (u, v) vektörünü ata.

    Kenar başına arama yapmak yerine düğüm başına bir kez arama yapılır:
    1.000 düğüm × 150 örnek = 150 bin işlem, 100 bin kenar × 150 örnekten
    çok daha ucuz.
    """
    if not wind_map:
        return {n: (0.0, 0.0) for n in G.nodes}

    items = tuple(
        (
            float(lat),
            ((float(lon) + 180) % 360) - 180,
            float(data.get("speed", 0) or 0),
            float(data.get("dir", 0) or 0),
        )
        for (lat, lon), data in wind_map.items()
    )
    vectors = _wind_vectors(items)

    assigned = {}
    for node, data in G.nodes(data=True):
        lat = data.get("latitude", 0.0)
        lon = ((data.get("longitude", 0.0) + 180) % 360) - 180
        best, best_d = (0.0, 0.0), float("inf")
        for wlat, wlon, u, v in vectors:
            d = (lat - wlat) ** 2 + (lon - wlon) ** 2
            if d < best_d:
                best_d, best = d, (u, v)
        assigned[node] = best
    return assigned


# ═══════════════════════════════════════════════════════════════════
#  Kenar maliyetleri
# ═══════════════════════════════════════════════════════════════════

def _apply_composite_edge_costs(
    G: nx.DiGraph,
    perf,
    altitude_ft: float,
    cost_index: float,
    weights: dict,
    reference: dict,
    node_winds: dict,
    mass_kg: float,
) -> float:
    """
    Kenarlara kompozit maliyet yazar; NM başına en düşük maliyeti döndürür
    (A* heuristic'i için alt sınır).
    """
    ref_fuel = reference.get("fuel_kg") or 1.0
    ref_time = reference.get("time_min") or 1.0
    ref_co2 = reference.get("co2_kg") or 1.0
    w_fuel, w_time, w_co2 = weights["fuel"], weights["time"], weights["co2"]

    tas = perf.tas_for_ci(cost_index, altitude_ft)
    ff = perf.fuel_flow_kg_s(mass_kg, tas, altitude_ft)
    ff_per_s = ff

    min_per_nm = float("inf")
    sin = math.sin
    cos = math.cos

    for u, v, data in G.edges(data=True):
        dist = data.get("distance_nm", 0.0)
        if dist <= 0:
            continue
        bearing = data.get("bearing", 0.0)
        u_wind = node_winds.get(u, (0.0, 0.0))
        v_wind = node_winds.get(v, (0.0, 0.0))
        mu = (u_wind[0] + v_wind[0]) * 0.5
        mv = (u_wind[1] + v_wind[1]) * 0.5
        brg = math.radians(bearing)
        headwind = -(mu * sin(brg) + mv * cos(brg))
        ground_speed = max(tas - headwind, 120.0)

        fuel = ff_per_s * (dist / ground_speed) * 3600.0
        time_min = dist / ground_speed * 60.0

        composite = (
            w_fuel * (fuel / ref_fuel)
            + w_time * (time_min / ref_time)
            + w_co2 * ((fuel * 3.16) / ref_co2)
        )
        data["weight"] = composite
        data["fuel_kg"] = fuel
        data["time_min"] = time_min
        data["co2_kg"] = fuel * 3.16
        data["headwind_kts"] = headwind

        if composite / dist < min_per_nm:
            min_per_nm = composite / dist

    return 0.0 if min_per_nm == float("inf") else min_per_nm


# ═══════════════════════════════════════════════════════════════════
#  Rota profili
# ═══════════════════════════════════════════════════════════════════

def _path_segments(G: nx.DiGraph, path: list, node_winds: dict) -> list:
    """Yol kenarlarını performans modeline uygun segment listesine çevir."""
    segments = []
    sin = math.sin
    cos = math.cos
    for i in range(len(path) - 1):
        edge = G.edges[path[i], path[i + 1]]
        bearing = edge.get("bearing", 0.0)
        u_wind = node_winds.get(path[i], (0.0, 0.0))
        v_wind = node_winds.get(path[i + 1], (0.0, 0.0))
        mu = (u_wind[0] + v_wind[0]) * 0.5
        mv = (u_wind[1] + v_wind[1]) * 0.5
        brg = math.radians(bearing)
        headwind = -(mu * sin(brg) + mv * cos(brg))
        segments.append({
            "distance_nm": edge.get("distance_nm", 0.0),
            "headwind_kts": headwind,
            "bearing": bearing,
        })
    return segments


def _profile_for_path(
    G: nx.DiGraph,
    path: list,
    perf,
    altitude_ft: float,
    cost_index: float,
    origin: dict,
    dest: dict,
    node_winds: dict,
) -> dict:
    """Yolun kütle azalmalı, tırmanma/alçalmalı toplam profilini üretir."""
    segments = _path_segments(G, path, node_winds)
    return perf.evaluate_route(
        segments,
        cruise_alt_ft=altitude_ft,
        cost_index=cost_index,
        takeoff_elev_ft=origin.get("elevation_ft") or 0.0,
        landing_elev_ft=dest.get("elevation_ft") or 0.0,
    )


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


def _waypoints(G: nx.DiGraph, path: list) -> list:
    return [
        {
            "id": node,
            "name": G.nodes[node].get("name", node),
            "latitude": G.nodes[node].get("latitude", 0),
            "longitude": G.nodes[node].get("longitude", 0),
            "type": G.nodes[node].get("type", "waypoint"),
        }
        for node in path
    ]


def _waypoint_ids(waypoints: list) -> list:
    return [w["id"] for w in waypoints]


def _route_info(
    waypoints: list, profile: dict, route_type: str,
    level_mb: int, altitude_ft: float,
) -> dict:
    """Arayüzün beklediği rota bilgisi + fizik profili."""
    return {
        "type": route_type,
        "waypoints": waypoints,
        "waypoint_count": len(waypoints),
        "level_mb": level_mb,
        "cruise_altitude_ft": round(altitude_ft, 0),
        "total_distance_nm": profile["total_distance_nm"],
        "cruise_distance_nm": profile["cruise_distance_nm"],
        "estimated_fuel_kg": profile["fuel_kg"],
        "estimated_time_min": profile["time_min"],
        "co2_emission_kg": profile["co2_kg"],
        "fuel_cost_usd": profile["fuel_cost_usd"],
        "takeoff_mass_kg": profile["takeoff_mass_kg"],
        "landing_mass_kg": profile["landing_mass_kg"],
        "tas_kts": profile["tas_kts"],
        "mach": profile["mach"],
        "avg_ground_speed_kts": profile["avg_ground_speed_kts"],
        "avg_headwind_kts": profile["avg_headwind_kts"],
        "cost_index": profile["cost_index"],
        "feasible": profile.get("feasible", True),
        "fuel_capacity_kg": profile.get("fuel_capacity_kg"),
        "fuel_margin_kg": profile.get("fuel_margin_kg"),
        "phases": profile["phases"],
        "mass_samples_kg": profile["mass_samples_kg"],
    }


def _weighted_score(profile: dict, weights: dict) -> float:
    """
    Mutlak ağırlıklı maliyet (USD).

    Üç kriter de paraya çevrildiği için katmanlar arası karşılaştırma
    tutarlıdır: yakıt × fiyat, süre × dakika maliyeti, CO₂ × karbon fiyatı.
    """
    fuel_usd = profile["fuel_kg"] * FUEL_PRICE_USD_PER_KG
    time_usd = profile["time_min"] * TIME_COST_USD_PER_MIN
    co2_usd = profile["co2_kg"] * CARBON_PRICE_USD_PER_KG
    return round(
        weights["fuel"] * fuel_usd
        + weights["time"] * time_usd
        + weights["co2"] * co2_usd,
        2,
    )


def _level_metric(std: dict, opt: dict, weights: dict) -> dict:
    """Katman bazında yakıt/süre farkı (arayüz tablosu için)."""
    fuel_delta = std["fuel_kg"] - opt["fuel_kg"]
    time_delta = std["time_min"] - opt["time_min"]
    return {
        "fuel_saved_kg": round(fuel_delta, 1),
        "fuel_saved_percent": round(
            fuel_delta / std["fuel_kg"] * 100 if std["fuel_kg"] else 0.0, 2
        ),
        "time_saved_min": round(time_delta, 1),
        "time_saved_percent": round(
            time_delta / std["time_min"] * 100 if std["time_min"] else 0.0, 2
        ),
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
    distance_delta = optimized["total_distance_nm"] - standard["total_distance_nm"]

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
        "cost_saved_usd": round(
            fuel_saved * FUEL_PRICE_USD_PER_KG
            + time_saved * TIME_COST_USD_PER_MIN,
            2,
        ),
        "distance_delta_nm": round(distance_delta, 1),
        # Optimize rota daha uzun olabilir (rüzgârdan kaçınmak için) —
        # bunu gizlemek yerine raporla.
    }
