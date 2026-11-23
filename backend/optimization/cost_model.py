"""
SkyOptimizer AI — Maliyet Modeli

A* kenar maliyetleri ve API tahminleri için ince bir katman. Fizik
`optimization.performance.AircraftPerformance` içindedir; bu sınıf onu
A*'ın beklediği segment arayüzüne uyarlar.

Varsayılanlar artık sabit değil:
  • cruise hızı        → cost index'ten türetilir (CI 0-200)
  • cruise irtifası    → katman taramasından gelir (FL300/340/390)
  • kütle              → rota mesafesinden türetilir, yakıtla azalır
"""

import math
from typing import Optional

from optimization.performance import (
    AircraftPerformance,
    CI_DEFAULT,
    FUEL_PRICE_USD_PER_KG,
    METHOD_NOTES,
    get_performance,
)
from utils.geo import fuel_to_co2, wind_components


class CostModel:
    """
    Segment bazlı maliyet hesaplayıcı.

    `calculate_segment_cost` rüzgârlı yakıt/süre/CO₂ üretir; sonuçlar
    YUVARLANMAZ (yuvarlama A* maliyet fonksiyonuna gürültü ekliyordu).
    """

    def __init__(
        self,
        aircraft_type: str = "B738",
        cost_index: float = CI_DEFAULT,
        cruise_altitude_ft: Optional[float] = None,
        mass_kg: Optional[float] = None,
    ):
        self.aircraft_type = aircraft_type
        self.cost_index = max(0.0, min(200.0, float(cost_index)))
        self.perf: AircraftPerformance = get_performance(aircraft_type)
        self.cruise_altitude_ft = cruise_altitude_ft or self.perf.nominal_alt_ft
        self.cruise_mass_kg = mass_kg or self.perf.initial_mass(1000)
        self.cruise_speed_kts = self.perf.tas_for_ci(
            self.cost_index, self.cruise_altitude_ft
        )

    # ═══════════════════════════════════════════════════════════════
    #  Segment maliyeti
    # ═══════════════════════════════════════════════════════════════

    def calculate_segment_cost(
        self,
        distance_nm: float,
        wind_speed_kts: float = 0,
        wind_direction: float = 0,
        aircraft_heading: float = 0,
        altitude_ft: Optional[float] = None,
        cost_index: Optional[float] = None,
        mass_kg: Optional[float] = None,
    ) -> dict:
        """
        Tek bir rota segmenti için tüm maliyetleri hesaplar.

        Returns:
            {fuel_kg, time_min, co2_kg, ground_speed_kts, headwind_kts,
             crosswind_kts, distance_nm, tas_kts, mach}
        """
        alt = altitude_ft if altitude_ft is not None else self.cruise_altitude_ft
        ci = self.cost_index if cost_index is None else float(cost_index)
        mass = mass_kg if mass_kg is not None else self.cruise_mass_kg

        headwind, crosswind = wind_components(
            wind_speed_kts, wind_direction, aircraft_heading
        )

        tas = self.perf.tas_for_ci(ci, alt)
        ground_speed = max(tas - headwind, 120.0)
        time_min = distance_nm / ground_speed * 60.0
        ff = self.perf.fuel_flow_kg_s(mass, tas, alt)
        fuel_kg = ff * time_min * 60.0

        return {
            "fuel_kg": fuel_kg,
            "time_min": time_min,
            "co2_kg": fuel_to_co2(fuel_kg),
            "ground_speed_kts": ground_speed,
            "headwind_kts": headwind,
            "crosswind_kts": crosswind,
            "distance_nm": distance_nm,
            "tas_kts": tas,
            "mach": self.perf.mach_for_ci(ci),
        }

    # ═══════════════════════════════════════════════════════════════
    #  Kompozit maliyet
    # ═══════════════════════════════════════════════════════════════

    def composite_cost(
        self,
        fuel_kg: float,
        time_min: float,
        co2_kg: float,
        weights: Optional[dict] = None,
        reference: Optional[dict] = None,
    ) -> float:
        """
        Ağırlıklı kompozit maliyet — A*'ta kenar ağırlığı.

        `reference`, referans rotanın (standart = en kısa rota) TOPLAM
        maliyetleridir: {"fuel_kg", "time_min", "co2_kg"}. Normalizasyon
        referansa göre yapıldığı için ağırlıklar karşılaştırılabilir ve
        standart rotanın kompozit maliyeti tam 1.0 olur.
        """
        w = self._normalize_weights(weights)
        ref = reference or {}

        ref_fuel = ref.get("fuel_kg") or 1.0
        ref_time = ref.get("time_min") or 1.0
        ref_co2 = ref.get("co2_kg") or 1.0

        return (
            w["fuel"] * (fuel_kg / ref_fuel)
            + w["time"] * (time_min / ref_time)
            + w["co2"] * (co2_kg / ref_co2)
        )

    @staticmethod
    def _normalize_weights(weights: Optional[dict]) -> dict:
        """Ağırlıkları toplamı 1 olacak şekilde doğrula/normalize et."""
        default = {"fuel": 0.4, "time": 0.35, "co2": 0.25}
        w = {k: float((weights or {}).get(k, default[k])) for k in default}
        total = sum(w.values())
        if total <= 0:
            return dict(default)
        return {k: v / total for k, v in w.items()}

    # ═══════════════════════════════════════════════════════════════
    #  Geriye dönük uyumluluk
    # ═══════════════════════════════════════════════════════════════

    def estimate_total_route(
        self,
        total_distance_nm: float,
        wind_speed_kts: float = 0,
        wind_direction: float = 0,
        aircraft_heading: float = 0,
    ) -> dict:
        """Toplam rota maliyet tahmini (tek segment olarak)."""
        return self.calculate_segment_cost(
            distance_nm=total_distance_nm,
            wind_speed_kts=wind_speed_kts,
            wind_direction=wind_direction,
            aircraft_heading=aircraft_heading,
        )

    @staticmethod
    def method_notes() -> dict:
        return METHOD_NOTES
