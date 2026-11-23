"""
SkyOptimizer AI — Gerçek Uçuşla Doğrulama

Modelin kendi içinde tutarlı olması yetmez; gerçek bir uçuşun ADS-B iziyle
karşılaştırılması gerekir. Bu modül:

  1. OpenSky'den son 24 saatte `origin → destination` uçmuş gerçek bir
     uçuşu bulur (varış listesi üzerinden, anonim erişime açık).
  2. O uçuşun izini (`/tracks/all`) çeker ve uçağın gerçek tipini
     hexdb.io'dan alır.
  3. İzi aynı fizik motoruyla değerlendirir: gerçek mesafe, irtifa
     profili, süre ve model tabanlı yakıt tahmini.
  4. Aynı rota için optimizasyonu çalıştırır ve "bu uçak gerçekten böyle
     uçtu; optimizasyon ne kazandırırdı" karşılaştırmasını üretir.

Dürüstlük notları:
  • İzdeki yer hızı TAS'e çevrilmez (rüzgâr bilinmiyor) → yakıt tahmini
    ±%3 bandında.
  • Gerçek uçuş, kısıtlı hava sahası / ATC yönlendirmesi / yakıt ikmali
    gibi nedenlerle optimumdan sapabilir; bu bir model hatası değildir.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from optimization.performance import CI_DEFAULT, get_performance
from services.adsb_service import find_recent_flight, get_flight_track
from services.aircraft_service import get_aircraft
from services.route_planner import plan_route
from utils.geo import haversine_nm


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(
            timespec="seconds"
        )
    except (ValueError, OSError, OverflowError):
        return None


async def validate_route(
    origin: str,
    destination: str,
    aircraft_type: Optional[str] = None,
    cost_index: float = CI_DEFAULT,
    weights: Optional[dict] = None,
    hours: int = 12,
) -> dict:
    """
    Son N saatteki gerçek bir uçuşla modeli karşılaştır.

    Returns:
        {
          "available": bool, "reason": str|None,
          "flight": {...}, "actual": {...}, "planned": {...},
          "comparison": {...}
        }
    """
    found = await find_recent_flight(origin, destination, hours)
    if not found.get("available"):
        reason = found.get("reason", "Uygun uçuş bulunamadı")
        if "403" in str(reason):
            reason = (
                "OpenSky geçmiş uçuşlar için kimlik doğrulama istedi. "
                "Anonim erişim son 12 saati kapsar; daha eski uçuşlar için "
                "credentials.json içine geçerli clientId/clientSecret ekleyin."
            )
        return {
            "available": False,
            "reason": reason,
            "origin": origin.upper(),
            "destination": destination.upper(),
        }

    flight = found["flight"]
    icao24 = flight.get("icao24")
    callsign = flight.get("callsign")

    track_result, meta = await _track_and_meta(icao24, callsign, flight.get("last_seen"))
    track = track_result.get("track") or []
    if len(track) < 5:
        return {
            "available": False,
            "reason": (
                "Uçuş bulundu ancak iz verisi alınamadı. OpenSky izleri "
                "yalnızca uçuş sona erdikten sonra tam olarak erişilebilir."
            ),
            "flight": flight,
            "origin": origin.upper(),
            "destination": destination.upper(),
        }

    # Uçağın gerçek tipi (hexdb); yoksa kullanıcı seçimi
    actual_type = (meta or {}).get("type_code") or aircraft_type or "B738"
    perf = get_performance(actual_type)

    actual = perf.evaluate_track(track, cost_index=cost_index)
    if actual is None:
        return {
            "available": False,
            "reason": "İz değerlendirilemedi (yetersiz veri).",
            "flight": flight,
        }

    # Uçuşun kendi zamanındaki rüzgârla plan (geçmişe izin ver)
    departure_iso = _iso(flight.get("first_seen"))
    planned = await plan_route(
        origin, destination,
        aircraft_type=actual_type,
        weights=weights,
        cost_index=cost_index,
        departure_time=departure_iso,
        with_weather=False,
        allow_past=True,
    )

    if "error" in planned:
        return {
            "available": False,
            "reason": planned["error"],
            "flight": flight,
        }

    optimized = planned["optimized_route"]
    standard = planned["standard_route"]

    comparison = _compare(actual, optimized, standard)

    return {
        "available": True,
        "method": (
            "Gerçek ADS-B izi aynı fizik motoruyla değerlendirildi; "
            "optimizasyon aynı uçak tipi, aynı kalkış saati rüzgârı ve aynı "
            "ağırlıklarla yeniden hesaplandı."
        ),
        "origin": origin.upper(),
        "destination": destination.upper(),
        "flight": {
            **flight,
            "aircraft_type": actual_type,
            "registration": (meta or {}).get("registration"),
            "operator": (meta or {}).get("operator"),
            "model": (meta or {}).get("model"),
            "track_points": len(track),
            "first_seen_utc": departure_iso,
            "last_seen_utc": _iso(flight.get("last_seen")),
        },
        "actual": actual,
        "optimized": {
            "distance_nm": optimized["total_distance_nm"],
            "fuel_kg": optimized["estimated_fuel_kg"],
            "time_min": optimized["estimated_time_min"],
            "co2_kg": optimized["co2_emission_kg"],
            "cruise_altitude_ft": optimized["cruise_altitude_ft"],
        },
        "standard": {
            "distance_nm": standard["total_distance_nm"],
            "fuel_kg": standard["estimated_fuel_kg"],
            "time_min": standard["estimated_time_min"],
            "co2_kg": standard["co2_emission_kg"],
            "cruise_altitude_ft": standard["cruise_altitude_ft"],
        },
        "comparison": comparison,
        "wind_info": planned.get("wind_info"),
        "departure_time": planned.get("departure_time"),
        "caveats": [
            "İz yer hızı TAS kabul edilir; rüzgâr nedeniyle yakıt tahmini ±%3 sapabilir.",
            "Gerçek uçuş ATC yönlendirmesi, kısıtlı saha veya yakıt ikmali nedeniyle optimumdan sapabilir.",
            "Gerçek uçuşun kalkış ağırlığı bilinmez; rota mesafesinden tahmin edilir.",
        ],
    }


async def _track_and_meta(icao24: Optional[str], callsign: Optional[str], last_seen):
    """İz ve uçak kimliğini paralel çek."""
    import asyncio

    if not icao24:
        return {"track": []}, None
    track_task = get_flight_track(icao24, last_seen)
    meta_task = get_aircraft(icao24, callsign=callsign, include_route=True)
    track_result, meta = await asyncio.gather(
        track_task, meta_task, return_exceptions=True
    )
    if isinstance(track_result, Exception):
        track_result = {"track": [], "error": str(track_result)}
    if isinstance(meta, Exception):
        meta = None
    return track_result, meta


def _compare(actual: dict, optimized: dict, standard: dict) -> dict:
    """Gerçek uçuş vs optimize rota karşılaştırması."""
    actual_fuel = actual.get("fuel_kg") or 0.0
    actual_time = actual.get("time_min") or 0.0
    actual_dist = actual.get("distance_nm") or 0.0

    opt_fuel = optimized.get("estimated_fuel_kg") or 0.0
    opt_time = optimized.get("estimated_time_min") or 0.0
    opt_dist = optimized.get("total_distance_nm") or 0.0

    fuel_saved = actual_fuel - opt_fuel
    time_saved = actual_time - opt_time

    return {
        "fuel_saved_vs_actual_kg": round(fuel_saved, 1),
        "fuel_saved_vs_actual_percent": round(
            fuel_saved / actual_fuel * 100 if actual_fuel else 0.0, 2
        ),
        "time_saved_vs_actual_min": round(time_saved, 1),
        "time_saved_vs_actual_percent": round(
            time_saved / actual_time * 100 if actual_time else 0.0, 2
        ),
        "co2_saved_vs_actual_kg": round(fuel_saved * 3.16, 1),
        "distance_delta_vs_actual_nm": round(actual_dist - opt_dist, 1),
        "actual_longer_than_optimized": actual_dist > opt_dist,
        # Gerçek uçuşun kendi rotası ne kadar "dolambaçlı"ydı?
        "actual_vs_shortest_extra_nm": round(actual_dist - opt_dist, 1),
        "model_time_delta_min": round(actual_time - opt_time, 1),
        "optimized_is_better": fuel_saved > 0,
    }


def great_circle_distance(origin_icao: str, destination_icao: str) -> Optional[float]:
    """Yardımcı: iki ICAO arası great-circle mesafe (NM)."""
    from services.airport_service import get_airport

    a = get_airport(origin_icao)
    b = get_airport(destination_icao)
    if not a or not b:
        return None
    return haversine_nm(
        a["latitude"], a["longitude"], b["latitude"], b["longitude"]
    )
