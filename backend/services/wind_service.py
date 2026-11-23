"""
SkyOptimizer AI — Üst Seviye Rüzgâr Servisi (Open-Meteo / GFS)

Cruise irtifalarındaki gerçek rüzgâr vektörlerini Open-Meteo üzerinden
NOAA GFS modelinden çeker. API anahtarı gerekmez.

Üç boyut + zaman:
  • lat / lon   — rota boyunca dinamik örnekleme
  • basınç      — 500/400/300/250/200 hPa (≈ FL180/240/300/340/390)
  • zaman       — `valid_time` verilirse forecast saatine göre rüzgâr

Open-Meteo tek istekte birden fazla koordinatı ve basınç seviyesini
desteklediği için 3 katman × 150 nokta birkaç HTTP çağrısıyla alınır.
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import httpx

from services.cache_manager import cache

# ─── Sabitler ───────────────────────────────────────────────────────
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Basınç seviyesi → yaklaşık irtifa (feet)
PRESSURE_LEVEL_TO_ALT = {
    850: 5000,
    700: 10000,
    600: 14000,
    500: 18000,   # FL180
    400: 24000,   # FL240
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

# Forecast penceresi (gün) — Open-Meteo GFS için üst sınır 16
MAX_FORECAST_DAYS = 7
# Geçmiş pencere (gün) — gerçek uçuş doğrulaması için GFS past_days
MAX_PAST_DAYS = 7


# ═══════════════════════════════════════════════════════════════════
#  Toplu (batch) erişim — rota örneklemesi için
# ═══════════════════════════════════════════════════════════════════

async def get_winds_multi_level(
    points: Iterable[tuple],
    levels: Iterable[int] = (300, 250, 200),
    valid_time: Optional[str] = None,
) -> dict:
    """
    Birden fazla koordinat ve basınç seviyesi için üst seviye rüzgâr.

    Args:
        points: [(lat, lon), ...]
        levels: basınç seviyeleri (hPa)
        valid_time: ISO-8601 zaman ("2025-11-24T14:00:00Z"). None → şimdi.

    Returns:
        {level: [ {"latitude", "longitude", "wind_speed_kts",
                   "wind_direction", "level_mb", "approx_altitude_ft",
                   "valid_time", "source"}, ... ]}
        Liste girdi sırasıyla aynı uzunluktadır.
    """
    points = [(float(lat), float(lon)) for lat, lon in points]
    levels = sorted({int(lv) for lv in levels}) or [300]
    target = _parse_valid_time(valid_time)

    if not points:
        return {lv: [] for lv in levels}

    out: dict = {lv: [None] * len(points) for lv in levels}
    missing: dict = {lv: [] for lv in levels}  # level → [(index, lat, lon)]

    for lv in levels:
        hour_key = target.strftime("%Y%m%d%H")
        for i, (lat, lon) in enumerate(points):
            cached = cache.get("wind", _cache_key(lat, lon, lv, hour_key))
            if cached is not None:
                out[lv][i] = cached
            else:
                missing[lv].append((i, lat, lon))

    # Tek istekte birden fazla seviye çekilir; eksik noktalar seviyeye göre
    # birleştirilir (aynı koordinat kümesi genelde tüm seviyelerde eksiktir).
    if any(missing[lv] for lv in levels):
        # Ortak nokta listesi: seviye başına ayrı istek gerekmesin diye
        # her seviye için kendi noktasını çekiyoruz ama tek istemcide.
        async with httpx.AsyncClient(timeout=25) as client:
            for lv in levels:
                if not missing[lv]:
                    continue
                fetched = await _fetch_open_meteo(
                    client, [(lat, lon) for _, lat, lon in missing[lv]],
                    lv, target,
                )
                hour_key = target.strftime("%Y%m%d%H")
                for (i, lat, lon), wind in zip(missing[lv], fetched):
                    if wind is None:
                        wind = await _owm_extrapolated(lat, lon, lv)
                    wind = {
                        **wind,
                        "latitude": lat,
                        "longitude": lon,
                        "level_mb": lv,
                        "valid_time": target.isoformat(),
                        "approx_altitude_ft": wind.get(
                            "approx_altitude_ft",
                            PRESSURE_LEVEL_TO_ALT.get(lv, 30000),
                        ),
                    }
                    out[lv][i] = wind
                    cache.set("wind", _cache_key(lat, lon, lv, hour_key), wind)

    return out


async def get_winds_batch(
    points: Iterable[tuple],
    level_mb: int = 300,
    valid_time: Optional[str] = None,
) -> list:
    """Tek seviye için toplu rüzgâr (geriye uyumlu sarmalayıcı)."""
    res = await get_winds_multi_level(points, [level_mb], valid_time)
    return res.get(int(level_mb), [])


async def get_upper_winds(
    lat: float, lon: float, level_mb: int = 300,
    valid_time: Optional[str] = None,
) -> dict:
    """Tek koordinat için üst seviye rüzgâr."""
    winds = await get_winds_batch([(lat, lon)], level_mb, valid_time)
    return winds[0]


async def get_route_winds(
    waypoints: list, level_mb: int = 300,
    valid_time: Optional[str] = None,
) -> list:
    """Rota üzerindeki her waypoint için rüzgâr verisi."""
    return await get_winds_batch(
        [(lat, lon) for lat, lon in waypoints], level_mb, valid_time
    )


# ═══════════════════════════════════════════════════════════════════
#  Zaman yardımcıları
# ═══════════════════════════════════════════════════════════════════

def _parse_valid_time(valid_time: Optional[str]) -> datetime:
    """ISO zamanı naive UTC datetime'a çevir; geçersizse şimdi."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    now = now.replace(minute=0, second=0, microsecond=0)
    if not valid_time:
        return now
    try:
        text = str(valid_time).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        dt = dt.replace(minute=0, second=0, microsecond=0)
    except (TypeError, ValueError):
        return now

    # Geçmiş ve aşırı uzak zamanlar GFS penceresinde yok; kırp.
    if dt < now - timedelta(days=MAX_PAST_DAYS):
        return now
    if dt > now + timedelta(days=MAX_FORECAST_DAYS):
        return now + timedelta(days=MAX_FORECAST_DAYS)
    return dt


def _forecast_days(target: datetime) -> int:
    """Hedef saat için gereken forecast penceresi (gün)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delta_days = math.ceil(max(0.0, (target - now).total_seconds()) / 86400.0)
    return max(1, min(MAX_FORECAST_DAYS, delta_days + 1))


def _past_days(target: datetime) -> int:
    """Hedef geçmişteyse gereken past_days (gün); gelecekte 0."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if target >= now:
        return 0
    delta_days = math.ceil((now - target).total_seconds() / 86400.0)
    return max(0, min(MAX_PAST_DAYS, delta_days))


# ═══════════════════════════════════════════════════════════════════
#  Open-Meteo istemcisi
# ═══════════════════════════════════════════════════════════════════

def _cache_key(lat: float, lon: float, level_mb: int, hour_key: str = "now") -> str:
    return f"wind:{lat:.2f},{lon:.2f},{level_mb},{hour_key}"


def _var_name(level_mb: int) -> str:
    level = level_mb if level_mb in SUPPORTED_LEVELS else 300
    return f"wind_speed_{level}hPa,wind_direction_{level}hPa"


async def _fetch_open_meteo(
    client: httpx.AsyncClient,
    points: list,
    level_mb: int,
    target: datetime,
) -> list:
    """
    Open-Meteo'dan (GFS) nokta listesi için rüzgâr çeker.

    Tüm noktalar 50'lik gruplar hâlinde gönderilir ve yanıt girdi
    sırasına göre hizalanır. Başarısız noktalar için None döner.
    """
    out: list = []
    try:
        for start in range(0, len(points), MAX_POINTS_PER_REQUEST):
            chunk = points[start:start + MAX_POINTS_PER_REQUEST]
            out.extend(await _fetch_chunk(client, chunk, level_mb, target))
    except Exception as e:
        print(f"[UYARI] Open-Meteo erişilemedi: {e}")
        return [None] * len(points)

    while len(out) < len(points):
        out.append(None)
    return out[:len(points)]


async def _fetch_chunk(
    client: httpx.AsyncClient, chunk: list, level_mb: int, target: datetime,
) -> list:
    """Tek bir Open-Meteo isteği."""
    params = {
        "latitude": ",".join(f"{lat:.2f}" for lat, _ in chunk),
        "longitude": ",".join(f"{lon:.2f}" for _, lon in chunk),
        "hourly": _var_name(level_mb),
        "models": "gfs_global",
        "wind_speed_unit": "kn",
        "forecast_days": _forecast_days(target),
        "past_days": _past_days(target),
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

        idx = _nearest_hour_index(times, target)
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
            "valid_time": target.isoformat(),
            "source": "open-meteo-gfs",
        })

    while len(results) < len(chunk):
        results.append(None)

    return results


def _nearest_hour_index(times: list, target: Optional[datetime] = None) -> Optional[int]:
    """Verilen ana en yakın saat diliminin indeksi (UTC)."""
    if not times:
        return None

    if target is None:
        target = datetime.now(timezone.utc).replace(tzinfo=None)

    best_idx, best_delta = None, None
    for i, ts in enumerate(times):
        try:
            t = datetime.fromisoformat(ts)
        except (TypeError, ValueError):
            continue
        delta = abs((t - target).total_seconds())
        if best_delta is None or delta < best_delta:
            best_idx, best_delta = i, delta

    return best_idx


# ═══════════════════════════════════════════════════════════════════
#  Rota örnekleme
# ═══════════════════════════════════════════════════════════════════

def sampling_plan(distance_nm: float, corridor_offsets_nm=(0, -80, 80)) -> dict:
    """
    Rota uzunluğuna göre dinamik rüzgâr örnekleme planı.

    Sabit 21 örnek kısa rotalarda gereksiz sık, 7.000 NM'lik rotalarda
    ise 240 NM'de bir (çok seyrek) oluyordu. Artık hedef ~150 NM aralık;
    alt/üst sınırlarla istek sayısı kontrol altında tutuluyor.

    Returns:
        {"samples": [...], "spacing_nm": float, "offsets_nm": [...]}
    """
    distance_nm = max(1.0, float(distance_nm))
    base_points = int(math.ceil(distance_nm / 150.0))
    base_points = max(6, min(48, base_points))
    spacing_nm = distance_nm / base_points
    return {
        "base_points": base_points,
        "spacing_nm": round(spacing_nm, 1),
        "offsets_nm": list(corridor_offsets_nm),
    }


def build_sample_points(
    lat1: float, lon1: float, lat2: float, lon2: float,
    distance_nm: float,
) -> list:
    """
    Great-circle hattı + koridor ofsetleri için örnek koordinatlar.

    Returns:
        [(lat, lon), ...] — ofsetler dahil
    """
    from utils.geo import great_circle_waypoints, initial_bearing

    plan = sampling_plan(distance_nm)
    base = great_circle_waypoints(lat1, lon1, lat2, lon2, plan["base_points"])
    bearing = initial_bearing(lat1, lon1, lat2, lon2)
    perp_rad = math.radians((bearing + 90) % 360)

    points = []
    for gc_lat, gc_lon in base:
        for offset_nm in plan["offsets_nm"]:
            offset_deg = offset_nm / 60.0
            sample_lat = gc_lat + offset_deg * math.cos(perp_rad)
            sample_lon = gc_lon + offset_deg * math.sin(perp_rad) / max(
                math.cos(math.radians(gc_lat)), 0.01
            )
            points.append((sample_lat, sample_lon))
    return points


def build_wind_map(points: list, winds: list) -> dict:
    """
    (lat, lon) → {"speed", "dir"} haritası. Boylam farkı 180°'yi aşan
    noktalarda tarih çizgisi doğru işlenir (harita boylamı -180..180).
    """
    wind_map = {}
    for (lat, lon), wind in zip(points, winds):
        if not wind:
            continue
        lon_norm = ((lon + 180) % 360) - 180
        lat_key = round(lat, 1)
        lon_key = round(lon_norm, 1)
        wind_map[(lat_key, lon_key)] = {
            "speed": float(wind.get("wind_speed_kts", 0) or 0),
            "dir": float(wind.get("wind_direction", 0) or 0),
        }
    return wind_map


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
    factors = {
        850: 1.5, 700: 2.0, 600: 2.6, 500: 3.0, 400: 4.0,
        300: 5.0, 250: 6.0, 200: 7.0,
    }
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
