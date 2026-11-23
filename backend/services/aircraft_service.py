"""
SkyOptimizer AI — Uçak Kimliği Servisi (hexdb.io)

OpenSky'nin `/metadata/aircraft` uç noktası kaldırıldığı (HTTP 410) için
uçak tipi/operatör bilgisi hexdb.io'dan alınır. Anahtar gerekmez.

  GET https://hexdb.io/api/v1/aircraft/{icao24}
      → typecode, model, üretici, kayıt, operatör
  GET https://hexdb.io/api/v1/route/icao/{callsign}
      → "LTAI-LTFM" biçiminde rota (çağrı işareti bazlı, eski olabilir)

Sonuçlar 24 saat cache'lenir. Tüm çağrılar isteğe bağlıdır: servis
erişilemezse arayüz yalnızca ADS-B'den gelen hız/irtifa sınıfını gösterir.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional

import httpx

from services.cache_manager import cache

HEXDB_BASE = "https://hexdb.io/api/v1"
_TIMEOUT = 12.0

# ADS-B emitter category (OpenSky extended=1, state[17]) → sınıf
EMITTER_CATEGORY = {
    1: "unknown",
    2: "light",
    3: "light",
    4: "narrow",
    5: "heavy",
    6: "heavy",
    7: "fighter",
    8: "rotor",
    9: "light",
    10: "light",
    11: "light",
    12: "light",
    13: "light",
    14: "light",
    15: "light",
    16: "light",
    17: "light",
    18: "turboprop",
    19: "turboprop",
    20: "turboprop",
}

# ICAO tip kodu önekleri → sınıf
_TYPE_PREFIXES = (
    (("A388", "A389", "B748", "B744", "B742", "B743"), "heavy"),
    (("A332", "A333", "A338", "A339", "A342", "A343", "A345", "A346",
      "A350", "A351", "A358", "A359"), "heavy"),
    (("B762", "B763", "B764", "B772", "B773", "B77W", "B778", "B779",
      "B788", "B789", "B78X", "MD11", "IL96", "A300", "A310"), "heavy"),
    (("A318", "A319", "A320", "A321", "A20N", "A21N", "A32N", "A32S"), "narrow"),
    (("B731", "B732", "B733", "B734", "B735", "B736", "B737", "B738",
      "B739", "B37M", "B38M", "B39M", "B3XM", "B752", "B753"), "narrow"),
    (("MD81", "MD82", "MD83", "MD87", "MD88", "MD90", "BCS1", "BCS3"), "narrow"),
    (("E170", "E175", "E190", "E195", "E75L", "E75S", "E290", "E295"), "regional"),
    (("CRJ1", "CRJ2", "CRJ7", "CRJ9", "CRJX"), "regional"),
    (("AT4", "AT5", "AT7", "AT8", "DH8", "DHC", "SF34", "SAAB", "SB20",
      "J32", "J41", "BE20", "B190", "C208", "PC12", "TBM"), "turboprop"),
    (("R22", "R44", "R66", "B06", "B407", "B429", "EC", "AS3", "AS5",
      "AW13", "AW16", "H60", "H64", "UH1", "S76", "S92"), "rotor"),
    (("F16", "F15", "F18", "F22", "F35", "T38", "T6", "PC21", "L39",
      "M346", "EUFI", "RFAL", "GR4", "HAWK"), "fighter"),
    # Hafif uçaklar askerî kodlardan ÖNCE gelir: "C172" ile "C17"
    # (Globemaster) ve "B190" ile "B1" çakışmasın.
    (("C150", "C152", "C172", "C182", "C206", "C210", "C25", "C500",
      "C510", "C525", "C550", "C560", "C650", "C680", "C750", "B200",
      "B300", "P28", "PA2", "PA3", "PA4", "SR2", "DA4", "DA6", "M20",
      "BE1", "BE3", "BE5", "BE9"), "light"),
    (("C130", "C17", "C5M", "C5A", "C141", "C160", "A400", "K35", "KC46",
      "E3", "P8", "B52", "B1", "B2"), "military"),
)


def classify_by_type(type_code: Optional[str]) -> Optional[str]:
    """ICAO tip kodundan uçak sınıfı."""
    if not type_code:
        return None
    code = str(type_code).upper().strip()
    for prefixes, category in _TYPE_PREFIXES:
        for prefix in prefixes:
            if code.startswith(prefix):
                return category
    return "unknown"


def classify_flight(
    speed_ms: Optional[float],
    altitude_m: Optional[float],
    emitter_category: Optional[int] = None,
    type_code: Optional[str] = None,
) -> str:
    """
    Uçuşu ikon sınıfına ayır.

    Öncelik: gerçek tip kodu > ADS-B emitter category > hız/irtifa sezgisi.
    Hız/irtifa sezgisi yalnızca "unknown" durumunda kullanılır ve arayüzde
    "tahmini sınıf" olarak etiketlenir.
    """
    by_type = classify_by_type(type_code)
    if by_type and by_type != "unknown":
        return by_type

    if emitter_category:
        mapped = EMITTER_CATEGORY.get(int(emitter_category))
        if mapped and mapped != "unknown":
            return mapped

    speed_kts = (speed_ms or 0) * 1.943844
    alt_ft = (altitude_m or 0) * 3.28084

    # Alçak irtifada jet ile turboprop ayrımı hızdan yapılamaz (yaklaşma
    # 180-250 kt). Bu yüzden turboprop yalnızca cruise bandında varsayılır;
    # yanlış sınıflandırmak yerine "narrow" varsayılanı korunur.
    if alt_ft < 3500 and speed_kts < 130:
        return "light"
    if alt_ft < 10000:
        return "light" if speed_kts < 150 else "narrow"
    if 12000 < alt_ft < 30000 and speed_kts < 310:
        return "turboprop"
    return "narrow"


async def _get_json(url: str) -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url)
        if response.status_code == 200:
            data = response.json()
            return data if isinstance(data, dict) else None
    except Exception:
        return None
    return None


def _normalize_icao(icao24: str) -> str:
    return str(icao24 or "").strip().lower()


async def get_aircraft(
    icao24: str,
    callsign: Optional[str] = None,
    include_route: bool = True,
) -> dict:
    """
    Uçak kimliği + (varsa) rota bilgisi.

    Returns:
        {"icao24", "registration", "type_code", "model", "manufacturer",
         "operator", "category", "route": {"origin","destination"} | None,
         "available": bool, "source": "hexdb"}
    """
    key = _normalize_icao(icao24)
    if not key:
        return {"available": False, "reason": "icao24 gerekli"}

    cache_key = f"ac:{key}"
    cached = cache.get("aircraft", cache_key)
    if cached is not None:
        result = dict(cached)
    else:
        data = await _get_json(f"{HEXDB_BASE}/aircraft/{key}")
        if not data:
            result = {
                "icao24": key, "available": False,
                "reason": "hexdb.io kaydı bulunamadı",
            }
        else:
            type_code = (data.get("ICAOTypeCode") or "").strip().upper() or None
            result = {
                "icao24": key,
                "available": True,
                "registration": (data.get("Registration") or "").strip() or None,
                "type_code": type_code,
                "model": (data.get("Type") or "").strip() or None,
                "manufacturer": (data.get("Manufacturer") or "").strip() or None,
                "operator": (data.get("RegisteredOwners") or "").strip() or None,
                "category": classify_by_type(type_code) or "unknown",
                "source": "hexdb",
            }
        cache.set("aircraft", cache_key, result)

    result = dict(result)
    if include_route and callsign:
        route = await get_route(callsign)
        result["route"] = route

    return result


async def get_route(callsign: str) -> Optional[dict]:
    """Çağrı işaretine göre rota (hexdb). Örn. {"origin": "LTAI", "destination": "LTFM"}"""
    cs = str(callsign or "").strip().upper()
    if not cs:
        return None

    cache_key = f"route:{cs}"
    cached = cache.get("aircraft", cache_key)
    if cached is not None:
        return cached

    data = await _get_json(f"{HEXDB_BASE}/route/icao/{cs}")
    route = None
    if data:
        raw = str(data.get("route") or "").strip().upper()
        parts = [p.strip() for p in raw.split("-") if p.strip()]
        if len(parts) >= 2 and len(parts[0]) == 4 and len(parts[-1]) == 4:
            route = {
                "origin": parts[0],
                "destination": parts[-1],
                "raw": raw,
                "updated_at": data.get("updatetime"),
                "source": "hexdb",
            }
    cache.set("aircraft", cache_key, route)
    return route


async def enrich_flights(flights: Iterable[dict], limit: int = 40) -> dict:
    """
    Uçuş listesine gerçek tip kodu ekle.

    Cache'te olan tüm uçaklar anında döner; cache'te olmayanlardan en fazla
    `limit` tanesi hexdb.io'dan çekilir. Böylece her trafik yenilemesinde
    yeni bir grup uçak zenginleşir ve ikonlar zamanla gerçek tipe döner.
    """
    flights = [f for f in flights if f.get("icao24")]
    enriched: dict = {}
    pending: list = []

    for flight in flights:
        cached = cache.get("aircraft", f"ac:{_normalize_icao(flight['icao24'])}")
        if cached is not None:
            if cached.get("available"):
                enriched[flight["icao24"]] = {
                    "type_code": cached.get("type_code"),
                    "operator": cached.get("operator"),
                    "category": cached.get("category"),
                }
        elif len(pending) < max(0, int(limit)):
            pending.append(flight)

    if not pending:
        return enriched

    semaphore = asyncio.Semaphore(12)

    async def fetch(flight):
        async with semaphore:
            meta = await get_aircraft(flight["icao24"], include_route=False)
            return flight["icao24"], meta

    results = await asyncio.gather(*(fetch(f) for f in pending), return_exceptions=True)
    for entry in results:
        if isinstance(entry, Exception):
            continue
        icao, meta = entry
        if meta.get("available"):
            enriched[icao] = {
                "type_code": meta.get("type_code"),
                "operator": meta.get("operator"),
                "category": meta.get("category"),
            }
    return enriched
