"""
SkyOptimizer AI — NOAA GFS Rüzgâr Servisi
Üst seviye rüzgâr verilerini (cruise irtifaları) çeker.
NOAA NOMADS sunucusundan — API key gerekmez, tamamen ücretsiz.
"""

from typing import Optional
import httpx
from services.cache_manager import cache


# Basınç seviyesi → yaklaşık irtifa (feet) eşlemesi
PRESSURE_LEVEL_TO_ALT = {
    "850": 5000,
    "700": 10000,
    "500": 18000,
    "400": 24000,
    "300": 30000,   # FL300
    "250": 34000,   # FL340
    "200": 39000,   # FL390
}


async def get_upper_winds(
    lat: float,
    lon: float,
    level_mb: int = 300,
) -> dict:
    """
    Belirli koordinat ve basınç seviyesinde rüzgâr verisi.

    OpenWeatherMap'i yedek kaynak olarak kullanır (NOAA GFS yerine)
    çünkü GRIB verisi ayrıştırmak ek bağımlılık gerektirir.
    Üretim ortamında getgfs kütüphanesi ile NOAA'ya geçilecek.

    Args:
        lat: Enlem
        lon: Boylam
        level_mb: Basınç seviyesi (mb) — 300, 250, 200 vb.

    Returns:
        Rüzgâr vektörü bilgileri
    """
    cache_key = f"wind:{lat:.1f},{lon:.1f},{level_mb}"
    cached = cache.get("wind", cache_key)
    if cached is not None:
        return cached

    # OpenWeatherMap ile yüzey rüzgârını al ve irtifaya göre ölçekle
    # Not: Gerçek üst seviye rüzgâr verisi için NOAA GFS kullanılacak (Sprint 4)
    from config import OPENWEATHER_API_KEY, OPENWEATHER_BASE_URL

    if not OPENWEATHER_API_KEY:
        return _fallback_wind(lat, lon, level_mb)

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

            surface_speed_ms = wind.get("speed", 0) or 0
            surface_dir = wind.get("deg", 0) or 0

            # Yükseklik düzeltme faktörü (basitleştirilmiş)
            # Gerçek üst seviye rüzgârları tipik olarak yüzey rüzgârının 3-8 katıdır
            altitude_factor = _altitude_wind_factor(level_mb)
            upper_speed_ms = surface_speed_ms * altitude_factor

            # Rüzgâr yönü yükseldikçe saat yönünde döner (Ekman spirali)
            direction_shift = min(30, (1013 - level_mb) / 20)
            upper_dir = (surface_dir + direction_shift) % 360

            result = {
                "latitude": lat,
                "longitude": lon,
                "level_mb": level_mb,
                "approx_altitude_ft": PRESSURE_LEVEL_TO_ALT.get(str(level_mb), 30000),
                "wind_speed_ms": round(upper_speed_ms, 1),
                "wind_speed_kts": round(upper_speed_ms * 1.944, 1),
                "wind_direction": round(upper_dir, 0),
                "u_component_ms": round(-upper_speed_ms * _sind(upper_dir), 2),
                "v_component_ms": round(-upper_speed_ms * _cosd(upper_dir), 2),
                "source": "owm_extrapolated",
                "note": "Yüzey verisinden tahmin — NOAA GFS ile değiştirilecek",
            }

            cache.set("wind", cache_key, result)
            return result

    except Exception as e:
        return {"error": f"Rüzgâr verisi alınamadı: {str(e)}"}

    return _fallback_wind(lat, lon, level_mb)


async def get_route_winds(
    waypoints: list,
    level_mb: int = 300,
) -> list:
    """
    Rota üzerindeki her waypoint için rüzgâr verisi.
    waypoints: [(lat, lon), ...] listesi
    """
    winds = []
    for lat, lon in waypoints:
        wind = await get_upper_winds(lat, lon, level_mb)
        winds.append(wind)
    return winds


def _altitude_wind_factor(level_mb: int) -> float:
    """Basınç seviyesine göre rüzgâr hız çarpanı (yaklaşık)."""
    factors = {
        850: 1.5,
        700: 2.0,
        500: 3.0,
        400: 4.0,
        300: 5.0,   # FL300 — jet stream bölgesi
        250: 6.0,   # FL340
        200: 7.0,   # FL390
    }
    return factors.get(level_mb, 4.0)


def _fallback_wind(lat: float, lon: float, level_mb: int) -> dict:
    """API çalışmadığında varsayılan rüzgâr verisi."""
    return {
        "latitude": lat,
        "longitude": lon,
        "level_mb": level_mb,
        "approx_altitude_ft": PRESSURE_LEVEL_TO_ALT.get(str(level_mb), 30000),
        "wind_speed_ms": 15.0,
        "wind_speed_kts": 29.2,
        "wind_direction": 270,
        "u_component_ms": 15.0,
        "v_component_ms": 0.0,
        "source": "fallback",
        "note": "Varsayılan batı rüzgârı (API erişilemedi)",
    }


import math

def _sind(deg: float) -> float:
    return math.sin(math.radians(deg))

def _cosd(deg: float) -> float:
    return math.cos(math.radians(deg))
