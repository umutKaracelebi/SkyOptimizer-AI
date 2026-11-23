"""
SkyOptimizer AI — Uçak Performans Modeli (4B)

Bu modül rota optimizasyonunun fizik çekirdeğidir. OpenAP'ın uçak veritabanı
ve yakıt modeli üzerine dört ek boyut ekler:

  1. COST INDEX (CI)      — hız–yakıt takası. Havayolları CI ile "zaman
                            maliyeti / yakıt maliyeti" oranını seçer.
  2. TIRMANMA / ALÇALMA   — kısa rotalarda toplam yakıtın büyük kısmı bu
                            fazlarda yanar; cruise tek başına yetersizdir.
  3. KÜTLE AZALMASI       — yakıt yandıkça kütle düşer, yakıt akışı azalır.
  4. İRTİFA KATMANLARI    — FL300/340/390 rüzgârları ayrı ayrı değerlendirilir.

Model dürüstlük ilkesi: taban yakıt akışı OpenAP'tan gelir (ICAO emisyon
veritabanı + Gur vd. 2010 dalga sürüklemesi). OpenAP'ın hız duyarlılığı
M0.74–M0.82 bandında gerçek uçak davranışını yansıtmadığı için (modelde
spesifik menzil hızla sürekli artıyor) hız etkisi, yayınlanmış 737/A320
CI davranışına kalibre edilmiş bir üstel düzeltme ile uygulanır.
`METHOD_NOTES` alanı bu varsayımları API yanıtında açıkça belgeler.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, Optional

from utils.geo import fuel_to_co2

try:
    from openap import FuelFlow, prop
    import openap.mass as openap_mass
    OPENAP_AVAILABLE = True
except Exception:  # pragma: no cover - OpenAP kurulu değilse
    OPENAP_AVAILABLE = False


# ─── Sabitler ───────────────────────────────────────────────────────
KTS_TO_MS = 0.514444
FT_TO_M = 0.3048
ISA_SEA_LEVEL_K = 288.15
ISA_LAPSE_K_PER_M = 0.0065
GAMMA = 1.4
R_AIR = 287.05287

# Cost index → Mach eşlemesi (uçak tipine göre ölçeklenir)
CI_MIN = 0
CI_MAX = 200
CI_DEFAULT = 30

# Hız–yakıt üstel düzeltmesi. 1.6, 737-800/A320 sınıfı uçaklarda
# M0.78 → M0.82 geçişinde ~%7-8 saatlik yakıt artışına karşılık gelir.
SPEED_FUEL_EXPONENT = 1.6

# Yakıt fiyatı (USD/kg, Jet A-1 küresel ortalama)
FUEL_PRICE_USD_PER_KG = 0.80

# Basit (OpenAP yoksa) yedek model parametreleri
_FALLBACK = {
    "B738": {"oew": 41400, "mtow": 79000, "nominal_mach": 0.789, "mmo": 0.82,
             "ff_kg_s": 0.70, "cruise_alt": 35000},
}


@dataclass
class PhaseResult:
    """Tek bir uçuş fazının (tırmanma/cruise/alçalma) çıktısı."""
    time_min: float
    fuel_kg: float
    distance_nm: float
    altitude_ft: float = 0.0

    def to_dict(self) -> dict:
        return {
            "time_min": round(self.time_min, 1),
            "fuel_kg": round(self.fuel_kg, 1),
            "distance_nm": round(self.distance_nm, 1),
            "altitude_ft": round(self.altitude_ft, 0),
        }


class AircraftPerformance:
    """
    Tek bir uçak tipi için hız, yakıt akışı ve dikey profil modeli.

    Nesneler uçak tipine göre `get_performance()` üzerinden cache'lenir;
    OpenAP nesneleri pahalı olduğu için her istekte yeniden kurulmaz.
    """

    def __init__(self, aircraft_type: str = "B738"):
        self.aircraft_type = (aircraft_type or "B738").upper()
        self.ac = self.aircraft_type
        self.available = False
        self.known_type = False

        if OPENAP_AVAILABLE:
            try:
                # use_synonym: A21N→A321, B38M→B737 gibi yeni tipler OpenAP
                # veritabanında doğrudan yoksa en yakın türe eşlenir.
                self.props = prop.aircraft(self.ac, use_synonym=True)
                self.fuelflow = FuelFlow(ac=self.ac, use_synonym=True)
                cruise = self.props.get("cruise", {}) or {}
                self.nominal_mach = float(cruise.get("mach") or 0.78)
                self.nominal_alt_ft = float(cruise.get("height") or 10668) / FT_TO_M
                self.mmo = float(self.props.get("mmo") or 0.82)
                self.mtow = float(self.props.get("mtow") or 79000)
                self.mlw = float(self.props.get("mlw") or self.mtow * 0.84)
                self.oew = float(self.props.get("oew") or self.mtow * 0.52)
                self.mfc_l = float(self.props.get("mfc") or 20000)
                self.max_fuel_kg = self.mfc_l * 0.8025
                self.available = True
                self.known_type = True
            except Exception as exc:  # pragma: no cover
                print(f"[UYARI] OpenAP {self.ac} yüklenemedi, basit model: {exc}")

        if not self.available:
            fb = _FALLBACK.get(self.ac, _FALLBACK["B738"])
            self.nominal_mach = fb["nominal_mach"]
            self.nominal_alt_ft = fb["cruise_alt"]
            self.mmo = fb["mmo"]
            self.mtow = fb["mtow"]
            self.mlw = fb["mtow"] * 0.84
            self.oew = fb["oew"]
            self.max_fuel_kg = 16000.0

        # Yakıt akışı cache'i: (irtifa_ft, tas_kts, yuvarlanmış kütle) → kg/s
        self._ff_cache: dict = {}

    # ═══════════════════════════════════════════════════════════════
    #  Hız / irtifa
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def speed_of_sound_kts(altitude_ft: float) -> float:
        """ISA troposferde ses hızı (knots)."""
        alt_m = max(0.0, altitude_ft * FT_TO_M)
        temp_k = ISA_SEA_LEVEL_K - ISA_LAPSE_K_PER_M * alt_m
        temp_k = max(temp_k, 216.65)  # tropopoz alt sınırı
        return math.sqrt(GAMMA * R_AIR * temp_k) / KTS_TO_MS

    def mach_for_ci(self, cost_index: float) -> float:
        """
        Cost index → cruise Mach.

        CI 0   → uzun menzil cruise (LRC), en ekonomik hız.
        CI 200 → yüksek hızlı cruise (HSC), Mmo'ya yakın.

        Aralık uçak verisinden türetilir: LRC = nominal − 0.036,
        HSC = min(Mmo − 0.02, nominal + 0.028).
        """
        ci = max(CI_MIN, min(CI_MAX, float(cost_index)))
        mach_lrc = max(0.68, self.nominal_mach - 0.036)
        mach_hsc = min(self.mmo - 0.02, self.nominal_mach + 0.028)
        if mach_hsc <= mach_lrc:
            return self.nominal_mach
        return mach_lrc + (mach_hsc - mach_lrc) * (ci - CI_MIN) / (CI_MAX - CI_MIN)

    def tas_for_ci(self, cost_index: float, altitude_ft: float) -> float:
        """CI'ya karşılık gelen gerçek hava hızı (TAS, knots)."""
        return self.mach_for_ci(cost_index) * self.speed_of_sound_kts(altitude_ft)

    def optimal_cruise_alt_ft(self, distance_nm: float) -> float:
        """
        Mesafeye göre makul cruise irtifası (fiziksel sınır).

        34 NM'lik bir hop FL390'da uçulmaz; kısa rotalarda irtifa kısıtlanır.
        """
        if distance_nm <= 120:
            return 12000.0
        if distance_nm <= 300:
            return 22000.0
        if distance_nm <= 700:
            return 30000.0
        return 35000.0

    def candidate_levels(self, distance_nm: float) -> list:
        """
        Değerlendirilecek (basınç_hPa, irtifa_ft) katmanları.

        Kısa rotalarda 390 hPa yerine 500/400 hPa kullanılır — FL390'da
        34 NM uçmak fiziksel olarak anlamsızdır.
        """
        if distance_nm <= 60:
            return [(850, 6000)]
        if distance_nm <= 120:
            return [(700, 10000)]
        if distance_nm <= 300:
            return [(500, 18000), (400, 24000)]
        if distance_nm <= 700:
            return [(400, 24000), (300, 30000), (250, 34000)]
        return [(300, 30000), (250, 34000), (200, 39000)]

    # ═══════════════════════════════════════════════════════════════
    #  Kütle
    # ═══════════════════════════════════════════════════════════════

    def initial_mass(self, distance_nm: float, load_factor: float = 0.8) -> float:
        """
        Rota mesafesine göre kalkış kütlesi (kg).

        OpenAP `mass.from_range` kullanılır (yakıt + faydalı yük). Sonuç
        OEW ile MTOW arasına sıkıştırılır; kısa rotalarda bile boş uçak
        uçurulmaz.
        """
        if OPENAP_AVAILABLE:
            try:
                mass = float(openap_mass.from_range(
                    self.ac, max(distance_nm, 100), load_factor=load_factor
                ))
            except Exception:
                mass = self.oew + self.max_fuel_kg * 0.35 + (self.mtow - self.oew) * 0.25
        else:
            mass = self.oew + self.max_fuel_kg * 0.35 + (self.mtow - self.oew) * 0.25

        min_mass = self.oew + (self.mtow - self.oew) * 0.15
        return max(min_mass, min(self.mtow, mass))

    def landing_mass(self, takeoff_mass: float, trip_fuel_kg: float) -> float:
        return max(self.oew, takeoff_mass - trip_fuel_kg)

    # ═══════════════════════════════════════════════════════════════
    #  Yakıt akışı
    # ═══════════════════════════════════════════════════════════════

    def fuel_flow_kg_s(
        self,
        mass_kg: float,
        tas_kts: float,
        altitude_ft: float,
        vertical_rate_fpm: float = 0.0,
    ) -> float:
        """
        Cruise/tırmanma/alçalma yakıt akışı (kg/s).

        OpenAP `enroute` taban alınır (kütle, hız, irtifa ve dikey hız
        gerçekten hesaba girer). Hız etkisi, nominal hıza göre üstel
        düzeltme ile uygulanır (SPEED_FUEL_EXPONENT).
        """
        tas = max(120.0, float(tas_kts))
        nominal_tas = max(
            150.0, self.nominal_mach * self.speed_of_sound_kts(altitude_ft)
        )

        # Cache anahtarı: 500 kg kütle, 5 kt hız, 1000 ft irtifa kuantizasyonu
        key = (
            int(round(altitude_ft / 1000.0)),
            int(round(tas / 5.0)) * 5,
            int(round(mass_kg / 500.0)) * 500,
            int(round(vertical_rate_fpm / 250.0)) * 250,
        )
        cached = self._ff_cache.get(key)
        if cached is not None:
            return cached

        base = None
        if self.available:
            try:
                base = float(self.fuelflow.enroute(
                    mass=max(mass_kg, self.oew),
                    tas=tas * KTS_TO_MS,
                    alt=max(altitude_ft, 0.0) * FT_TO_M,
                    vs=vertical_rate_fpm,
                ))
            except Exception:
                base = None

        if base is None or not math.isfinite(base) or base <= 0:
            # Basit yedek: cruise ~0.70 kg/s, irtifa ile hafif düşüş
            base = 0.70 * (1.0 - 0.25 * (altitude_ft / 40000.0))
            base *= max(0.7, min(1.35, mass_kg / 65000.0))

        # Hız etkisi (nominal hıza göre)
        speed_factor = (tas / nominal_tas) ** SPEED_FUEL_EXPONENT
        ff = base * speed_factor

        self._ff_cache[key] = ff
        return ff

    def cruise_flow_per_nm(
        self,
        mass_kg: float,
        cost_index: float,
        altitude_ft: float,
        headwind_kts: float = 0.0,
    ) -> tuple:
        """
        Cruise için NM başına yakıt (kg/NM) ve dakika (dk/NM).

        Dönüş: (fuel_per_nm, min_per_nm, ground_speed, tas, mach)
        """
        tas = self.tas_for_ci(cost_index, altitude_ft)
        gs = max(120.0, tas - headwind_kts)
        ff = self.fuel_flow_kg_s(mass_kg, tas, altitude_ft)
        fuel_per_nm = ff * 3600.0 / gs
        min_per_nm = 60.0 / gs
        return fuel_per_nm, min_per_nm, gs, tas, self.mach_for_ci(cost_index)

    # ═══════════════════════════════════════════════════════════════
    #  Dikey profil (tırmanma / alçalma)
    # ═══════════════════════════════════════════════════════════════

    def climb_profile(
        self,
        from_ft: float,
        to_ft: float,
        mass_kg: float,
        step_ft: float = 2000.0,
    ) -> PhaseResult:
        """
        Tırmanma fazı: sabit adımlarla OpenAP yakıt akışı integrasyonu.

        Dikey hız irtifayla azalır (2200 → 1200 fpm), hız 300 kt CAS'tan
        M0.78'e kadar TAS'a çevrilir.
        """
        if to_ft <= from_ft + 100:
            return PhaseResult(0.0, 0.0, 0.0, from_ft)

        alt = float(from_ft)
        time_min = 0.0
        fuel = 0.0
        distance = 0.0
        mass = mass_kg

        while alt < to_ft - 1e-6:
            alt_next = min(to_ft, alt + step_ft)
            mid = (alt + alt_next) / 2.0
            vs = 2200.0 if mid < 15000 else 1800.0 if mid < 25000 else 1200.0
            cas = 300.0 if mid < 25000 else 290.0
            tas = min(cas / max(self._density_ratio(mid), 1e-3) ** 0.5,
                      self.mach_for_ci(CI_DEFAULT) * self.speed_of_sound_kts(mid))
            dt_min = (alt_next - alt) / vs
            ff = self.fuel_flow_kg_s(mass, tas, mid, vertical_rate_fpm=vs)
            burned = ff * dt_min * 60.0
            fuel += burned
            mass -= burned
            time_min += dt_min
            distance += tas * dt_min / 60.0
            alt = alt_next

        return PhaseResult(time_min, fuel, distance, to_ft)

    def descent_profile(
        self,
        from_ft: float,
        to_ft: float,
        mass_kg: float,
        step_ft: float = 2000.0,
    ) -> PhaseResult:
        """Alçalma fazı — tipik 1500-1800 fpm, düşük itki."""
        if from_ft <= to_ft + 100:
            return PhaseResult(0.0, 0.0, 0.0, to_ft)

        alt = float(from_ft)
        time_min = 0.0
        fuel = 0.0
        distance = 0.0
        mass = mass_kg

        while alt > to_ft + 1e-6:
            alt_next = max(to_ft, alt - step_ft)
            mid = (alt + alt_next) / 2.0
            vs = -1500.0 if mid > 10000 else -1200.0
            cas = 290.0 if mid > 10000 else 250.0
            tas = min(cas / max(self._density_ratio(mid), 1e-3) ** 0.5,
                      self.mach_for_ci(CI_DEFAULT) * self.speed_of_sound_kts(mid))
            dt_min = (alt - alt_next) / abs(vs)
            ff = self.fuel_flow_kg_s(mass, tas, mid, vertical_rate_fpm=vs)
            burned = ff * dt_min * 60.0
            fuel += burned
            mass -= burned
            time_min += dt_min
            distance += tas * dt_min / 60.0
            alt = alt_next

        return PhaseResult(time_min, fuel, distance, to_ft)

    @staticmethod
    def _density_ratio(altitude_ft: float) -> float:
        """
        ISA yoğunluk oranı σ = ρ/ρ0 (CAS → TAS dönüşümü için).

        Troposferde σ = (T/T₀)^(g/(L·R) − 1) ≈ (T/T₀)^4.2561
        """
        alt_m = max(0.0, altitude_ft * FT_TO_M)
        t = max(ISA_SEA_LEVEL_K - ISA_LAPSE_K_PER_M * alt_m, 216.65)
        return (t / ISA_SEA_LEVEL_K) ** 4.2561

    # ═══════════════════════════════════════════════════════════════
    #  Rota profili
    # ═══════════════════════════════════════════════════════════════

    def evaluate_route(
        self,
        segments: Iterable[dict],
        cruise_alt_ft: float,
        cost_index: float,
        takeoff_elev_ft: float = 0.0,
        landing_elev_ft: float = 0.0,
        initial_mass_kg: Optional[float] = None,
    ) -> dict:
        """
        Bir rota boyunca kütle azalmasını ve fazları entegre eder.

        Args:
            segments: [{"distance_nm", "headwind_kts"}] sırayla
            cruise_alt_ft: cruise irtifası
            cost_index: CI
            takeoff_elev_ft / landing_elev_ft: havalimanı yükseklikleri
            initial_mass_kg: verilmezse rota mesafesinden tahmin edilir

        Returns:
            Toplam yakıt/süre/mesafe + faz kırılımı + kütle profili.
        """
        segments = list(segments)
        path_distance = sum(max(0.0, s.get("distance_nm", 0.0)) for s in segments)
        if initial_mass_kg is None:
            initial_mass_kg = self.initial_mass(path_distance + 150)

        # ── Dikey profil rotaya sığmalı ────────────────────────────
        # Tırmanma + alçalma yatay mesafesi rota uzunluğuna yaklaşırsa
        # (çok kısa hop) cruise irtifası düşürülür; aksi hâlde profil
        # rota mesafesini aşar.
        altitude = float(cruise_alt_ft)
        climb = self.climb_profile(takeoff_elev_ft, altitude, initial_mass_kg)
        descent = self.descent_profile(
            altitude, landing_elev_ft, max(self.oew, initial_mass_kg - climb.fuel_kg)
        )
        for _ in range(8):
            vertical_distance = climb.distance_nm + descent.distance_nm
            if vertical_distance <= 0.85 * max(path_distance, 1.0) or altitude <= 3500:
                break
            altitude = max(3500.0, altitude * 0.72)
            climb = self.climb_profile(takeoff_elev_ft, altitude, initial_mass_kg)
            descent = self.descent_profile(
                altitude, landing_elev_ft,
                max(self.oew, initial_mass_kg - climb.fuel_kg),
            )

        # ── Cruise: yolun tırmanma/alçalma dışında kalan kısmı ─────
        # Yol mesafesi havalimanı→havalimanıdır; tırmanma ve alçalma bu
        # mesafenin içindedir, üstüne eklenmez.
        mass = initial_mass_kg - climb.fuel_kg
        fuel = climb.fuel_kg
        time_min = climb.time_min
        distance = path_distance
        tas = self.tas_for_ci(cost_index, altitude)
        mach = self.mach_for_ci(cost_index)

        cruise_remaining = max(0.0, path_distance - climb.distance_nm - descent.distance_nm)
        climb_remaining = climb.distance_nm
        cruise_distance = 0.0
        cruise_time = 0.0
        headwind_sum = 0.0
        mass_samples = [round(mass, 0)]

        for seg in segments:
            seg_dist = max(0.0, seg.get("distance_nm", 0.0))
            if seg_dist <= 0:
                continue

            if climb_remaining > 0:
                used = min(seg_dist, climb_remaining)
                climb_remaining -= used
                seg_dist -= used
            if seg_dist <= 0 or cruise_remaining <= 0:
                continue

            used = min(seg_dist, cruise_remaining)
            headwind = float(seg.get("headwind_kts", 0.0) or 0.0)
            gs = max(120.0, tas - headwind)
            dt_min = used / gs * 60.0
            ff = self.fuel_flow_kg_s(mass, tas, altitude)
            burned = ff * dt_min * 60.0
            fuel += burned
            mass -= burned
            cruise_remaining -= used
            cruise_distance += used
            cruise_time += dt_min
            headwind_sum += headwind * used
            mass_samples.append(round(mass, 0))

        time_min += cruise_time

        # Alçalma, cruise sonrası kütleyle yeniden hesaplanır
        descent = self.descent_profile(altitude, landing_elev_ft, mass)
        fuel += descent.fuel_kg
        time_min += descent.time_min
        mass -= descent.fuel_kg

        avg_headwind = headwind_sum / cruise_distance if cruise_distance > 0 else 0.0
        avg_gs = cruise_distance / cruise_time * 60.0 if cruise_time > 0 else tas

        return {
            "total_distance_nm": round(distance, 1),
            "cruise_distance_nm": round(cruise_distance, 1),
            "fuel_kg": round(fuel, 1),
            "time_min": round(time_min, 1),
            "co2_kg": round(fuel_to_co2(fuel), 1),
            "takeoff_mass_kg": round(initial_mass_kg, 0),
            "landing_mass_kg": round(mass, 0),
            "mass_samples_kg": mass_samples,
            "fuel_capacity_kg": round(self.max_fuel_kg, 0),
            "feasible": fuel <= self.max_fuel_kg * 1.02,
            "fuel_margin_kg": round(self.max_fuel_kg - fuel, 0),
            "cruise_altitude_ft": round(altitude, 0),
            "tas_kts": round(tas, 0),
            "mach": round(mach, 3),
            "avg_ground_speed_kts": round(avg_gs, 0),
            "avg_headwind_kts": round(avg_headwind, 0),
            "cost_index": int(max(CI_MIN, min(CI_MAX, cost_index))),
            "phases": {
                "climb": climb.to_dict(),
                "cruise": {
                    "time_min": round(cruise_time, 1),
                    "fuel_kg": round(fuel - climb.fuel_kg - descent.fuel_kg, 1),
                    "distance_nm": round(cruise_distance, 1),
                    "altitude_ft": round(altitude, 0),
                },
                "descent": descent.to_dict(),
            },
            "fuel_cost_usd": round(fuel * FUEL_PRICE_USD_PER_KG, 2),
        }

    # ═══════════════════════════════════════════════════════════════
    #  Gerçek iz (track) değerlendirmesi — doğrulama için
    # ═══════════════════════════════════════════════════════════════

    def evaluate_track(self, track: list, cost_index: float = CI_DEFAULT) -> Optional[dict]:
        """
        Gerçek ADS-B izi üzerinden yakıt/süre tahmini.

        track: [[timestamp, lat, lon, baro_altitude_m, heading, on_ground], ...]
        (OpenSky `/tracks/all` irtifayı metre cinsinden verir.)

        İz kendi irtifa ve zaman damgalarıyla değerlendirilir; böylece
        "bu uçak gerçekten nasıl uçtu ve ne yaktı" sorusuna model tabanlı
        bir cevap verilir. Kütle, izin toplam mesafesinden başlatılır.

        Not: yer hızı doğrudan izden alınır, TAS'e çevrilmez. Bu yüzden
        kuvvetli karşı rüzgârda yakıt bir miktar düşük, kuyruk rüzgârında
        bir miktar yüksek tahmin edilir (±%3 mertebesi).
        """
        from utils.geo import haversine_nm

        pts = [
            p for p in track
            if len(p) >= 5 and p[1] is not None and p[2] is not None and not p[5]
        ]
        if len(pts) < 2:
            return None

        total_dist = 0.0
        for i in range(1, len(pts)):
            total_dist += haversine_nm(pts[i - 1][1], pts[i - 1][2],
                                       pts[i][1], pts[i][2])

        mass = self.initial_mass(max(total_dist, 100))
        fuel = 0.0
        elapsed_s = 0.0
        cruise_samples = 0
        alt_sum = 0.0

        for i in range(1, len(pts)):
            p0, p1 = pts[i - 1], pts[i]
            dt_s = max(1.0, float(p1[0]) - float(p0[0]))
            if dt_s > 900:  # veri boşluğu — fazla interpolasyon yapma
                continue
            dist = haversine_nm(p0[1], p0[2], p1[1], p1[2])
            alt_m = p1[3] if p1[3] is not None else p0[3]
            alt_ft = max(1000.0, float(alt_m or 9000.0) * 3.28084)
            gs = dist / (dt_s / 3600.0) if dt_s > 0 else 0.0
            if gs < 60:
                continue
            # Gerçek yer hızından TAS tahmini (rüzgâr bilinmiyor → TAS≈GS)
            tas = max(150.0, gs)
            ff = self.fuel_flow_kg_s(mass, tas, alt_ft)
            burned = ff * dt_s
            fuel += burned
            mass -= burned
            elapsed_s += dt_s
            if alt_ft > 25000:
                cruise_samples += 1
                alt_sum += alt_ft

        if elapsed_s <= 0:
            return None

        return {
            "track_points": len(pts),
            "distance_nm": round(total_dist, 1),
            "fuel_kg": round(fuel, 1),
            "time_min": round(elapsed_s / 60.0, 1),
            "co2_kg": round(fuel_to_co2(fuel), 1),
            "avg_altitude_ft": round(alt_sum / cruise_samples, 0) if cruise_samples else None,
            "landing_mass_kg": round(mass, 0),
            "cost_index": int(cost_index),
            "source": "adsb_track_model",
        }


# ─── Cache'li erişim ────────────────────────────────────────────────

@lru_cache(maxsize=16)
def get_performance(aircraft_type: str = "B738") -> AircraftPerformance:
    """Uçak tipine göre performans nesnesi (cache'li)."""
    return AircraftPerformance(aircraft_type)


METHOD_NOTES = {
    "base_fuel_model": (
        "OpenAP 2.4 FuelFlow.enroute — ICAO emisyon veritabanı yakıt modeli, "
        "Gur vd. (2010) dalga sürüklemesi dahil."
    ),
    "cost_index": (
        "CI 0→200, LRC (nominal Mach − 0.036) ile HSC (nominal + 0.028, "
        "Mmo − 0.02 sınırı) arasında doğrusal eşlenir."
    ),
    "speed_fuel_coupling": (
        f"Saatlik yakıt akışı (TAS/nominal TAS)^{SPEED_FUEL_EXPONENT} ile "
        "ölçeklenir; 737/A320 sınıfı yayınlanmış CI davranışına kalibre edildi. "
        "OpenAP'ın hız duyarlılığı M0.74-0.82 bandında kullanılmaz."
    ),
    "mass": (
        "Kalkış kütlesi OpenAP mass.from_range ile rotadan türetilir; yakıt "
        "yanarken kütle ve dolayısıyla yakıt akışı azalır (adım integrasyonu)."
    ),
    "vertical_profile": (
        "Tırmanma/alçalma 2000 ft adımlarla OpenAP enroute ile entegre edilir; "
        "dikey hız ve CAS→TAS dönüşümü irtifaya göre değişir. Dikey fazlarda "
        "rüzgâr etkisi ihmal edilir."
    ),
    "altitude_layers": (
        "FL300/340/390 (ve kısa rotalarda 180/240) rüzgârları ayrı ayrı "
        "değerlendirilir; en düşük kompozit maliyetli katman seçilir."
    ),
    "co2": "1 kg Jet A-1 = 3.16 kg CO₂ (ICAO yakıt çevrim faktörü).",
    "fuel_price": f"{FUEL_PRICE_USD_PER_KG} USD/kg Jet A-1 (küresel ortalama).",
}
