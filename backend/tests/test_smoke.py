"""
SkyOptimizer AI — Smoke testleri

Çalıştırma (backend/ dizininden):
    venv/Scripts/python.exe -m pytest tests/ -v

Testler ağ erişimi gerektirmez: rüzgâr verisi sabitlenir, API çağrıları
monkeypatch ile devre dışı bırakılır.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import main
from optimization.astar import find_optimal_route
from optimization.cost_model import CostModel
from optimization.graph_builder import build_waypoint_graph
from optimization.ml_predictor import get_predictor
from services.airport_service import get_all_airports_count, get_airport

EXPECTED_AIRPORTS = 5278


# ─── Altyapı ────────────────────────────────────────────────────────

def run(coro):
    """Senkron testlerden async fonksiyon çalıştır."""
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


@pytest.fixture
def fixed_winds(monkeypatch):
    """Ağa çıkmadan sabit rüzgâr verisi döndür (300 hPa, 90 kt batı rüzgârı)."""
    async def fake_batch(points, level_mb=300):
        return [
            {
                "latitude": lat,
                "longitude": lon,
                "wind_speed_kts": 90.0,
                "wind_direction": 270.0,
                "level_mb": level_mb,
                "approx_altitude_ft": 30000,
                "source": "test",
            }
            for lat, lon in points
        ]

    monkeypatch.setattr(main, "get_winds_batch", fake_batch)
    return fake_batch


# ─── Havalimanı veritabanı ──────────────────────────────────────────

def test_airport_database_loaded():
    assert get_all_airports_count() == EXPECTED_AIRPORTS


def test_known_airports_resolve():
    for icao in ("LTFM", "LTBJ", "EGLL", "KJFK"):
        airport = get_airport(icao)
        assert airport is not None, f"{icao} bulunamadı"
        assert -90 <= airport["latitude"] <= 90
        assert -180 <= airport["longitude"] <= 180


def test_airport_lookup_is_case_insensitive():
    assert get_airport("ltfm")["icao"] == "LTFM"


# ─── Graf ───────────────────────────────────────────────────────────

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


# ─── Maliyet modeli ─────────────────────────────────────────────────

def test_composite_cost_is_one_for_reference_route():
    """Referans rotanın kompozit maliyeti tam 1.0 olmalı (ağırlıklar toplamı 1)."""
    model = CostModel("B738")
    reference = {"fuel_kg": 8000.0, "time_min": 200.0, "co2_kg": 25280.0}

    cost = model.composite_cost(
        fuel_kg=reference["fuel_kg"],
        time_min=reference["time_min"],
        co2_kg=reference["co2_kg"],
        weights={"fuel": 0.4, "time": 0.35, "co2": 0.25},
        reference=reference,
    )
    assert cost == pytest.approx(1.0)


def test_composite_weights_are_normalized():
    model = CostModel("B738")
    weights = model._normalize_weights({"fuel": 4, "time": 3.5, "co2": 2.5})
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["fuel"] == pytest.approx(0.4)


def test_headwind_increases_fuel_and_time():
    model = CostModel("B738")
    still = model.calculate_segment_cost(distance_nm=500)
    headwind = model.calculate_segment_cost(
        distance_nm=500, wind_speed_kts=100, wind_direction=90, aircraft_heading=90
    )

    assert headwind["headwind_kts"] > 0
    assert headwind["fuel_kg"] > still["fuel_kg"]
    assert headwind["time_min"] > still["time_min"]


def test_tailwind_reduces_time():
    model = CostModel("B738")
    still = model.calculate_segment_cost(distance_nm=500)
    tailwind = model.calculate_segment_cost(
        distance_nm=500, wind_speed_kts=100, wind_direction=270, aircraft_heading=90
    )

    assert tailwind["headwind_kts"] < 0
    assert tailwind["time_min"] < still["time_min"]


# ─── A* rota optimizasyonu ──────────────────────────────────────────

def test_identical_routes_without_wind():
    """
    Rüzgâr yoksa optimize rota standart rotadan farklılaşamaz.
    Bu, "yapay tasarruf" üretilmediğinin kanıtıdır.
    """
    result = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))

    assert "error" not in result
    assert abs(result["savings"]["fuel_saved_kg"]) < 1.0
    assert abs(result["savings"]["fuel_saved_percent"]) < 0.1
    assert result["has_measurable_savings"] is False


def test_optimized_route_never_worse_than_standard():
    """
    Ağırlık tamamen yakıta verildiğinde optimize rota yakıtı asla
    standart rotadan fazla olamaz. Heuristic'in admissible olduğunu doğrular.
    """
    winds = {
        (41.0, 29.0): {"speed": 90.0, "dir": 270.0},
        (41.0, 28.0): {"speed": 80.0, "dir": 265.0},
        (40.0, 28.0): {"speed": 70.0, "dir": 260.0},
        (39.0, 28.0): {"speed": 60.0, "dir": 255.0},
    }
    result = run(
        find_optimal_route(
            "LTFM", "LTBJ",
            weights={"fuel": 1.0, "time": 0.0, "co2": 0.0},
            wind_data_map=winds,
        )
    )

    assert "error" not in result
    assert result["savings"]["fuel_saved_kg"] >= -0.05
    assert result["optimized_route"]["estimated_fuel_kg"] <= (
        result["standard_route"]["estimated_fuel_kg"] + 0.05
    )


def test_comparison_uses_same_wind_for_both_routes():
    """İki rota da rüzgârlı hesaplanmalı — standart rota rüzgârsız olamaz."""
    winds = {(41.0, 29.0): {"speed": 120.0, "dir": 270.0}}
    result = run(find_optimal_route("LTFM", "LTBJ", wind_data_map=winds))

    still_air = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))

    # Rüzgâr verildiğinde standart rotanın yakıtı rüzgârsız hâlden farklı olmalı
    assert (
        result["standard_route"]["estimated_fuel_kg"]
        != still_air["standard_route"]["estimated_fuel_kg"]
    )


def test_result_shape_is_stable():
    result = run(find_optimal_route("LTFM", "LTBJ", wind_data_map={}))

    for key in (
        "optimized_route", "standard_route", "savings", "routes_identical",
        "has_measurable_savings", "comparison_basis", "graph_stats",
    ):
        assert key in result

    for route in ("optimized_route", "standard_route"):
        assert len(result[route]["waypoints"]) >= 2
        assert result[route]["total_distance_nm"] > 0
        assert result[route]["waypoint_count"] == len(result[route]["waypoints"])


# ─── ML tahmini ─────────────────────────────────────────────────────

def test_ai_prediction_is_deterministic():
    """
    Aynı girdi aynı çıktıyı vermeli.
    (Regresyon testi: eskiden random çarpanla "kalibre" ediliyordu.)
    """
    predictor = get_predictor()
    kwargs = dict(
        distance_nm=500,
        wind_speed_kts=60,
        wind_direction_deg=270,
        aircraft_heading_deg=90,
        altitude_ft=35000,
        headwind_kts=-60,
        crosswind_kts=0,
    )
    first = predictor.predict(**kwargs)
    second = predictor.predict(**kwargs)

    assert first == second


def test_error_vs_physics_is_a_percentage():
    predictor = get_predictor()
    ai = {"fuel_kg": 1000.0, "time_min": 100.0, "co2_kg": 3160.0}
    physics = {"fuel_kg": 1100.0, "time_min": 100.0, "co2_kg": 3476.0}

    error = predictor.error_vs_physics(ai, physics)

    assert error["fuel_kg"] == pytest.approx(-9.09, abs=0.01)
    assert error["time_min"] == pytest.approx(0.0)
    assert error["co2_kg"] == pytest.approx(-9.09, abs=0.01)


# ─── API ────────────────────────────────────────────────────────────

def test_health_endpoint(client):
    response = client.get("/health")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["airports_loaded"] == EXPECTED_AIRPORTS


def test_weather_point_route_is_not_shadowed(client):
    """
    /api/weather/point, /api/weather/{icao} tarafından yakalanmamalı.
    (Regresyon testi: rota sırası hatalıyken ICAO="POINT" olarak işleniyordu.)
    """
    body = client.get("/api/weather/point", params={"lat": 40.0, "lon": 29.0}).json()

    assert "icao" not in body
    assert body["latitude"] == 40.0
    assert body["longitude"] == 29.0


def test_airport_search_endpoint(client):
    body = client.get("/api/airports/search", params={"q": "LTFM"}).json()

    assert body["count"] >= 1
    assert body["results"][0]["icao"] == "LTFM"


def test_optimize_endpoint(client, fixed_winds):
    body = client.post(
        "/api/optimize",
        json={"origin": "LTFM", "destination": "LTBJ", "aircraft_type": "B738"},
    ).json()

    assert "error" not in body
    assert body["wind_info"]["sample_points"] == 21
    assert body["wind_info"]["avg_direction_deg"] == pytest.approx(270.0)
    assert body["comparison_basis"]["wind_samples"] == 21
    assert body["standard_route"]["total_distance_nm"] > 0
    assert body["optimized_route"]["total_distance_nm"] > 0


def test_optimize_rejects_unknown_airport(client, fixed_winds):
    body = client.post(
        "/api/optimize",
        json={"origin": "XXXX", "destination": "LTBJ"},
    ).json()

    assert "error" in body


def test_predict_endpoint_returns_both_models(client):
    body = client.post(
        "/api/predict",
        json={
            "distance_nm": 500,
            "wind_speed_kts": 60,
            "wind_direction": 270,
            "heading": 90,
        },
    ).json()

    assert body["physics_prediction"]["fuel_kg"] > 0
    assert "ai_vs_physics_error_percent" in body
    if body["model_available"]:
        assert body["ai_prediction"] is not None
