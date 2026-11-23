"""
SkyOptimizer AI — Üst Seviye Rüzgâr Servisi (Open-Meteo / GFS)

Cruise irtifalarındaki (varsayılan 300 hPa ≈ FL300) gerçek rüzgâr vektörlerini
Open-Meteo üzerinden NOAA GFS modelinden çeker. API anahtarı gerekmez.

Open-Meteo tek istekte birden fazla koordinatı desteklediği için rota boyunca
onlarca örnek noktası tek HTTP çağrısıyla alınabilir.

Yedek kaynak: OpenWeatherMap yüzey rüzgârından yükseklik düzeltmesiyle
tahmin (yalnızca Open-Meteo erişilemezse; `source` alanı bunu belirtir).
"""

import math
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx

from services.cache_manager import cache

# ─── Sabitler ───────────────────────────────────────────────────────
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Basınç seviyesi → yaklaşık irtifa (feet)
PRESSURE_LEVEL_TO_ALT = {
    850: 5000,
    700: 10000,
    500: 18000,
    400: 24000,
    300: 30000,   # FL300
    250: 34000,   # FL340
    200: 39000,   # FL390
}

# Open-Meteo'nun desteklediği basınç seviyeleri (hPa)
SUPPORTED_LEVELS = {
    1000, 975, 950, 925, 900, 850, 800, 700,
    600, 500, 400, 300, 250, 200, 150, 100,
}

# Tek istekte gönderilebilecek koordinat sayısı (Open-Meteo sınırına pay bırakır)
MAX_POINTS_PER_REQUEST = 50


# ═══════════════════════════════════════════════════════════════════
#  Toplu (batch) erişim — rota örneklemesi için
# ═══════════════════════════════════════════════════════════════════

async def get_winds_batch(
    points: Iterable[tuple],
    level_mb: int = 300,
) -> list:
    """
    Birden fazla koordinat için üst seviye rüzgâr verisi.

    Args:
        points: [(lat, lon), ...]
        level_mb: Basınç seviyesi (hPa)

    Returns:
        Girdi sırasıyla aynı uzunlukta liste. Her eleman:
        {"latitude", "longitude", "wind_speed_kts", "wind_direction",
         "source", "approx_altitude_ft"}
    """
    points = [(float(lat), float(lon)) for lat, lon in points]
    if not points:
        return []

    # 1) Cache'den karşıla
    results: list = [None] * len(points)
    missing: list = []          # (index, lat, lon)
    for i, (lat, lon) in enumerate(points):
        cached = cache.get("wind", _cache_key(lat, lon, level_mb))
        if cached is not None:
            results[i] = cached
        else:
            missing.append((i, lat, lon))

    # 2) Eksikleri tek/az sayıda istekle tamamla
    if missing:
        fetched = await _fetch_open_meteo(
            [(lat, lon) for _, lat, lon in missing], level_mb
        )
        for (i, lat, lon), wind in zip(missing, fetched):
            if wind is None:
                wind = await _owm_extrapolated(lat, lon, level_mb)
            wind = {
                **wind,
                "latitude": lat,
                "longitude": lon,
                "level_mb": level_mb,
                "approx_altitude_ft": wind.get(
                    "approx_altitude_ft",
                    PRESSURE_LEVEL_TO_ALT.get(level_mb, 30000),
                ),
            }
            results[i] = wind
            cache.set("wind", _cache_key(lat, lon, level_mb), wind)

    return results


async def get_upper_winds(lat: float, lon: float, level_mb: int = 300) -> dict:
    """Tek koordinat için üst seviye rüzgâr (toplu erişimin sarmalayıcısı)."""
    winds = await get_winds_batch([(lat, lon)], level_mb)
    return winds[0]


async def get_route_winds(waypoints: list, level_mb: int = 300) -> list:
    """Rota üzerindeki her waypoint için rüzgâr verisi."""
    return await get_winds_batch([(lat, lon) for lat, lon in waypoints], level_mb)


# ═══════════════════════════════════════════════════════════════════
#  Open-Meteo istemcisi
# ═══════════════════════════════════════════════════════════════════

def _cache_key(lat: float, lon: float, level_mb: int) -> str:
    return f"wind:{lat:.2f},{lon:.2f},{level_mb}"


def _var_name(level_mb: int) -> str:
    level = level_mb if level_mb in SUPPORTED_LEVELS else 300
    return f"wind_speed_{level}hPa,wind_direction_{level}hPa"


async def _fetch_open_meteo(points: list, level_mb: int) -> list:
    """
    Open-Meteo'dan (GFS) nokta listesi için rüzgâr çeker.

    Tüm noktalar tek istekte (50'lik gruplar hâlinde) gönderilir ve
    yanıt girdi sırasına göre hizalanır. Başarısız noktalar için None döner.
    """
    out: list = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            for start in range(0, len(points), MAX_POINTS_PER_REQUEST):
                chunk = points[start:start + MAX_POINTS_PER_REQUEST]
                out.extend(await _fetch_chunk(client, chunk, level_mb))
    except Exception as e:
        print(f"[UYARI] Open-Meteo erişilemedi: {e}")
        return [None] * len(points)

    return out


async def _fetch_chunk(client: httpx.AsyncClient, chunk: list, level_mb: int) -> list:
    """Tek bir Open-Meteo isteği."""
    params = {
        "latitude": ",".join(f"{lat:.2f}" for lat, _ in chunk),
        "longitude": ",".join(f"{lon:.2f}" for _, lon in chunk),
        "hourly": _var_name(level_mb),
        "models": "gfs_global",
        "wind_speed_unit": "kn",
        "forecast_days": 1,
        "timezone": "UTC",
    }

    try:
        response = await client.get(OPEN_METEO_URL, params=params)
        if response.status_code != 200:
            print(f"[UYARI] Open-Meteo HTTP {response.status_code}: {response.text[:120]}")
            return [None] * len(chunk)
        data = response.json()
    except Exception as e:
        print(f"[UYARI] Open-Meteo isteği başarısız: {e}")
        return [None] * len(chunk)

    # Tek nokta isteğinde yanıt dict, çok noktada liste döner
    items = data if isinstance(data, list) else [data]
    if len(items) != len(chunk):
        print(
            f"[UYARI] Open-Meteo beklenen {len(chunk)} nokta yerine "
            f"{len(items)} döndürdü."
        )

    level = level_mb if level_mb in SUPPORTED_LEVELS else 300
    speed_key = f"wind_speed_{level}hPa"
    dir_key = f"wind_direction_{level}hPa"

    results = []
    for item in items:
        hourly = item.get("hourly") or {}
        times = hourly.get("time") or []
        speeds = hourly.get(speed_key) or []
        dirs = hourly.get(dir_key) or []

        idx = _nearest_hour_index(times)
        if idx is None or idx >= len(speeds) or speeds[idx] is None:
            results.append(None)
            continue

        speed_kts = float(speeds[idx])
        direction = dirs[idx] if idx < len(dirs) and dirs[idx] is not None else 0

        results.append({
            "wind_speed_kts": round(speed_kts, 1),
            "wind_speed_ms": round(speed_kts * 0.514444, 1),
            "wind_direction": round(float(direction), 0),
            "approx_altitude_ft": PRESSURE_LEVEL_TO_ALT.get(level, 30000),
            "source": "open-meteo-gfs",
        })

    # Eksik nokta olduysa boyu tamamla
    while len(results) < len(chunk):
        results.append(None)

    return results


def _nearest_hour_index(times: list) -> Optional[int]:
    """Şu ana en yakın saat diliminin indeksi (UTC)."""
    if not times:
        return None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    best_idx, best_delta = None, None

    for i, ts in enumerate(times):
        try:
            t = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        delta = abs((t - now).total_seconds())
        if best_delta is None or delta < best_delta:
            best_idx, best_delta = i, delta

    return best_idx


# ═══════════════════════════════════════════════════════════════════
#  Yedek kaynaklar
# ═══════════════════════════════════════════════════════════════════

async def _owm_extrapolated(lat: float, lon: float, level_mb: int) -> dict:
    """
    OpenWeatherMap yüzey rüzgârından yükseklik düzeltmesiyle tahmin.

    Yalnızca Open-Meteo erişilemediğinde kullanılır; gerçek üst seviye
    verisi değildir, bu yüzden `source` alanı bunu açıkça belirtir.
    """
    from config import OPENWEATHER_API_KEY, OPENWEATHER_BASE_URL

    if not OPENWEATHER_API_KEY:
        return _fallback_wind(level_mb)

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
        if response.status_code != 200:
            return _fallback_wind(level_mb)

        data = response.json()
        wind = data.get("wind", {})
        surface_speed_ms = wind.get("speed", 0) or 0
        surface_dir = wind.get("deg", 0) or 0

        upper_speed_ms = surface_speed_ms * _altitude_wind_factor(level_mb)
        # Ekman spirali: rüzgâr yükseldikçe saat yönünde döner
        upper_dir = (surface_dir + min(30, (1013 - level_mb) / 20)) % 360

        return {
            "wind_speed_kts": round(upper_speed_ms * 1.943844, 1),
            "wind_speed_ms": round(upper_speed_ms, 1),
            "wind_direction": round(upper_dir, 0),
            "approx_altitude_ft": PRESSURE_LEVEL_TO_ALT.get(level_mb, 30000),
            "source": "owm_extrapolated",
        }
    except Exception:
        return _fallback_wind(level_mb)


def _altitude_wind_factor(level_mb: int) -> float:
    """Basınç seviyesine göre rüzgâr hız çarpanı (yaklaşık)."""
    factors = {850: 1.5, 700: 2.0, 500: 3.0, 400: 4.0, 300: 5.0, 250: 6.0, 200: 7.0}
    return factors.get(level_mb, 4.0)


def _fallback_wind(level_mb: int) -> dict:
    """Hiçbir kaynağa erişilemediğinde varsayılan batı rüzgârı."""
    return {
        "wind_speed_kts": 29.2,
        "wind_speed_ms": 15.0,
        "wind_direction": 270.0,
        "approx_altitude_ft": PRESSURE_LEVEL_TO_ALT.get(level_mb, 30000),
        "source": "fallback",
    }
