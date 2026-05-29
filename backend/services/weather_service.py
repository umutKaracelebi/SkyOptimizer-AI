"""
SkyOptimizer AI — Meteoroloji Servisi
AviationWeather.gov'dan METAR/TAF, OpenWeatherMap'ten hava durumu çeker.
"""

import httpx

from config import (
    AVIATION_WEATHER_BASE_URL,
    OPENWEATHER_BASE_URL,
    OPENWEATHER_API_KEY,
)
from services.cache_manager import cache


async def get_metar(icao: str) -> dict:
    """
    Havalimanı METAR (anlık gözlem) verisi.
    Kaynak: AviationWeather.gov (ücretsiz, API key gerekmez).
    """
    icao = icao.upper().strip()
    cache_key = f"metar:{icao}"
    cached = cache.get("weather", cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{AVIATION_WEATHER_BASE_URL}/metar",
                params={"ids": icao, "format": "json"},
            )

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                metar = data[0]
                result = {
                    "icao": icao,
                    "raw": metar.get("rawOb", ""),
                    "temperature_c": metar.get("temp"),
                    "dewpoint_c": metar.get("dewp"),
                    "wind_direction": metar.get("wdir"),
                    "wind_speed_kts": metar.get("wspd"),
                    "wind_gust_kts": metar.get("wgst"),
                    "visibility_m": metar.get("visib"),
                    "altimeter_hpa": metar.get("altim"),
                    "flight_category": metar.get("fltcat"),  # VFR/IFR/MVFR/LIFR
                    "cloud_layers": metar.get("clouds", []),
                    "observation_time": metar.get("reportTime"),
                }
                cache.set("weather", cache_key, result)
                return result

        return {"icao": icao, "error": "METAR verisi bulunamadı"}

    except Exception as e:
        return {"icao": icao, "error": f"Bağlantı hatası: {str(e)}"}


async def get_taf(icao: str) -> dict:
    """
    Havalimanı TAF (tahmin) verisi.
    Kaynak: AviationWeather.gov.
    """
    icao = icao.upper().strip()
    cache_key = f"taf:{icao}"
    cached = cache.get("weather", cache_key)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{AVIATION_WEATHER_BASE_URL}/taf",
                params={"ids": icao, "format": "json"},
            )

        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                taf = data[0]
                result = {
                    "icao": icao,
                    "raw": taf.get("rawTAF", ""),
                    "issue_time": taf.get("issueTime"),
                    "valid_from": taf.get("validTimeFrom"),
                    "valid_to": taf.get("validTimeTo"),
                    "forecasts": taf.get("fcsts", []),
                }
                cache.set("weather", cache_key, result)
                return result

        return {"icao": icao, "error": "TAF verisi bulunamadı"}

    except Exception as e:
        return {"icao": icao, "error": f"Bağlantı hatası: {str(e)}"}


async def get_weather_at_point(lat: float, lon: float) -> dict:
    """
    Belirli koordinattaki hava durumu (OpenWeatherMap).
    Rota üzerindeki noktalar için kullanılır.
    """
    cache_key = f"owm:{lat:.2f},{lon:.2f}"
    cached = cache.get("weather", cache_key)
    if cached is not None:
        return cached

    if not OPENWEATHER_API_KEY:
        return {"error": "OpenWeatherMap API anahtarı tanımlı değil"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{OPENWEATHER_BASE_URL}/weather",
                params={
                    "lat": lat,
                    "lon": lon,
                    "appid": OPENWEATHER_API_KEY,
                    "units": "metric",
                },
            )

        if response.status_code == 200:
            data = response.json()
            wind = data.get("wind", {})
            main = data.get("main", {})

            result = {
                "latitude": lat,
                "longitude": lon,
                "temperature_c": main.get("temp"),
                "pressure_hpa": main.get("pressure"),
                "humidity_pct": main.get("humidity"),
                "wind_speed_ms": wind.get("speed"),
                "wind_speed_kts": round((wind.get("speed", 0) or 0) * 1.944, 1),
                "wind_direction": wind.get("deg"),
                "wind_gust_ms": wind.get("gust"),
                "visibility_m": data.get("visibility"),
                "description": data.get("weather", [{}])[0].get("description", ""),
            }
            cache.set("weather", cache_key, result)
            return result

        return {"error": f"OWM API hatası: {response.status_code}"}

    except Exception as e:
        return {"error": f"Bağlantı hatası: {str(e)}"}


async def get_route_weather(waypoints: list) -> list:
    """
    Rota üzerindeki waypoint'ler için hava durumu profili.
    Her waypoint: (lat, lon) tuple.
    """
    weather_profile = []
    for lat, lon in waypoints:
        wx = await get_weather_at_point(lat, lon)
        weather_profile.append(wx)
    return weather_profile
