"""
SkyOptimizer AI — ADS-B Veri Servisi (OpenSky Network)
Canlı uçuş verilerini çeker. Günlük 4000 istek limitine dikkat eder.
"""

import time
from typing import Optional

import httpx

from config import (
    OPENSKY_BASE_URL,
    OPENSKY_CLIENT_ID,
    OPENSKY_CLIENT_SECRET,
    OPENSKY_TOKEN_URL,
    TURKEY_BBOX,
)
from services.cache_manager import cache, opensky_limiter


# OAuth2 token cache
_access_token: Optional[str] = None
_token_expiry: float = 0


async def _get_access_token() -> Optional[str]:
    """OpenSky OAuth2 access token al."""
    global _access_token, _token_expiry

    if _access_token and time.time() < _token_expiry:
        return _access_token

    if not OPENSKY_CLIENT_ID or not OPENSKY_CLIENT_SECRET:
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
    except Exception as e:
        print(f"[OpenSky] Token alınamadı: {e}")

    return None


async def get_live_flights(
    lamin: float = None,
    lamax: float = None,
    lomin: float = None,
    lomax: float = None,
) -> dict:
    """
    Belirli bölgedeki canlı uçuşları döndürür.
    Varsayılan: Avrupa + Ortadoğu + Merkez Asya bölgesi.
    15 dakika cache'lenir, günlük limit takip edilir.
    """
    # Varsayılan: Avrupa + Ortadoğu + Merkez Asya bölgesi
    # (OpenSky tüm dünyayı tek istekte döndüremez)
    lamin = lamin if lamin is not None else 10.0
    lamax = lamax if lamax is not None else 65.0
    lomin = lomin if lomin is not None else -30.0
    lomax = lomax if lomax is not None else 60.0

    cache_key = f"flights:{lamin:.1f},{lamax:.1f},{lomin:.1f},{lomax:.1f}"
    cached = cache.get("opensky", cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    # Rate limit kontrolü
    if not opensky_limiter.can_request():
        return {
            "flights": [],
            "error": "Günlük API limiti aşıldı veya çok sık istek",
            "remaining": opensky_limiter.remaining_requests,
            "from_cache": False,
        }

    opensky_limiter.wait_if_needed()

    try:
        token = await _get_access_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{OPENSKY_BASE_URL}/states/all",
                params={
                    "lamin": lamin,
                    "lamax": lamax,
                    "lomin": lomin,
                    "lomax": lomax,
                },
                headers=headers,
            )

        opensky_limiter.record_request()

        if response.status_code == 200:
            data = response.json()
            states = data.get("states", []) or []

            flights = []
            for state in states:
                if len(state) < 17:
                    continue
                flight = {
                    "icao24": state[0],
                    "callsign": (state[1] or "").strip(),
                    "origin_country": state[2],
                    "longitude": state[5],
                    "latitude": state[6],
                    "altitude_m": state[7],  # barometrik
                    "on_ground": state[8],
                    "velocity_ms": state[9],
                    "true_track": state[10],
                    "vertical_rate": state[11],
                    "geo_altitude_m": state[13],
                }
                # Sadece havadaki uçakları al
                if not flight["on_ground"] and flight["latitude"] and flight["longitude"]:
                    flights.append(flight)

            result = {
                "flights": flights,
                "count": len(flights),
                "timestamp": data.get("time"),
                "remaining": opensky_limiter.remaining_requests,
                "from_cache": False,
            }

            cache.set("opensky", cache_key, result)
            return result

        elif response.status_code == 429:
            return {
                "flights": [],
                "error": "OpenSky rate limit aşıldı (429)",
                "remaining": opensky_limiter.remaining_requests,
                "from_cache": False,
            }
        else:
            return {
                "flights": [],
                "error": f"OpenSky API hatası: {response.status_code}",
                "remaining": opensky_limiter.remaining_requests,
                "from_cache": False,
            }

    except Exception as e:
        return {
            "flights": [],
            "error": f"Bağlantı hatası: {str(e)}",
            "remaining": opensky_limiter.remaining_requests,
            "from_cache": False,
        }


async def get_flight_track(icao24: str) -> dict:
    """Belirli uçağın son iz bilgilerini döndürür."""
    cache_key = f"track:{icao24}"
    cached = cache.get("opensky", cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    if not opensky_limiter.can_request():
        return {"error": "API limiti aşıldı", "track": []}

    opensky_limiter.wait_if_needed()

    try:
        token = await _get_access_token()
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{OPENSKY_BASE_URL}/tracks/all",
                params={"icao24": icao24, "time": 0},
                headers=headers,
            )

        opensky_limiter.record_request()

        if response.status_code == 200:
            data = response.json()
            result = {
                "icao24": data.get("icao24"),
                "callsign": (data.get("callsign") or "").strip(),
                "track": data.get("path", []),
                "from_cache": False,
            }
            cache.set("opensky", cache_key, result)
            return result

        return {"error": f"API hatası: {response.status_code}", "track": []}

    except Exception as e:
        return {"error": str(e), "track": []}
