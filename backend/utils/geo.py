"""
SkyOptimizer AI — Coğrafi Hesaplama Araçları
Haversine mesafe, great-circle, rüzgâr bileşeni hesaplamaları.
"""

import math
from typing import Tuple


# Dünya yarıçapı (deniz mili cinsinden)
EARTH_RADIUS_NM = 3440.065

# Dünya yarıçapı (kilometre)
EARTH_RADIUS_KM = 6371.0


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    İki koordinat arası mesafeyi deniz mili (NM) cinsinden hesaplar.
    Haversine formülü kullanır.
    """
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_NM * c


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """İki koordinat arası mesafe (km)."""
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r

    a = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    İki nokta arası başlangıç yönünü (bearing) derece cinsinden hesaplar.
    0° = Kuzey, 90° = Doğu, 180° = Güney, 270° = Batı
    """
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    dlon = lon2_r - lon1_r

    x = math.sin(dlon) * math.cos(lat2_r)
    y = (math.cos(lat1_r) * math.sin(lat2_r) -
         math.sin(lat1_r) * math.cos(lat2_r) * math.cos(dlon))

    bearing = math.degrees(math.atan2(x, y))
    return (bearing + 360) % 360


def wind_components(
    wind_speed: float,
    wind_direction: float,
    aircraft_heading: float,
) -> Tuple[float, float]:
    """
    Rüzgâr bileşenlerini hesaplar.

    Args:
        wind_speed: Rüzgâr hızı (knots)
        wind_direction: Rüzgârın geldiği yön (derece, meteorolojik)
        aircraft_heading: Uçağın yönü (derece)

    Returns:
        (headwind, crosswind) tuple:
        - headwind > 0 → karşı rüzgâr (yakıt artırır)
        - headwind < 0 → kuyruk rüzgârı (yakıt azaltır, avantaj!)
        - crosswind: mutlak çapraz rüzgâr bileşeni
    """
    # Rüzgâr açısı ile uçak yönü arasındaki fark
    angle_diff = math.radians(wind_direction - aircraft_heading)

    headwind = wind_speed * math.cos(angle_diff)
    crosswind = abs(wind_speed * math.sin(angle_diff))

    return headwind, crosswind


def great_circle_waypoints(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
    num_points: int = 10,
) -> list:
    """
    İki nokta arası great-circle (büyük çember) rotası üzerinde
    ara noktalar üretir. Harita üzerinde eğri çizgi çizmek için kullanılır.

    Returns:
        [(lat, lon), ...] listesi
    """
    lat1_r, lon1_r = math.radians(lat1), math.radians(lon1)
    lat2_r, lon2_r = math.radians(lat2), math.radians(lon2)

    d = 2 * math.asin(math.sqrt(
        math.sin((lat2_r - lat1_r) / 2) ** 2 +
        math.cos(lat1_r) * math.cos(lat2_r) *
        math.sin((lon2_r - lon1_r) / 2) ** 2
    ))

    if d < 1e-10:
        return [(lat1, lon1)]

    waypoints = []
    for i in range(num_points + 1):
        f = i / num_points
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)

        x = a * math.cos(lat1_r) * math.cos(lon1_r) + b * math.cos(lat2_r) * math.cos(lon2_r)
        y = a * math.cos(lat1_r) * math.sin(lon1_r) + b * math.cos(lat2_r) * math.sin(lon2_r)
        z = a * math.sin(lat1_r) + b * math.sin(lat2_r)

        lat = math.degrees(math.atan2(z, math.sqrt(x ** 2 + y ** 2)))
        lon = math.degrees(math.atan2(y, x))
        waypoints.append((lat, lon))

    return waypoints


def estimate_flight_time_min(
    distance_nm: float,
    cruise_speed_kts: float = 460,
    headwind_kts: float = 0,
) -> float:
    """
    Tahmini uçuş süresini dakika cinsinden hesaplar.
    Ground speed = TAS - headwind (basitleştirilmiş).
    """
    ground_speed = max(cruise_speed_kts - headwind_kts, 100)  # minimum 100 kts
    return (distance_nm / ground_speed) * 60


def nm_to_km(nm: float) -> float:
    """Deniz mili → Kilometre."""
    return nm * 1.852


def km_to_nm(km: float) -> float:
    """Kilometre → Deniz mili."""
    return km / 1.852


def ft_to_m(ft: float) -> float:
    """Feet → Metre."""
    return ft * 0.3048


def m_to_ft(m: float) -> float:
    """Metre → Feet."""
    return m / 0.3048


def kg_to_lbs(kg: float) -> float:
    """Kilogram → Pound."""
    return kg * 2.20462


def fuel_to_co2(fuel_kg: float) -> float:
    """
    Yakıt tüketiminden CO₂ emisyonu hesaplama.
    Jet-A1 yakıtı: 1 kg yakıt ≈ 3.16 kg CO₂
    """
    return fuel_kg * 3.16
