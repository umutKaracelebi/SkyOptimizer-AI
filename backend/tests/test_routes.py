"""Graf, tarih çizgisi, kısıtlı hava sahası ve A* davranışı."""

import asyncio

import networkx as nx
import pytest

from optimization.astar import find_optimal_route
from optimization.graph_builder import build_waypoint_graph, graph_stats
from optimization.performance import get_performance
from services.airport_service import get_all_airports_count, get_airport
from services.airport_service import search_airports
from services.airspace_service import (
    airspace_meta,
    load_airspaces,
    point_blocked,
    segment_blocked,
)
from services.wind_service import build_sample_points, sampling_plan
from utils.geo import haversine_nm, initial_bearing

EXPECTED_AIRPORTS = 5278


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


# ─── Havalimanı veritabanı ─────────────────────────────────────────

def test_airport_database_loaded():
    assert get_all_airports_count() == EXPECTED_AIRPORTS


def test_known_airports_resolve():
    for icao in ("LTFM", "LTBJ", "EGLL", "KJFK", "VHHH"):
        airport = get_airport(icao)
        assert airport is not None, f"{icao} bulunamadı"
        assert -90 <= airport["latitude"] <= 90
        assert -180 <= airport["longitude"] <= 180


def test_airport_lookup_is_case_insensitive():
    assert get_airport("ltfm")["icao"] == "LTFM"


def test_search_prefers_exact_icao():
    assert search_airports("LTFM", 5)[0]["icao"] == "LTFM"


# ─── Coğrafya ──────────────────────────────────────────────────────

def test_initial_bearing_handles_antimeridian():
    """179°E → 179°W gerçekten doğuya gitmek olmalı (2°), 358° değil."""
    bearing = initial_bearing(0.0, 179.0, 0.0, -179.0)
    assert bearing == pytest.approx(90.0, abs=1.0)

    reverse = initial_bearing(0.0, -179.0, 0.0, 179.0)
    assert reverse == pytest.approx(270.0, abs=1.0)


# ─── Örnekleme ─────────────────────────────────────────────────────

def test_dynamic_sampling_scales_with_distance():
    short = sampling_plan(100)
    medium = sampling_plan(1000)
    long = sampling_plan(7000)

    assert short["base_points"] == 6
    assert medium["base_points"] == 7
    assert 40 <= long["base_points"] <= 48
    # ~150 NM hedef aralık (48 nokta üst sınırında 146 NM)
    assert 140 <= long["spacing_nm"] <= 155
    assert len(short["offsets_nm"]) == 3


def test_sample_points_cover_corridor():
    points = build_sample_points(41.0, 29.0, 51.47, -0.45, 1500)
    # base_points + 1 great-circle noktası × 3 koridor ofseti
    assert len(points) == (sampling_plan(1500)["base_points"] + 1) * 3
    assert all(-90 <= lat <= 90 for lat, _ in points)


# ─── Graf ──────────────────────────────────────────────────────────

def test_graph_builds_with_waypoints_and_corridor():
    G = build_waypoint_graph("LTFM", "LTBJ")
    assert G.number_of_nodes() > 10
    assert G.has_node("LTFM") and G.has_node("LTBJ")
    types = {d.get("type") for _, d in G.nodes(data=True)}
    assert {"airport", "waypoint", "corridor"} <= types
    # Doğrudan kalkış→varış kenarı olmamalı (ara düğüm zorunlu)
    assert not G.has_edge("LTFM", "LTBJ")


def test_graph_edges_carry_distance_and_bearing():
    G = build_waypoint_graph("LTFM", "LTBJ")
    for _, _, data in G.edges(data=True):
        assert data["distance_nm"] > 0
        assert 0 <= data["bearing"] < 360


def test_graph_antimeridian_route_is_connected():
    """KJFK→VHHH tarih çizgisini geçer; tüm boylamlar normalize olmalı."""
    G = build_waypoint_graph("KJFK", "VHHH")
    assert nx.has_path(G, "KJFK", "VHHH")
    for _, data in G.nodes(data=True):
        assert -180 <= data["longitude"] <= 180
    stats = graph_stats(G)
    assert stats["nodes"] > 300
    # Mekânsal indeks sayesinde kenar sayısı düğüm sayısının karesinden çok küçük
    assert stats["edges"] < stats["nodes"] ** 2 / 4


def test_graph_topology_is_cached_but_mutable_edges():
    """Cache'lenen topoloji kopya olarak dönmeli; kenar maliyeti sızmamalı."""
    G1 = build_waypoint_graph("LTFM", "LTBJ")
    edge = next(iter(G1.edges))
    G1.edges[edge]["weight"] = 123.0

    G2 = build_waypoint_graph("LTFM", "LTBJ")
    assert "weight" not in G2.edges[edge]


# ─── Kısıtlı hava sahası ───────────────────────────────────────────

def test_airspace_dataset_loads():
    features, meta = load_airspaces()
    assert len(features) >= 4
    assert meta["available"] is True
    assert "AIP" in airspace_meta()["note"]


def test_point_in_prohibited_area():
    hit = point_blocked(38.89, -77.04)  # Washington DC P-56A
    assert hit is not None
    assert hit["id"] == "P-56A"
    assert point_blocked(41.0, 29.0) is None  # İstanbul


def test_segment_crossing_restricted_area_is_blocked():
    hit = segment_blocked(34.5, -118.4, 36.0, -117.0)  # R-2508
    assert hit is not None
    assert hit["id"] == "R-2508"


def test_route_through_restricted_area_is_avoided():
    """KLAX→KLAS hattı R-2508'in güneyinden geçmeli."""
    G = build_waypoint_graph("KLAX", "KLAS", avoid_airspace=True)
    for u, v in G.edges:
        d1, d2 = G.nodes[u], G.nodes[v]
        assert segment_blocked(
            d1["latitude"], d1["longitude"], d2["latitude"], d2["longitude"]
        ) is None


# ─── A* rota optimizasyonu ─────────────────────────────────────────

def test_windless_route_has_no_measurable_savings():
    """
    Rüzgâr yoksa optimize rota standart rotadan anlamlı biçimde farklılaşamaz.
    Bu, "yapay tasarruf" üretilmediğinin kanıtıdır. (Kütle azalması
    segment sırasına bağlı olduğu için ~1 kg mertebesinde fark oluşabilir.)
    """
    result = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))
    assert "error" not in result
    assert abs(result["savings"]["fuel_saved_kg"]) < 3.0
    assert abs(result["savings"]["fuel_saved_percent"]) < 0.1
    assert result["has_measurable_savings"] is False


def test_optimized_route_never_worse_than_standard():
    winds = {
        (41.0, 29.0): {"speed": 90.0, "dir": 270.0},
        (41.0, 28.0): {"speed": 80.0, "dir": 265.0},
        (40.0, 28.0): {"speed": 70.0, "dir": 260.0},
        (39.0, 28.0): {"speed": 60.0, "dir": 255.0},
    }
    result = run(find_optimal_route(
        "LTFM", "LTBJ",
        weights={"fuel": 1.0, "time": 0.0, "co2": 0.0},
        wind_data_map=winds,
    ))
    assert "error" not in result
    assert result["optimized_route"]["estimated_fuel_kg"] <= (
        result["standard_route"]["estimated_fuel_kg"] + 3.0
    )


def test_both_routes_use_the_same_wind():
    winds = {(41.0, 29.0): {"speed": 120.0, "dir": 270.0}}
    windy = run(find_optimal_route("LTFM", "LTBJ", wind_data_map=winds))
    still = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))
    assert (
        windy["standard_route"]["estimated_fuel_kg"]
        != still["standard_route"]["estimated_fuel_kg"]
    )


def test_result_shape_and_level_table():
    result = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))
    for key in (
        "optimized_route", "standard_route", "savings", "routes_identical",
        "has_measurable_savings", "comparison_basis", "graph_stats",
        "levels", "airspace", "feasibility", "aircraft_performance",
        "method_notes",
    ):
        assert key in result

    for route in ("optimized_route", "standard_route"):
        info = result[route]
        assert len(info["waypoints"]) >= 2
        assert info["total_distance_nm"] > 0
        assert info["waypoint_count"] == len(info["waypoints"])
        assert info["estimated_fuel_kg"] > 0
        assert info["cruise_altitude_ft"] > 0

    levels = result["levels"]
    assert len(levels) >= 1
    assert sum(1 for lv in levels if lv["selected_standard"]) == 1
    assert sum(1 for lv in levels if lv["selected_optimized"]) == 1
    for lv in levels:
        assert lv["standard_fuel_kg"] > 0
        assert lv["optimized_fuel_kg"] > 0


def test_altitude_layers_are_evaluated():
    result = run(find_optimal_route("LTFM", "EGLL", wind_data_map={}))
    labels = {lv["label"] for lv in result["levels"]}
    assert len(labels) >= 2
    assert any(label in labels for label in ("FL300", "FL340", "FL390"))


def test_cost_index_changes_route_profile():
    low = run(find_optimal_route("LTFM", "EGLL", cost_index=0, wind_data_map={}))
    high = run(find_optimal_route("LTFM", "EGLL", cost_index=200, wind_data_map={}))
    assert high["optimized_route"]["mach"] > low["optimized_route"]["mach"]
    assert (
        high["optimized_route"]["estimated_fuel_kg"]
        > low["optimized_route"]["estimated_fuel_kg"]
    )


def test_three_dimensional_winds_change_level_choice():
    """Batı yönlü jet stream'de doğuya uçuşta yüksek katman tercih edilmeli."""
    from utils.geo import great_circle_waypoints

    def wmap(speed, direction):
        return {
            (round(lat, 1), round(lon, 1)): {"speed": speed, "dir": direction}
            for lat, lon in great_circle_waypoints(41, 29, 51.47, -0.45, 12)
        }

    eastbound = run(find_optimal_route(
        "LTFM", "EGLL",
        wind_levels={300: wmap(60, 180), 250: wmap(90, 180), 200: wmap(140, 180)},
    ))
    # 180° = güneyden esen rüzgâr; kuzeye uçuşta kuvvetli karşı rüzgâr
    selected = next(lv for lv in eastbound["levels"] if lv["selected_optimized"])
    assert selected["level_mb"] in (200, 250, 300)


def test_infeasible_aircraft_route_reported():
    result = run(find_optimal_route("KJFK", "VHHH", aircraft_type="B738",
                                    wind_data_map={}))
    assert result["feasibility"]["feasible"] is False


def test_unknown_aircraft_type_warns_but_still_works():
    result = run(find_optimal_route("LTFM", "LTBJ", aircraft_type="ZZZZ",
                                    wind_data_map={}))
    assert "error" not in result
    assert result["aircraft_performance"]["known_type"] is False
    assert result["warnings"]


def test_route_profile_fuel_matches_segments():
    result = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))
    opt = result["optimized_route"]
    phases = opt["phases"]
    total = (
        phases["climb"]["fuel_kg"]
        + phases["cruise"]["fuel_kg"]
        + phases["descent"]["fuel_kg"]
    )
    assert total == pytest.approx(opt["estimated_fuel_kg"], abs=1.0)


def test_large_aircraft_has_more_capacity():
    small = get_performance("B738")
    large = get_performance("B77W")
    assert large.max_fuel_kg > small.max_fuel_kg
    assert large.mtow > small.mtow


def test_haversine_symmetry():
    assert haversine_nm(41, 29, 51.47, -0.45) == pytest.approx(
        haversine_nm(51.47, -0.45, 41, 29), abs=1e-6
    )
