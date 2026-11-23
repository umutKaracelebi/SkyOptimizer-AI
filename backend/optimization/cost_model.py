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

        # Cruise yakıt akışı sabittir (kütle, TAS ve irtifa sabit varsayılıyor).
        # Binlerce kenar için OpenAP'ı tekrar tekrar çağırmak yerine bir kez
        # hesaplayıp saklıyoruz — rota optimizasyonunda ~50x hızlanma.
        self._ff_kg_per_s: Optional[float] = None

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

        # NOT: Değerler YUVARLANMAZ. Yuvarlama, A*'ın maliyet fonksiyonuna
        # yapay gürültü ekliyordu (rüzgârsız rotada bile "tasarruf" çıkmasına
        # yol açıyordu). Yuvarlama yalnızca sunum katmanında yapılır.
        return {
            "fuel_kg": fuel_kg,
            "time_min": time_min,
            "co2_kg": co2_kg,
            "ground_speed_kts": ground_speed,
            "headwind_kts": headwind,
            "crosswind_kts": crosswind,
            "distance_nm": distance_nm,
        }

    def composite_cost(
        self,
        fuel_kg: float,
        time_min: float,
        co2_kg: float,
        weights: Optional[dict] = None,
        reference: Optional[dict] = None,
    ) -> float:
        """
        Ağırlıklı kompozit maliyet — A*'ta kenar ağırlığı olarak kullanılır.

        `reference`, referans rotanın (standart = en kısa rota) TOPLAM
        maliyetleridir: {"fuel_kg", "time_min", "co2_kg"}.

        Normalizasyon referansa göre yapıldığı için ağırlıklar gerçekten
        karşılaştırılabilir: yakıt ağırlığı 0.40 ise, rota yakıtının
        referansın %90'ı olması toplam maliyete 0.40 × 0.90 olarak yansır.
        Böylece referans rotanın kompozit maliyeti tam olarak 1.0'dır ve
        optimize rota her zaman ≤ 1.0 bulur.

        Önceden sabit referanslar (100 kg / 10 dk / 300 kg CO₂) kullanılıyordu;
        bu yüzden arayüzdeki 40/35/25 kaydırıcıları beklenen etkiyi
        yaratmıyordu.
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

    def _fuel_flow_kg_per_s(self, altitude_ft: float) -> Optional[float]:
        """OpenAP cruise yakıt akışı (kg/s) — bir kez hesaplanıp cache'lenir."""
        if self._ff_kg_per_s is not None:
            return self._ff_kg_per_s

        try:
            altitude_m = altitude_ft * 0.3048
            tas_ms = self.cruise_speed_kts * 0.5144
            ff = self.fuelflow.enroute(
                mass=self.cruise_mass_kg,
                tas=tas_ms,
                alt=altitude_m,
            )
            self._ff_kg_per_s = float(ff)
            return self._ff_kg_per_s
        except Exception:
            return None

    def _openap_fuel(self, distance_nm: float, altitude_ft: float, time_hours: float) -> float:
        """OpenAP ile yakıt hesabı."""
        ff = self._fuel_flow_kg_per_s(altitude_ft)
        if ff is None:
            return self._simple_fuel(distance_nm, time_hours)
        fuel = ff * time_hours * 3600  # kg/s → kg
        return max(fuel, 0)

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
