"""API uç noktaları — ağ erişimi olmadan, monkeypatch ile."""

import pytest
from fastapi.testclient import TestClient

import main
import services.route_planner as planner
import services.validation_service as validation

EXPECTED_AIRPORTS = 5278


@pytest.fixture(scope="module")
def client():
    return TestClient(main.app)


@pytest.fixture
def fixed_winds(monkeypatch):
    """3B sabit rüzgâr: her seviyede 90 kt batı rüzgârı."""
    async def fake_multi(points, levels=(300, 250, 200), valid_time=None):
        return {
            int(level): [
                {
                    "latitude": lat,
                    "longitude": lon,
                    "wind_speed_kts": 90.0,
                    "wind_direction": 270.0,
                    "level_mb": int(level),
                    "approx_altitude_ft": 30000,
                    "valid_time": valid_time,
                    "source": "test",
                }
                for lat, lon in points
            ]
            for level in levels
        }

    monkeypatch.setattr(planner, "get_winds_multi_level", fake_multi)
    return fake_multi


@pytest.fixture
def fixed_weather(monkeypatch):
    """METAR/TAF ağ çağrılarını sabitle."""
    async def fake_metar(icao):
        return {
            "icao": icao.upper(),
            "raw": f"{icao.upper()} 232050Z 27010KT 9999 SCT040 12/06 Q1015",
            "wind_speed_kts": 10, "wind_direction": 270,
            "flight_category": "VFR", "temperature_c": 12,
        }

    async def fake_taf(icao):
        return {"icao": icao.upper(), "raw": f"TAF {icao.upper()} ...", "forecasts": []}

    monkeypatch.setattr(planner, "get_metar", fake_metar)
    monkeypatch.setattr(planner, "get_taf", fake_taf)


# ─── Sistem ────────────────────────────────────────────────────────

def test_health_endpoint(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["airports_loaded"] == EXPECTED_AIRPORTS
    assert body["airspaces_loaded"] >= 1


def test_config_endpoint_exposes_model_constants(client):
    body = client.get("/api/config").json()
    assert body["cost_index"]["min"] == 0
    assert body["cost_index"]["max"] == 200
    assert "speed_fuel_coupling" in body["method_notes"]
    assert any(t["code"] == "B738" for t in body["aircraft_types"])
    assert 300 in body["cruise_levels_hpa"]


def test_status_endpoint(client):
    body = client.get("/api/status").json()
    assert "opensky_limits" in body
    assert "cache_stats" in body


# ─── Havalimanı ────────────────────────────────────────────────────

def test_airport_search_endpoint(client):
    body = client.get("/api/airports/search", params={"q": "LTFM"}).json()
    assert body["count"] >= 1
    assert body["results"][0]["icao"] == "LTFM"


def test_airport_lookup(client):
    body = client.get("/api/airports/ltfm").json()
    assert body["icao"] == "LTFM"
    assert body["country"] == "TR"


# ─── Hava sahası ───────────────────────────────────────────────────

def test_airspace_endpoint(client):
    body = client.get("/api/airspaces").json()
    assert body["meta"]["count"] >= 1
    assert body["geojson"]["type"] == "FeatureCollection"
    ids = {f["properties"]["id"] for f in body["geojson"]["features"]}
    assert "P-56A" in ids


# ─── Optimizasyon ──────────────────────────────────────────────────

def test_optimize_endpoint(client, fixed_winds, fixed_weather):
    body = client.post(
        "/api/optimize",
        json={
            "origin": "LTFM",
            "destination": "LTBJ",
            "aircraft_type": "B738",
            "cost_index": 40,
            "record": False,
        },
    ).json()

    assert "error" not in body
    assert body["origin"]["icao"] == "LTFM"
    assert body["destination"]["icao"] == "LTBJ"

    # 3B rüzgâr: iki aday seviye (180/240) × noktalar
    assert len(body["wind_info"]["levels"]) == 2
    assert body["wind_info"]["sample_points"] > 0
    assert body["departure_time"]["resolved_utc"].endswith("Z")

    # Hava durumu kartları
    assert body["weather"]["origin"]["metar"]["flight_category"] == "VFR"
    assert body["weather"]["destination"]["taf"]["raw"].startswith("TAF")

    # Fizik profili
    opt = body["optimized_route"]
    assert opt["estimated_fuel_kg"] > 0
    assert opt["phases"]["climb"]["fuel_kg"] > 0
    assert opt["phases"]["descent"]["fuel_kg"] > 0
    assert opt["takeoff_mass_kg"] > opt["landing_mass_kg"]
    assert opt["mach"] == pytest.approx(0.765, abs=0.06)
    assert "score_saved_usd" in body["savings"]
    assert body["feasibility"]["feasible"] is True

    # İrtifa tablosu + yöntem notları
    assert len(body["levels"]) == 2
    assert body["method_notes"]["base_fuel_model"].startswith("OpenAP")
    assert body["graph_stats"]["airspace_avoidance"] in ("active", "off", "disabled")


def test_optimize_rejects_unknown_airport(client, fixed_winds, fixed_weather):
    body = client.post(
        "/api/optimize", json={"origin": "XXXX", "destination": "LTBJ"}
    ).json()
    assert "error" in body


def test_optimize_requires_icao(client):
    body = client.post("/api/optimize", json={"origin": "", "destination": ""}).json()
    assert "error" in body


def test_optimize_cost_index_direction(client, fixed_winds, fixed_weather):
    """Yüksek CI daha hızlı ve daha çok yakıt yakmalı."""
    low = client.post("/api/optimize", json={
        "origin": "LTFM", "destination": "LTBJ", "cost_index": 0, "record": False,
    }).json()["optimized_route"]
    high = client.post("/api/optimize", json={
        "origin": "LTFM", "destination": "LTBJ", "cost_index": 200, "record": False,
    }).json()["optimized_route"]

    assert high["estimated_time_min"] < low["estimated_time_min"]
    assert high["estimated_fuel_kg"] > low["estimated_fuel_kg"]
    assert high["mach"] > low["mach"]


def test_optimize_infeasible_route_is_flagged(client, fixed_winds, fixed_weather):
    body = client.post("/api/optimize", json={
        "origin": "KJFK", "destination": "VHHH",
        "aircraft_type": "B738", "record": False,
    }).json()
    assert body["feasibility"]["feasible"] is False
    assert body["feasibility"]["note"]


def test_optimize_records_savings(client, fixed_winds, fixed_weather):
    before = client.get("/api/stats/savings").json()["totals"]["total_optimizations"]
    client.post("/api/optimize", json={
        "origin": "LTFM", "destination": "LTBJ", "record": True,
    })
    after = client.get("/api/stats/savings").json()
    assert after["totals"]["total_optimizations"] == before + 1
    assert after["recent"]


def test_predict_endpoint_returns_both_models(client):
    body = client.post("/api/predict", json={
        "distance_nm": 500, "wind_speed_kts": 60,
        "wind_direction": 270, "heading": 90, "cost_index": 60,
    }).json()
    assert body["physics_prediction"]["fuel_kg"] > 0
    assert "ai_vs_physics_error_percent" in body
    if body["model_available"]:
        assert body["ai_prediction"] is not None


# ─── Uçak kimliği / trafik ─────────────────────────────────────────

def test_aircraft_endpoint_uses_hexdb(client, monkeypatch):
    async def fake_json(url):
        if "/aircraft/" in url:
            return {
                "ModeS": "4BC8C6", "Registration": "TC-RFF",
                "Manufacturer": "Airbus", "ICAOTypeCode": "A21N",
                "Type": "A321 251NX", "RegisteredOwners": "Pegasus Airlines",
            }
        if "/route/" in url:
            return {"flight": "PGT38UL", "route": "LTAI-LTFM"}
        return None

    import services.aircraft_service as ac
    monkeypatch.setattr(ac, "_get_json", fake_json)

    body = client.get("/api/aircraft/4bc8c6", params={"callsign": "PGT38UL"}).json()
    assert body["available"] is True
    assert body["type_code"] == "A21N"
    assert body["category"] == "narrow"
    assert body["operator"] == "Pegasus Airlines"
    assert body["route"]["origin"] == "LTAI"


def test_live_flights_include_aircraft_class(client, monkeypatch):
    async def fake_live(*args, **kwargs):
        return {
            "flights": [{
                "icao24": "abc123", "callsign": "THY1",
                "origin_country": "Turkey", "latitude": 41.0, "longitude": 29.0,
                "altitude_m": 10000, "velocity_ms": 230, "true_track": 90,
                "vertical_rate": 0, "aircraft_class": "narrow",
            }],
            "count": 1, "from_cache": False, "remaining": 100,
        }

    async def fake_enrich(flights, limit=40):
        return {}

    monkeypatch.setattr(main, "get_live_flights", fake_live)
    monkeypatch.setattr(main, "enrich_flights", fake_enrich)

    body = client.get(
        "/api/flights/live",
        params={"lamin": 40, "lamax": 42, "lomin": 28, "lomax": 30},
    ).json()
    assert body["count"] == 1
    assert body["flights"][0]["aircraft_class"] == "narrow"


# ─── Gerçek uçuş doğrulama ─────────────────────────────────────────

def test_validate_route_compares_actual_track(client, fixed_winds, fixed_weather, monkeypatch):
    async def fake_find(origin, destination, hours=12):
        return {
            "available": True,
            "flight": {
                "icao24": "4bb279", "callsign": "THY9ZQ",
                "departure": "LTFM", "destination": "LTBJ",
                "first_seen": 1_700_000_000, "last_seen": 1_700_003_600,
            },
        }

    async def fake_track(icao24, time_s=None):
        # 100 NM doğuya, FL320'de, 45 dakikada (irtifa metre cinsinden)
        return {"track": [
            [1_700_000_000, 38.0, 27.0, 0, 90, False],
            [1_700_000_450, 38.0, 27.5, 8000, 90, False],
            [1_700_000_900, 38.0, 28.0, 10000, 90, False],
            [1_700_001_350, 38.0, 28.5, 10000, 90, False],
            [1_700_001_800, 38.0, 29.0, 8000, 90, False],
            [1_700_002_250, 38.0, 29.5, 3000, 90, False],
            [1_700_002_700, 38.0, 30.0, 500, 90, False],
        ]}

    async def fake_meta(icao24, callsign=None, include_route=True):
        return {"available": True, "type_code": "B738", "registration": "TC-JZF",
                "operator": "Turkish Airlines", "model": "737-800", "category": "narrow"}

    monkeypatch.setattr(validation, "find_recent_flight", fake_find)
    monkeypatch.setattr(validation, "get_flight_track", fake_track)
    monkeypatch.setattr(validation, "get_aircraft", fake_meta)

    body = client.post("/api/validate", json={
        "origin": "LTFM", "destination": "LTBJ", "cost_index": 30,
    }).json()

    assert body["available"] is True
    assert body["flight"]["aircraft_type"] == "B738"
    assert body["actual"]["distance_nm"] > 100
    assert body["optimized"]["fuel_kg"] > 0
    assert "fuel_saved_vs_actual_kg" in body["comparison"]
    assert len(body["caveats"]) >= 2


def test_validate_route_handles_missing_flight(client, monkeypatch):
    async def fake_find(origin, destination, hours=12):
        return {"available": False, "reason": "Son 12 saatte uçuş yok."}

    monkeypatch.setattr(validation, "find_recent_flight", fake_find)
    body = client.post("/api/validate", json={"origin": "LTFM", "destination": "EGLL"}).json()
    assert body["available"] is False
    assert "uçuş yok" in body["reason"]
