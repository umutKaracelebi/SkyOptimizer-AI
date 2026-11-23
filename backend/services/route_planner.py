"""
SkyOptimizer AI — Rota Planlayıcı

Rüzgâr örnekleme + optimizasyon + hava durumu + kayıt işlemlerini tek
yerde toplar. `/api/optimize` ve gerçek uçuş doğrulama aynı boru hattını
kullanır; böylece iki uç nokta asla farklı varsayımlarla hesaplamaz.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timezone
from typing import Optional

from optimization.astar import DEFAULT_WEIGHTS, find_optimal_route
from optimization.performance import CI_DEFAULT, METHOD_NOTES, get_performance
from services.airport_service import get_airport
from services.stats_store import record_optimization
from services.weather_service import get_metar, get_taf
from services.wind_service import (
    build_sample_points,
    build_wind_map,
    get_winds_multi_level,
    sampling_plan,
)
from utils.geo import haversine_nm


def resolve_departure_time(
    departure_time: Optional[str], allow_past: bool = False,
) -> dict:
    """
    Kullanıcının seçtiği kalkış zamanını normalize et.

    Geçmiş zamanlar "şimdi"ye, 7 günden uzak zamanlar pencere sonuna
    kırpılır; kırpma arayüzde açıkça gösterilir.

    `allow_past=True` yalnızca gerçek uçuş doğrulamasında kullanılır:
    o uçuşun kendi zamanındaki GFS rüzgârıyla karşılaştırma yapılır.
    """
    now = datetime.now(timezone.utc)
    raw = departure_time
    dt = now
    note = None
    if departure_time:
        try:
            text = str(departure_time).strip().replace("Z", "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            dt = parsed.astimezone(timezone.utc)
        except (TypeError, ValueError):
            dt = now
            note = "Kalkış zamanı okunamadı; şimdiki zaman kullanıldı."

    if not allow_past and dt < now.replace(minute=0, second=0, microsecond=0):
        dt = now
        note = "Geçmiş zaman istendi; tahmin için şimdiki GFS saatine dönüldü."
    elif (dt - now).days > 7:
        dt = now
        note = "7 günden uzak zaman istendi; GFS forecast penceresi aşıldı."

    return {
        "requested": raw,
        "resolved_utc": dt.replace(minute=0, second=0, microsecond=0)
        .isoformat().replace("+00:00", "Z"),
        "hours_ahead": round((dt - now).total_seconds() / 3600.0, 1),
        "note": note,
    }


async def _weather_card(icao: str) -> dict:
    metar, taf = await asyncio.gather(
        get_metar(icao), get_taf(icao), return_exceptions=True
    )
    return {
        "icao": icao,
        "metar": metar if isinstance(metar, dict) else {"error": str(metar)},
        "taf": taf if isinstance(taf, dict) else {"error": str(taf)},
    }


async def plan_route(
    origin_icao: str,
    destination_icao: str,
    aircraft_type: str = "B738",
    weights: Optional[dict] = None,
    cost_index: float = CI_DEFAULT,
    departure_time: Optional[str] = None,
    avoid_airspace: bool = True,
    wind_levels: Optional[dict] = None,
    with_weather: bool = True,
    record: bool = False,
    allow_past: bool = False,
) -> dict:
    """
    Tam bir rota planı üret.

    Args:
        wind_levels: Test/ileri kullanım için hazır rüzgâr haritaları
            ({level_mb: {(lat,lon): {"speed","dir"}}}). Verilmezse GFS'ten
            çekilir.
        record: Sonucu SQLite birikim deposuna yaz.
    """
    origin = get_airport(origin_icao)
    dest = get_airport(destination_icao)
    if not origin or not dest:
        return {"error": f"Havalimanı bulunamadı: {origin_icao if not origin else destination_icao}"}

    perf = get_performance(aircraft_type)
    distance = haversine_nm(
        origin["latitude"], origin["longitude"],
        dest["latitude"], dest["longitude"],
    )
    levels = [lv for lv, _ in perf.candidate_levels(distance)]
    timing = resolve_departure_time(departure_time, allow_past=allow_past)

    wind_source = "provided"
    if wind_levels is None:
        points = build_sample_points(
            origin["latitude"], origin["longitude"],
            dest["latitude"], dest["longitude"],
            distance,
        )
        fetched = await get_winds_multi_level(
            points, levels, timing["resolved_utc"]
        )
        wind_levels = {}
        for level_mb, winds in fetched.items():
            wind_levels[level_mb] = build_wind_map(points, winds)
        wind_source = "open-meteo-gfs"

    result = await find_optimal_route(
        origin_icao=origin_icao,
        destination_icao=destination_icao,
        aircraft_type=aircraft_type,
        weights=weights or DEFAULT_WEIGHTS,
        cost_index=cost_index,
        wind_levels=wind_levels,
        avoid_airspace=avoid_airspace,
    )
    if "error" in result:
        return result

    # ─── Rüzgâr özeti ─────────────────────────────────────────────
    all_speeds = []
    all_dirs = []
    for wind_map in wind_levels.values():
        for data in wind_map.values():
            speed = float(data.get("speed", 0) or 0)
            all_speeds.append(speed)
            if data.get("dir") is not None:
                all_dirs.append(float(data["dir"]))

    avg_speed = round(sum(all_speeds) / len(all_speeds), 1) if all_speeds else 0.0
    if all_dirs:
        sin_sum = sum(math.sin(math.radians(d)) for d in all_dirs)
        cos_sum = sum(math.cos(math.radians(d)) for d in all_dirs)
        avg_dir = round(math.degrees(math.atan2(sin_sum, cos_sum)) % 360, 0)
    else:
        avg_dir = 0.0

    plan = sampling_plan(distance)
    payload = {
        "origin": origin,
        "destination": dest,
        "aircraft_type": aircraft_type,
        "departure_time": timing,
        "wind_info": {
            "sample_points": sum(len(m) for m in wind_levels.values()),
            "positions_per_level": len(next(iter(wind_levels.values()), {})),
            "levels": sorted(wind_levels.keys()),
            "spacing_nm": plan["spacing_nm"],
            "corridor_offsets_nm": plan["offsets_nm"],
            "avg_speed_kts": avg_speed,
            "avg_direction_deg": avg_dir,
            "source": wind_source,
            "level_mb": 300,
        },
        "weather": {
            "origin": await _weather_card(origin_icao) if with_weather else None,
            "destination": await _weather_card(destination_icao) if with_weather else None,
        },
        "method_notes": METHOD_NOTES,
        **result,
    }

    if record:
        record_optimization(
            {
                "origin": origin,
                "destination": dest,
                "aircraft_type": aircraft_type,
                "savings": result.get("savings"),
                "standard_route": result.get("standard_route"),
                "optimized_route": result.get("optimized_route"),
                "aircraft_performance": result.get("aircraft_performance"),
            },
            departure_time=timing["resolved_utc"],
        )

    return payload
