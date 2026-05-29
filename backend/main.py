"""
SkyOptimizer AI — FastAPI Ana Uygulama
Uçuş rota optimizasyonu için REST API sunucusu.
"""

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from config import CORS_ORIGINS, TURKEY_BBOX
from services.cache_manager import cache, opensky_limiter
from services.airport_service import (
    search_airports,
    get_airport,
    get_turkey_airports,
    get_all_airports_count,
)
from services.adsb_service import get_live_flights, get_flight_track
from services.weather_service import get_metar, get_taf, get_weather_at_point
from services.wind_service import get_upper_winds, get_route_winds

app = FastAPI(
    title="SkyOptimizer AI",
    description=(
        "Yapay zekâ destekli uçuş rota optimizasyon sistemi. "
        "ADS-B, canlı meteoroloji ve trafik verileriyle "
        "optimum uçuş rotaları hesaplar."
    ),
    version="0.2.0",
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
        "version": "0.2.0",
        "airports_loaded": get_all_airports_count(),
    }


@app.get("/api/status", tags=["Sistem"])
async def api_status():
    """API limit durumu ve cache istatistikleri."""
    return {
        "opensky_limits": opensky_limiter.status,
        "cache_stats": cache.stats,
    }


# ─── Airport Endpoints ──────────────────────────────────────────────
@app.get("/api/airports/search", tags=["Havalimanları"])
async def api_search_airports(
    q: str = Query("", description="Arama sorgusu (ICAO, IATA veya isim)"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Havalimanı arama. ICAO kodu, IATA kodu veya isim ile aranabilir.
    Türkiye havalimanları öncelikli sıralanır.
    """
    results = search_airports(q, limit)
    return {"query": q, "count": len(results), "results": results}


@app.get("/api/airports/{icao}", tags=["Havalimanları"])
async def api_get_airport(icao: str):
    """ICAO koduna göre havalimanı detay bilgisi."""
    airport = get_airport(icao)
    if airport:
        return airport
    return {"error": f"Havalimanı bulunamadı: {icao.upper()}"}


@app.get("/api/airports/turkey/all", tags=["Havalimanları"])
async def api_turkey_airports():
    """Tüm Türkiye havalimanlarını listele."""
    airports = get_turkey_airports()
    return {"count": len(airports), "airports": airports}


# ─── Weather Endpoints ──────────────────────────────────────────────
@app.get("/api/weather/{icao}", tags=["Meteoroloji"])
async def api_get_weather(icao: str):
    """Belirtilen havalimanı için METAR ve TAF verisi."""
    metar = await get_metar(icao)
    taf = await get_taf(icao)
    return {"icao": icao.upper(), "metar": metar, "taf": taf}


@app.get("/api/weather/point", tags=["Meteoroloji"])
async def api_get_point_weather(
    lat: float = Query(..., description="Enlem"),
    lon: float = Query(..., description="Boylam"),
):
    """Belirtilen koordinattaki hava durumu."""
    return await get_weather_at_point(lat, lon)


@app.get("/api/winds", tags=["Meteoroloji"])
async def api_get_winds(
    lat: float = Query(39.0, description="Enlem"),
    lon: float = Query(35.0, description="Boylam"),
    level_mb: int = Query(300, description="Basınç seviyesi (mb)"),
):
    """Belirtilen koordinat ve irtifada üst seviye rüzgâr verisi."""
    return await get_upper_winds(lat, lon, level_mb)


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
):
    """Canlı uçuş verileri — OpenSky ADS-B (15 dk cache)."""
    return await get_live_flights(lamin, lamax, lomin, lomax)


@app.get("/api/flights/track/{icao24}", tags=["Trafik"])
async def api_get_flight_track(icao24: str):
    """Belirli uçağın iz takibi."""
    return await get_flight_track(icao24)


# ─── Optimization Endpoints ─────────────────────────────────────────
@app.post("/api/optimize", tags=["Optimizasyon"])
async def api_optimize_route(payload: dict):
    """
    İki havalimanı arası optimum rota hesaplama.
    A* algoritması + OpenAP yakıt modeli ile gerçek optimizasyon.
    """
    from optimization.astar import find_optimal_route

    origin_icao = payload.get("origin", "").upper()
    dest_icao = payload.get("destination", "").upper()
    aircraft_type = payload.get("aircraft_type", "B738")
    weights = payload.get("optimization_weights",
                          {"fuel": 0.4, "time": 0.35, "co2": 0.25})

    if not origin_icao or not dest_icao:
        return {"error": "Kalkış ve varış ICAO kodları gerekli"}

    origin = get_airport(origin_icao)
    dest = get_airport(dest_icao)

    if not origin:
        return {"error": f"Kalkış havalimanı bulunamadı: {origin_icao}"}
    if not dest:
        return {"error": f"Varış havalimanı bulunamadı: {dest_icao}"}

    # Rota boyunca ve koridor genişliğinde rüzgâr verisi al
    # Sadece merkez hat değil, ±sapma noktalarından da örnekle
    # Bu sayede koridor waypoint'lerindeki rüzgâr farkları A*'ya yansır
    from utils.geo import great_circle_waypoints, initial_bearing
    import math

    gc_points = great_circle_waypoints(
        origin["latitude"], origin["longitude"],
        dest["latitude"], dest["longitude"],
        num_points=7,
    )

    # Rota yönüne dik sapma hesapla
    route_bearing = initial_bearing(
        origin["latitude"], origin["longitude"],
        dest["latitude"], dest["longitude"],
    )
    perp_bearing_rad = math.radians((route_bearing + 90) % 360)

    wind_data_map = {}
    # Koridor offset'leri (derece cinsinden): merkez + sağ/sol
    offsets_deg = [0, -0.8, 0.8]  # ~0.8° ≈ 48 NM

    for gc_lat, gc_lon in gc_points:
        for offset in offsets_deg:
            sample_lat = gc_lat + offset * math.cos(perp_bearing_rad)
            sample_lon = gc_lon + offset * math.sin(perp_bearing_rad) / max(
                math.cos(math.radians(gc_lat)), 0.01
            )
            wind = await get_upper_winds(sample_lat, sample_lon, 300)
            key = (round(sample_lat, 1), round(sample_lon, 1))
            wind_data_map[key] = {
                "speed": wind.get("wind_speed_kts", 0),
                "dir": wind.get("wind_direction", 0),
            }

    # A* optimizasyon
    result = await find_optimal_route(
        origin_icao=origin_icao,
        destination_icao=dest_icao,
        aircraft_type=aircraft_type,
        weights=weights,
        wind_data_map=wind_data_map,
    )

    if "error" in result:
        return result

    # Hava durumu bilgisini ekle
    origin_wx = await get_metar(origin_icao)
    dest_wx = await get_metar(dest_icao)

    return {
        "origin": origin,
        "destination": dest,
        "aircraft_type": aircraft_type,
        "wind_info": {
            "sample_points": len(wind_data_map),
            "avg_speed_kts": round(
                sum(w["speed"] for w in wind_data_map.values()) / max(len(wind_data_map), 1), 1
            ),
            "source": "multi_point_owm",
        },
        "origin_weather": origin_wx,
        "destination_weather": dest_wx,
        **result,
    }


@app.post("/api/compare", tags=["Optimizasyon"])
async def api_compare_routes(payload: dict):
    """Standart vs optimize edilmiş rota karşılaştırma."""
    return await api_optimize_route(payload)


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

    hw, cw = wind_components(wind_spd, wind_dir, heading)

    # AI tahmini dene
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
    cost_model = CostModel("B738")
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

    # AI tahminini fizikle kalibre et
    if ai_result is not None:
        ai_result = predictor.calibrate_with_physics(ai_result, physics_result)

    return {
        "ai_prediction": ai_result,
        "physics_prediction": physics_result,
        "model_available": ai_result is not None,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
