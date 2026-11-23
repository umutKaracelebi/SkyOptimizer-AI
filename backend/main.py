"""
SkyOptimizer AI — FastAPI Ana Uygulama
Uçuş rota optimizasyonu için REST API sunucusu.
"""

import asyncio

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS, DEFAULT_AIRCRAFT
from services.cache_manager import cache, opensky_limiter
from services.airport_service import (
    search_airports,
    get_airport,
    get_turkey_airports,
    get_all_airports_count,
)
from services.adsb_service import (
    get_live_flights,
    get_flight_track,
    get_recent_arrivals,
    get_recent_departures,
    find_recent_flight,
)
from services.aircraft_service import get_aircraft, enrich_flights
from services.airspace_service import airspace_meta, feature_geojson
from services.stats_store import get_totals, record_optimization
from services.weather_service import get_metar, get_taf, get_weather_at_point
from services.wind_service import get_upper_winds, get_winds_multi_level
from services.route_planner import plan_route
from services.validation_service import validate_route
from optimization.performance import (
    CI_DEFAULT,
    CI_MAX,
    CI_MIN,
    METHOD_NOTES,
    get_performance,
)

APP_VERSION = "0.3.0"

app = FastAPI(
    title="SkyOptimizer AI",
    description=(
        "Yapay zekâ destekli uçuş rota optimizasyon sistemi. "
        "ADS-B, canlı meteoroloji ve 3B üst seviye rüzgâr verileriyle "
        "optimum uçuş rotaları hesaplar."
    ),
    version=APP_VERSION,
)

# ─── CORS Middleware ─────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health & Status Endpoints ──────────────────────────────────────
@app.get("/health", tags=["Sistem"])
async def health_check():
    """Sistem sağlık kontrolü."""
    return {
        "status": "ok",
        "service": "SkyOptimizer AI",
        "version": APP_VERSION,
        "airports_loaded": get_all_airports_count(),
        "airspaces_loaded": airspace_meta().get("count", 0),
    }


@app.get("/api/status", tags=["Sistem"])
async def api_status():
    """API limit durumu ve cache istatistikleri."""
    return {
        "opensky_limits": opensky_limiter.status,
        "cache_stats": cache.stats,
    }


@app.get("/api/config", tags=["Sistem"])
async def api_config():
    """
    Arayüz için model sabitleri ve yöntem notları.

    Cost index aralığı, yakıt fiyatı, zaman maliyeti gibi değerlerin tek
    kaynağı backend'dir; arayüzde kopyalanmaz.
    """
    perf = get_performance(DEFAULT_AIRCRAFT)
    return {
        "version": APP_VERSION,
        "cost_index": {
            "min": CI_MIN,
            "max": CI_MAX,
            "default": CI_DEFAULT,
            "description": (
                "0 = uzun menzil cruise (en ekonomik), "
                "200 = yüksek hızlı cruise (en hızlı)."
            ),
        },
        "aircraft_types": [
            {"code": "B738", "name": "Boeing 737-800"},
            {"code": "A320", "name": "Airbus A320"},
            {"code": "A321", "name": "Airbus A321"},
            {"code": "A20N", "name": "Airbus A320neo"},
            {"code": "A21N", "name": "Airbus A321neo"},
            {"code": "B77W", "name": "Boeing 777-300ER"},
            {"code": "B789", "name": "Boeing 787-9"},
            {"code": "A359", "name": "Airbus A350-900"},
            {"code": "A388", "name": "Airbus A380-800"},
            {"code": "E190", "name": "Embraer E190"},
            {"code": "AT76", "name": "ATR 72-600"},
        ],
        "default_aircraft": DEFAULT_AIRCRAFT,
        "cruise_levels_hpa": [500, 400, 300, 250, 200],
        "weather_levels": perf.candidate_levels(2000),
        "method_notes": METHOD_NOTES,
    }


# ─── Airport Endpoints ──────────────────────────────────────────────
@app.get("/api/airports/search", tags=["Havalimanları"])
async def api_search_airports(
    q: str = Query("", description="Arama sorgusu (ICAO, IATA veya isim)"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Havalimanı arama. ICAO kodu, IATA kodu veya isim ile aranabilir.
    """
    results = search_airports(q, limit)
    return {"query": q, "count": len(results), "results": results}


@app.get("/api/airports/turkey/all", tags=["Havalimanları"])
async def api_turkey_airports():
    """Tüm Türkiye havalimanlarını listele."""
    airports = get_turkey_airports()
    return {"count": len(airports), "airports": airports}


@app.get("/api/airports/{icao}", tags=["Havalimanları"])
async def api_get_airport(icao: str):
    """ICAO koduna göre havalimanı detay bilgisi."""
    airport = get_airport(icao)
    if airport:
        return airport
    return {"error": f"Havalimanı bulunamadı: {icao.upper()}"}


# ─── Weather Endpoints ──────────────────────────────────────────────
# NOT: Sabit yollar ({parametre} içermeyen) ÖNCE tanımlanmalı.
@app.get("/api/weather/point", tags=["Meteoroloji"])
async def api_get_point_weather(
    lat: float = Query(..., description="Enlem"),
    lon: float = Query(..., description="Boylam"),
):
    """Belirtilen koordinattaki hava durumu."""
    return await get_weather_at_point(lat, lon)


@app.get("/api/weather/{icao}", tags=["Meteoroloji"])
async def api_get_weather(icao: str):
    """Belirtilen havalimanı için METAR ve TAF verisi."""
    metar, taf = await asyncio.gather(get_metar(icao), get_taf(icao))
    return {"icao": icao.upper(), "metar": metar, "taf": taf}


@app.get("/api/winds", tags=["Meteoroloji"])
async def api_get_winds(
    lat: float = Query(39.0, description="Enlem"),
    lon: float = Query(35.0, description="Boylam"),
    level_mb: int = Query(300, description="Basınç seviyesi (mb)"),
    valid_time: str | None = Query(
        None, description="ISO-8601 zaman (ör. 2026-11-23T14:00:00Z)"
    ),
):
    """Belirtilen koordinat, irtifa ve zamanda üst seviye rüzgâr."""
    return await get_upper_winds(lat, lon, level_mb, valid_time)


# ─── Airspace Endpoints ─────────────────────────────────────────────
@app.get("/api/airspaces", tags=["Hava Sahası"])
async def api_airspaces():
    """
    Kısıtlı/yasak hava sahaları.

    Paket içindeki veri seti küçük bir gösterim setidir; gerçek kapsam
    için ulusal AIP / OpenAIP verisi `RESTRICTED_AIRSPACE_FILE` ile
    yüklenir.
    """
    return {"meta": airspace_meta(), "geojson": feature_geojson()}


# ─── Traffic & Flights Endpoints ────────────────────────────────────
@app.get("/api/traffic", tags=["Trafik"])
async def api_get_traffic():
    """Türkiye hava sahası canlı trafik (15dk cache)."""
    data = await get_live_flights()
    return {
        "region": "Türkiye",
        "aircraft_count": data.get("count", 0),
        "from_cache": data.get("from_cache", False),
        "opensky_remaining": opensky_limiter.remaining_requests,
    }


@app.get("/api/flights/live", tags=["Trafik"])
async def api_get_live_flights(
    lamin: float = Query(None),
    lamax: float = Query(None),
    lomin: float = Query(None),
    lomax: float = Query(None),
    enrich: bool = Query(
        True, description="Gerçek uçak tipini hexdb'den tamamla (ilk 40 uçak)"
    ),
):
    """
    Canlı uçuş verileri — OpenSky ADS-B (15 dk cache).

    Her uçuşta `aircraft_class` bulunur (heavy/narrow/regional/turboprop/
    light/rotor/fighter). `enrich=true` ise ilk 40 uçak için gerçek ICAO
    tip kodu eklenir; arayüz ikonları bu tipe göre çizilir.
    """
    data = await get_live_flights(lamin, lamax, lomin, lomax)
    # Dünya modunda 10.000+ uçak olabildiği için yalnızca rota/yerel
    # görünümlerde zenginleştirme yapılır.
    if enrich and data.get("flights") and data["count"] <= 1500:
        try:
            enriched = await enrich_flights(data["flights"], limit=120)
            for flight in data["flights"]:
                meta = enriched.get(flight["icao24"])
                if meta:
                    flight["type_code"] = meta.get("type_code")
                    flight["operator"] = meta.get("operator")
                    if meta.get("category"):
                        flight["aircraft_class"] = meta["category"]
        except Exception as exc:  # pragma: no cover - zenginleştirme opsiyonel
            data["enrich_error"] = str(exc)
    return data


@app.get("/api/flights/track/{icao24}", tags=["Trafik"])
async def api_get_flight_track(icao24: str, time_s: int = Query(0)):
    """Belirli uçağın iz takibi (geçmiş için `time_s` = lastSeen)."""
    return await get_flight_track(icao24, time_s)


@app.get("/api/flights/recent", tags=["Trafik"])
async def api_recent_flights(
    airport: str = Query(..., description="ICAO kod"),
    direction: str = Query("arrival", pattern="^(arrival|departure)$"),
    hours: int = Query(12, ge=1, le=48, description="Anonim erişimde en fazla 12"),
):
    """Son N saatte bir havalimanına inen/kalkan gerçek uçuşlar."""
    if direction == "departure":
        return await get_recent_departures(airport, hours)
    return await get_recent_arrivals(airport, hours)


@app.get("/api/flights/find", tags=["Trafik"])
async def api_find_flight(
    origin: str = Query(...),
    destination: str = Query(...),
    hours: int = Query(12, ge=1, le=48),
):
    """Son N saatte origin → destination uçmuş gerçek uçuşu bul."""
    return await find_recent_flight(origin, destination, hours)


# ─── Aircraft Identity ──────────────────────────────────────────────
@app.get("/api/aircraft/{icao24}", tags=["Uçak"])
async def api_aircraft(icao24: str, callsign: str = Query("")):
    """Uçak kimliği (tip, kayıt, operatör) ve varsa rota bilgisi."""
    return await get_aircraft(icao24, callsign=callsign, include_route=bool(callsign))


# ─── Optimization Endpoints ─────────────────────────────────────────
@app.post("/api/optimize", tags=["Optimizasyon"])
async def api_optimize_route(payload: dict):
    """
    İki havalimanı arası optimum rota hesaplama.

    Body:
        origin, destination, aircraft_type,
        optimization_weights {fuel,time,co2},
        cost_index (0-200), departure_time (ISO-8601),
        avoid_airspace (bool), record (bool)

    A* + OpenAP yakıt modeli + cost index + irtifa katmanı taraması.
    """
    origin_icao = str(payload.get("origin", "")).strip().upper()
    dest_icao = str(payload.get("destination", "")).strip().upper()
    if not origin_icao or not dest_icao:
        return {"error": "Kalkış ve varış ICAO kodları gerekli"}

    weights = payload.get("optimization_weights") or {
        "fuel": 0.4, "time": 0.35, "co2": 0.25
    }
    try:
        cost_index = float(payload.get("cost_index", CI_DEFAULT))
    except (TypeError, ValueError):
        cost_index = CI_DEFAULT

    result = await plan_route(
        origin_icao=origin_icao,
        destination_icao=dest_icao,
        aircraft_type=str(payload.get("aircraft_type") or DEFAULT_AIRCRAFT),
        weights=weights,
        cost_index=cost_index,
        departure_time=payload.get("departure_time"),
        avoid_airspace=bool(payload.get("avoid_airspace", True)),
        record=bool(payload.get("record", True)),
    )
    return result


@app.post("/api/compare", tags=["Optimizasyon"])
async def api_compare_routes(payload: dict):
    """Standart vs optimize edilmiş rota karşılaştırma."""
    return await api_optimize_route(payload)


@app.post("/api/validate", tags=["Doğrulama"])
async def api_validate_route(payload: dict):
    """
    Modeli son 24 saatteki gerçek bir ADS-B uçuşuyla karşılaştır.

    Body: origin, destination, aircraft_type (opsiyonel), cost_index,
    optimization_weights, hours (1-48)
    """
    origin = str(payload.get("origin", "")).strip().upper()
    dest = str(payload.get("destination", "")).strip().upper()
    if not origin or not dest:
        return {"error": "Kalkış ve varış ICAO kodları gerekli"}

    try:
        cost_index = float(payload.get("cost_index", CI_DEFAULT))
    except (TypeError, ValueError):
        cost_index = CI_DEFAULT

    return await validate_route(
        origin=origin,
        destination=dest,
        aircraft_type=payload.get("aircraft_type"),
        cost_index=cost_index,
        weights=payload.get("optimization_weights"),
        hours=int(payload.get("hours", 12)),
    )


@app.post("/api/predict", tags=["Yapay Zekâ"])
async def api_ml_predict(payload: dict):
    """
    Eğitilmiş AI modeli ile hızlı yakıt/süre/CO₂ tahmini.
    Model yoksa fallback olarak CostModel kullanır.
    """
    from optimization.ml_predictor import get_predictor
    from optimization.cost_model import CostModel
    from utils.geo import wind_components

    distance = payload.get("distance_nm", 0)
    wind_spd = payload.get("wind_speed_kts", 0)
    wind_dir = payload.get("wind_direction", 0)
    heading = payload.get("heading", 0)
    altitude = payload.get("altitude_ft", 35000)
    cost_index = payload.get("cost_index", CI_DEFAULT)

    hw, cw = wind_components(wind_spd, wind_dir, heading)

    predictor = get_predictor()
    ai_result = predictor.predict(
        distance_nm=distance,
        wind_speed_kts=wind_spd,
        wind_direction_deg=wind_dir,
        aircraft_heading_deg=heading,
        altitude_ft=altitude,
        headwind_kts=hw,
        crosswind_kts=cw,
    )

    # Fizik modeli (her zaman hesapla — karşılaştırma için)
    cost_model = CostModel("B738", cost_index=cost_index)
    physics = cost_model.calculate_segment_cost(
        distance_nm=distance,
        wind_speed_kts=wind_spd,
        wind_direction=wind_dir,
        aircraft_heading=heading,
        altitude_ft=altitude,
    )

    physics_result = {
        "fuel_kg": round(physics["fuel_kg"], 1),
        "time_min": round(physics["time_min"], 1),
        "co2_kg": round(physics["co2_kg"], 1),
        "source": "cost_model",
    }

    return {
        "ai_prediction": ai_result,
        "physics_prediction": physics_result,
        "model_available": ai_result is not None,
        "ai_vs_physics_error_percent": predictor.error_vs_physics(
            ai_result, physics_result
        ),
    }


# ─── Cumulative Savings (SQLite) ────────────────────────────────────
@app.get("/api/stats/savings", tags=["İstatistik"])
async def api_stats_savings(limit: int = Query(12, ge=1, le=100)):
    """Sunucuda birikmiş toplam tasarruf (ekip ortak istatistiği)."""
    return get_totals(limit_recent=limit)


@app.post("/api/stats/savings", tags=["İstatistik"])
async def api_record_savings(payload: dict):
    """
    Bir optimizasyon sonucunu birikime ekle (elle/istemci taraflı).

    `/api/optimize` varsayılan olarak kendisi kaydeder; bu uç nokta
    yalnızca istemci tarafında hesaplanmış sonuçları aktarmak içindir.
    """
    ok = record_optimization(payload, departure_time=payload.get("departure_time"))
    return {"recorded": ok, **get_totals()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
