"""
SkyOptimizer AI — ADS-B Veri Servisi (OpenSky Network)

Canlı uçuş verileri, geçmiş uçuş izleri ve son 24 saatteki gerçek
uçuşlar. Günlük 4000 istek limitine dikkat eder.

Not: OpenSky'nin `/metadata/aircraft` uç noktası kaldırıldığı için
uçak tipi bilgisi `services.aircraft_service` (hexdb.io) üzerinden gelir.
"""

import time
from datetime import datetime, timezone
from typing import Optional

import httpx

from config import (
    OPENSKY_BASE_URL,
    OPENSKY_CLIENT_ID,
    OPENSKY_CLIENT_SECRET,
    OPENSKY_TOKEN_URL,
)
from services.aircraft_service import classify_flight
from services.cache_manager import cache, opensky_limiter


# OAuth2 token cache
_access_token: Optional[str] = None
_token_expiry: float = 0
# Geçersiz kimlik bilgisiyle her istekte token POST'u yapıp OpenSky'yi
# kilitlememek için başarısızlığı 10 dakika hatırla.
_token_failure_until: float = 0
# 429 sonrası kısa süre istek atma (OpenSky anonim limiti).
_rate_limited_until: float = 0


async def _get_access_token() -> Optional[str]:
    """OpenSky OAuth2 access token al."""
    global _access_token, _token_expiry, _token_failure_until

    if _access_token and time.time() < _token_expiry:
        return _access_token

    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
        return None

    if time.time() < _token_failure_until:
        return None

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                OPENSKY_TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": OPENSKY_CLIENT_ID,
                    "client_secret": OPENSKY_CLIENT_SECRET,
                },
            )
            if response.status_code == 200:
                data = response.json()
                _access_token = data.get("access_token")
                # Token'ı 5 dakika erken yenile
                _token_expiry = time.time() + data.get("expires_in", 3600) - 300
                return _access_token
            _token_failure_until = time.time() + 600
            print(
                "[OpenSky] Token alınamadı "
                f"(HTTP {response.status_code}) — 10 dk anonim erişim."
            )
    except Exception as e:
        _token_failure_until = time.time() + 120
        print(f"[OpenSky] Token alınamadı: {e}")

    return None


async def _opensky_get(path: str, params: dict) -> tuple:
    """
    OpenSky REST çağrısı — kimlik doğrulama + kota + 429 yönetimi.

    Returns:
        (status_code, payload) — payload hata durumunda {"error": ...}
    """
    global _rate_limited_until
    if time.time() < _rate_limited_until:
        return 429, {"error": "OpenSky rate limit aşıldı (429) — kısa süre bekleniyor"}

    if not opensky_limiter.can_request():
        # 5 saniyelik minimum aralık ise beklenir; günlük kota ise durulur.
        if opensky_limiter.remaining_requests <= 0:
            return 0, {"error": "Günlük OpenSky API limiti aşıldı"}
        opensky_limiter.wait_if_needed()
    else:
        opensky_limiter.wait_if_needed()

    token = await _get_access_token()
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.get(
                f"{OPENSKY_BASE_URL}{path}", params=params, headers=headers
            )
    except Exception as exc:
        return 0, {"error": f"Bağlantı hatası: {exc}"}

    opensky_limiter.record_request()

    if response.status_code == 200:
        try:
            return 200, response.json()
        except ValueError:
            return 200, None
    if response.status_code == 429:
        _rate_limited_until = time.time() + 45
        retry_s = response.headers.get("X-Rate-Limit-Retry-After-Seconds")
        try:
            retry_min = max(1, int(float(retry_s)) // 60)
            detail = f" — yaklaşık {retry_min} dk sonra yenilenir"
        except (TypeError, ValueError):
            detail = ""
        return 429, {"error": f"OpenSky uçuş listesi kotası doldu (429){detail}"}
    if response.status_code == 403:
        return 403, {
            "error": (
                "OpenSky geçmiş veri erişimi reddedildi (403). "
                "credentials.json içine geçerli clientId/clientSecret ekleyin."
            )
        }
    return response.status_code, {
        "error": f"OpenSky API hatası: {response.status_code}"
    }


async def get_live_flights(
    lamin: float = None,
    lamax: float = None,
    lomin: float = None,
    lomax: float = None,
) -> dict:
    """
    Belirli bölgedeki canlı uçuşları döndürür.
    15 dakika cache'lenir, günlük limit takip edilir.
    """
    lamin = lamin if lamin is not None else 10.0
    lamax = lamax if lamax is not None else 65.0
    lomin = lomin if lomin is not None else -30.0
    lomax = lomax if lomax is not None else 60.0

    cache_key = f"flights:{lamin:.1f},{lamax:.1f},{lomin:.1f},{lomax:.1f}"
    cached = cache.get("opensky", cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    status, data = await _opensky_get(
        "/states/all",
        {
            "lamin": lamin, "lamax": lamax,
            "lomin": lomin, "lomax": lomax,
            "extended": 1,  # ADS-B emitter category (uçak sınıfı için)
        },
    )

    if status != 200 or data is None:
        return {
            "flights": [],
            "error": data.get("error") if isinstance(data, dict) else "OpenSky hatası",
            "remaining": opensky_limiter.remaining_requests,
            "from_cache": False,
        }

    states = data.get("states", []) or []
    flights = []
    for state in states:
        if len(state) < 17:
            continue
        altitude_m = state[7]
        velocity_ms = state[9]
        category = state[17] if len(state) > 17 else None
        flight = {
            "icao24": state[0],
            "callsign": (state[1] or "").strip(),
            "origin_country": state[2],
            "longitude": state[5],
            "latitude": state[6],
            "altitude_m": altitude_m,  # barometrik
            "on_ground": state[8],
            "velocity_ms": velocity_ms,
            "true_track": state[10],
            "vertical_rate": state[11],
            "geo_altitude_m": state[13],
            "squawk": state[14],
            "emitter_category": category,
            "aircraft_class": classify_flight(
                velocity_ms, altitude_m, category
            ),
        }
        if not flight["on_ground"] and flight["latitude"] and flight["longitude"]:
            flights.append(flight)

    result = {
        "flights": flights,
        "count": len(flights),
        "timestamp": data.get("time"),
        "remaining": opensky_limiter.remaining_requests,
        "from_cache": False,
        "region": {
            "lamin": lamin, "lamax": lamax,
            "lomin": lomin, "lomax": lomax,
        },
    }

    cache.set("opensky", cache_key, result)
    return result


async def get_flight_track(icao24: str, time_s: Optional[int] = None) -> dict:
    """
    Belirli uçağın iz bilgisi.

    time_s verilmezse (0) uçağın mevcut uçuşunun izi döner. Geçmiş bir
    uçuş için `lastSeen` zaman damgası verilir.
    """
    cache_key = f"track:{icao24}:{time_s or 0}"
    cached = cache.get("opensky", cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    status, data = await _opensky_get(
        "/tracks/all", {"icao24": icao24, "time": int(time_s or 0)}
    )
    if status != 200 or data is None:
        return {
            "error": data.get("error") if isinstance(data, dict) else "İz alınamadı",
            "track": [],
        }

    result = {
        "icao24": data.get("icao24"),
        "callsign": (data.get("callsign") or "").strip(),
        "start_time": data.get("startTime"),
        "end_time": data.get("endTime"),
        "track": data.get("path", []),
        "from_cache": False,
    }
    cache.set("opensky", cache_key, result)
    return result


# ═══════════════════════════════════════════════════════════════════
#  Son 24 saatteki gerçek uçuşlar (doğrulama için)
# ═══════════════════════════════════════════════════════════════════

def _flight_summary(raw: dict) -> dict:
    return {
        "icao24": raw.get("icao24"),
        "callsign": (raw.get("callsign") or "").strip(),
        "departure": raw.get("estDepartureAirport"),
        "destination": raw.get("estArrivalAirport"),
        "first_seen": raw.get("firstSeen"),
        "last_seen": raw.get("lastSeen"),
        "departure_distance_m": raw.get("estDepartureAirportHorizDistance"),
        "arrival_distance_m": raw.get("estArrivalAirportHorizDistance"),
    }


# OpenSky anonim erişimi geçmiş uçuşlarda yalnızca son 12 saati kapsar.
ANONYMOUS_HISTORY_HOURS = 12
AUTHENTICATED_HISTORY_HOURS = 48


async def _history_window(hours: int) -> tuple:
    """
    İstenen zaman penceresini kimlik durumuna göre sınırla.

    Geçerli OAuth token varsa 48 saat; yoksa OpenSky anonim erişimi
    12 saatten eski uçuşlara 403 döndürür.
    """
    hours = max(1, int(hours))
    token = await _get_access_token()
    limit = AUTHENTICATED_HISTORY_HOURS if token else ANONYMOUS_HISTORY_HOURS
    return min(hours, limit), limit, token is not None


async def get_recent_arrivals(airport: str, hours: int = 12) -> dict:
    """Bir havalimanına son N saatte inen uçuşlar (OpenSky)."""
    airport = (airport or "").strip().upper()
    hours, limit, authenticated = await _history_window(hours)
    cache_key = f"arrivals:{airport}:{hours}"
    cached = cache.get("opensky", cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    now = int(datetime.now(timezone.utc).timestamp())
    status, data = await _opensky_get(
        "/flights/arrival",
        {"airport": airport, "begin": now - hours * 3600, "end": now},
    )
    if status != 200 or not isinstance(data, list):
        return {
            "airport": airport,
            "flights": [],
            "error": (data or {}).get("error") if isinstance(data, dict) else None,
        }

    result = {
        "airport": airport,
        "hours": hours,
        "history_limit_hours": limit,
        "authenticated": authenticated,
        "flights": [_flight_summary(f) for f in data],
        "count": len(data),
    }
    cache.set("opensky", cache_key, result)
    return result


async def get_recent_departures(airport: str, hours: int = 12) -> dict:
    """Bir havalimanından son N saatte kalkan uçuşlar."""
    airport = (airport or "").strip().upper()
    hours, limit, authenticated = await _history_window(hours)
    cache_key = f"departures:{airport}:{hours}"
    cached = cache.get("opensky", cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    now = int(datetime.now(timezone.utc).timestamp())
    status, data = await _opensky_get(
        "/flights/departure",
        {"airport": airport, "begin": now - hours * 3600, "end": now},
    )
    if status != 200 or not isinstance(data, list):
        return {
            "airport": airport,
            "flights": [],
            "error": (data or {}).get("error") if isinstance(data, dict) else None,
        }

    result = {
        "airport": airport,
        "hours": hours,
        "history_limit_hours": limit,
        "authenticated": authenticated,
        "flights": [_flight_summary(f) for f in data],
        "count": len(data),
    }
    cache.set("opensky", cache_key, result)
    return result


async def find_recent_flight(
    origin: str, destination: str, hours: int = 12,
) -> dict:
    """
    Son N saatte `origin` → `destination` uçmuş gerçek bir uçuş bul.

    OpenSky'nin `/flights/aircraft` uç noktası kimlik doğrulama istiyor;
    `/flights/arrival` ise anonim erişime açık. Bu yüzden varış
    havalimanına inen uçuşlar arasından kalkışı eşleştiriyoruz.
    """
    arrivals = await get_recent_arrivals(destination, hours)
    if arrivals.get("error") and not arrivals.get("flights"):
        return {"available": False, "reason": arrivals["error"]}

    origin = (origin or "").strip().upper()
    matches = [
        f for f in arrivals.get("flights", [])
        if (f.get("departure") or "").upper() == origin
    ]
    if not matches:
        # Kalkış havalimanı bazen null gelir; kalkış listesiyle çapraz kontrol
        departures = await get_recent_departures(origin, hours)
        dep_icaos = {
            f["icao24"]: f for f in departures.get("flights", [])
            if (f.get("destination") or "").upper() == destination
        }
        matches = [
            f for f in arrivals.get("flights", [])
            if f.get("icao24") in dep_icaos
        ]

    if not matches:
        return {
            "available": False,
            "reason": (
                f"Son {hours} saatte {origin} → {destination} uçuşu bulunamadı. "
                "Farklı bir rota veya daha geniş zaman aralığı deneyin."
            ),
        }

    matches.sort(key=lambda f: f.get("last_seen") or 0, reverse=True)
    return {
        "available": True,
        "flight": matches[0],
        "alternatives": matches[1:6],
        "hours": hours,
    }
