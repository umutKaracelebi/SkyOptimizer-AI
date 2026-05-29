"""
SkyOptimizer AI — Maliyet Modeli
OpenAP kütüphanesi ile gerçekçi yakıt tüketimi ve CO₂ emisyon hesaplaması.
Rüzgâr etkisini dahil eden kompozit maliyet fonksiyonu.
"""

import math
from typing import Optional, Tuple

from utils.geo import wind_components, fuel_to_co2

# OpenAP'ı yüklemeye çalış, yoksa basit modele geç
try:
    from openap import FuelFlow, Emission, prop
    OPENAP_AVAILABLE = True
except ImportError:
    OPENAP_AVAILABLE = False
    print("[UYARI] OpenAP yüklenemedi, basit yakıt modeli kullanılacak.")


class CostModel:
    """
    Uçuş maliyet hesaplama modeli.
    OpenAP varsa gerçekçi yakıt modeli, yoksa basit formül kullanır.
    """

    def __init__(self, aircraft_type: str = "B738"):
        self.aircraft_type = aircraft_type

        if OPENAP_AVAILABLE:
            try:
                self.fuelflow = FuelFlow(ac=aircraft_type)
                self.emission = Emission(ac=aircraft_type)
                self.ac_props = prop.aircraft(aircraft_type)
                self.use_openap = True
            except Exception as e:
                print(f"[UYARI] OpenAP {aircraft_type} yüklenemedi: {e}")
                self.use_openap = False
        else:
            self.use_openap = False

        # Varsayılan performans parametreleri
        self.cruise_speed_kts = 460   # TAS (knots)
        self.cruise_altitude_ft = 35000
        self.cruise_mass_kg = 65000   # Ortalama kütle

    def calculate_segment_cost(
        self,
        distance_nm: float,
        wind_speed_kts: float = 0,
        wind_direction: float = 0,
        aircraft_heading: float = 0,
        altitude_ft: Optional[float] = None,
    ) -> dict:
        """
        Tek bir rota segmenti için tüm maliyetleri hesaplar.

        Returns:
            {fuel_kg, time_min, co2_kg, ground_speed_kts, headwind_kts, composite_cost}
        """
        alt = altitude_ft or self.cruise_altitude_ft

        # Rüzgâr bileşenleri
        headwind, crosswind = wind_components(
            wind_speed_kts, wind_direction, aircraft_heading
        )

        # Ground speed = TAS - headwind (basitleştirilmiş)
        ground_speed = max(self.cruise_speed_kts - headwind, 150)

        # Uçuş süresi
        time_hours = distance_nm / ground_speed
        time_min = time_hours * 60

        # Yakıt hesabı
        if self.use_openap:
            fuel_kg = self._openap_fuel(distance_nm, alt, time_hours)
        else:
            fuel_kg = self._simple_fuel(distance_nm, time_hours)

        # Rüzgâr etkisi düzeltmesi
        # Karşı rüzgârda daha fazla yakıt, kuyruk rüzgârında daha az
        wind_factor = 1.0 + (headwind / self.cruise_speed_kts) * 0.15
        fuel_kg *= wind_factor

        # CO₂ emisyonu
        co2_kg = fuel_to_co2(fuel_kg)

        return {
            "fuel_kg": round(fuel_kg, 1),
            "time_min": round(time_min, 1),
            "co2_kg": round(co2_kg, 1),
            "ground_speed_kts": round(ground_speed, 1),
            "headwind_kts": round(headwind, 1),
            "crosswind_kts": round(crosswind, 1),
            "distance_nm": round(distance_nm, 1),
        }

    def composite_cost(
        self,
        fuel_kg: float,
        time_min: float,
        co2_kg: float,
        weights: Optional[dict] = None,
    ) -> float:
        """
        Ağırlıklı kompozit maliyet hesaplama.
        A* algoritmasında kenar ağırlığı olarak kullanılır.
        """
        w = weights or {"fuel": 0.4, "time": 0.35, "co2": 0.25}

        # Normalize edilmiş maliyetler
        norm_fuel = fuel_kg / 100       # ~100 kg/segment referans
        norm_time = time_min / 10       # ~10 dk/segment referans
        norm_co2 = co2_kg / 300         # ~300 kg CO₂/segment referans

        return (
            w.get("fuel", 0.4) * norm_fuel +
            w.get("time", 0.35) * norm_time +
            w.get("co2", 0.25) * norm_co2
        )

    def _openap_fuel(self, distance_nm: float, altitude_ft: float, time_hours: float) -> float:
        """OpenAP ile yakıt hesabı."""
        try:
            distance_m = distance_nm * 1852
            altitude_m = altitude_ft * 0.3048
            tas_ms = self.cruise_speed_kts * 0.5144

            # Cruise fuel flow (kg/s)
            ff = self.fuelflow.enroute(
                mass=self.cruise_mass_kg,
                tas=tas_ms,
                alt=altitude_m,
            )
            fuel = ff * time_hours * 3600  # kg/s → kg
            return max(fuel, 0)
        except Exception:
            return self._simple_fuel(distance_nm, time_hours)

    def _simple_fuel(self, distance_nm: float, time_hours: float) -> float:
        """Basit yakıt modeli (OpenAP yoksa fallback)."""
        # B738 cruise: ~2600 kg/saat
        fuel_rate_kg_per_hour = 2600
        return fuel_rate_kg_per_hour * time_hours

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
