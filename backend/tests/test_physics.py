"""Fizik motoru: cost index, kütle, tırmanma/alçalma, rüzgâr."""

import pytest

from optimization.cost_model import CostModel
from optimization.performance import (
    CI_DEFAULT,
    AircraftPerformance,
    get_performance,
)
from services.validation_service import _assess_reliability
from utils.geo import fuel_to_co2


def test_aircraft_loaded_from_openap():
    perf = get_performance("B738")
    assert perf.known_type is True
    assert 0.74 < perf.nominal_mach < 0.84
    assert perf.mtow > 60000
    assert perf.max_fuel_kg > 10000


def test_synonym_types_resolve():
    """A21N/B38M gibi yeni tipler en yakın OpenAP türüne eşlenmeli."""
    for code in ("A21N", "A20N", "B38M"):
        perf = get_performance(code)
        assert perf.known_type is True, code


def test_cost_index_moves_speed_and_fuel_monotonically():
    perf = get_performance("B738")
    low_mach = perf.mach_for_ci(0)
    high_mach = perf.mach_for_ci(200)
    assert high_mach > low_mach

    segments = [{"distance_nm": 100.0, "headwind_kts": 0.0}] * 10
    low = perf.evaluate_route(segments, 30000, 0)
    high = perf.evaluate_route(segments, 30000, 200)

    assert high["time_min"] < low["time_min"]
    assert high["fuel_kg"] > low["fuel_kg"]
    # Gerçekçi büyüklük: CI 0→200 arasında yakıt %1-8 artar, süre %2-10 azalır
    fuel_change = (high["fuel_kg"] / low["fuel_kg"] - 1) * 100
    time_change = (1 - high["time_min"] / low["time_min"]) * 100
    assert 1.0 < fuel_change < 8.0
    assert 2.0 < time_change < 10.0


def test_mass_decreases_along_route():
    perf = get_performance("B738")
    profile = perf.evaluate_route(
        [{"distance_nm": 100.0, "headwind_kts": 0.0}] * 8, 30000, CI_DEFAULT
    )
    masses = profile["mass_samples_kg"]
    assert len(masses) >= 3
    assert all(a >= b for a, b in zip(masses, masses[1:]))
    assert profile["landing_mass_kg"] < profile["takeoff_mass_kg"]
    assert profile["landing_mass_kg"] > perf.oew


def test_climb_and_descent_burn_fuel_and_take_time():
    perf = get_performance("B738")
    profile = perf.evaluate_route(
        [{"distance_nm": 60.0, "headwind_kts": 0.0}] * 5, 30000, CI_DEFAULT
    )
    climb = profile["phases"]["climb"]
    descent = profile["phases"]["descent"]
    assert climb["fuel_kg"] > 300
    assert descent["fuel_kg"] > 30
    assert climb["time_min"] > 8
    # Kısa rotada tırmanma+alçalma yakıtın önemli bir kısmı olmalı
    assert (climb["fuel_kg"] + descent["fuel_kg"]) / profile["fuel_kg"] > 0.3


def test_route_distance_does_not_double_count_vertical_profile():
    """Toplam mesafe = havalimanı→havalimanı; tırmanma/alçalma üstüne eklenmez."""
    perf = get_performance("B738")
    profile = perf.evaluate_route(
        [{"distance_nm": 500.0, "headwind_kts": 0.0}], 30000, CI_DEFAULT
    )
    assert profile["total_distance_nm"] == pytest.approx(500.0, abs=0.2)
    assert profile["cruise_distance_nm"] < 500.0
    assert (
        profile["phases"]["climb"]["distance_nm"]
        + profile["cruise_distance_nm"]
        + profile["phases"]["descent"]["distance_nm"]
    ) == pytest.approx(500.0, abs=1.0)


def test_very_short_route_reduces_cruise_altitude():
    """34 NM'lik hop FL300'de uçulmaz; profil rotaya sığmalı."""
    perf = get_performance("B738")
    profile = perf.evaluate_route(
        [{"distance_nm": 34.0, "headwind_kts": 0.0}], 30000, CI_DEFAULT
    )
    assert profile["cruise_altitude_ft"] < 12000
    assert profile["phases"]["cruise"]["distance_nm"] >= 0


def test_headwind_increases_fuel_and_time():
    model = CostModel("B738")
    still = model.calculate_segment_cost(distance_nm=500)
    headwind = model.calculate_segment_cost(
        distance_nm=500, wind_speed_kts=100, wind_direction=90, aircraft_heading=90
    )

    assert headwind["headwind_kts"] > 0
    assert headwind["fuel_kg"] > still["fuel_kg"]
    assert headwind["time_min"] > still["time_min"]


def test_tailwind_reduces_time():
    model = CostModel("B738")
    still = model.calculate_segment_cost(distance_nm=500)
    tailwind = model.calculate_segment_cost(
        distance_nm=500, wind_speed_kts=100, wind_direction=270, aircraft_heading=90
    )

    assert tailwind["headwind_kts"] < 0
    assert tailwind["time_min"] < still["time_min"]
    assert tailwind["fuel_kg"] < still["fuel_kg"]


def test_composite_cost_is_one_for_reference_route():
    model = CostModel("B738")
    reference = {"fuel_kg": 8000.0, "time_min": 200.0, "co2_kg": 25280.0}

    cost = model.composite_cost(
        fuel_kg=reference["fuel_kg"],
        time_min=reference["time_min"],
        co2_kg=reference["co2_kg"],
        weights={"fuel": 0.4, "time": 0.35, "co2": 0.25},
        reference=reference,
    )
    assert cost == pytest.approx(1.0)


def test_composite_weights_are_normalized():
    model = CostModel("B738")
    weights = model._normalize_weights({"fuel": 4, "time": 3.5, "co2": 2.5})
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["fuel"] == pytest.approx(0.4)


def test_fuel_capacity_marks_long_route_infeasible():
    perf = AircraftPerformance("B738")
    profile = perf.evaluate_route(
        [{"distance_nm": 500.0, "headwind_kts": 0.0}] * 14, 39000, CI_DEFAULT
    )
    assert profile["fuel_kg"] > profile["fuel_capacity_kg"]
    assert profile["feasible"] is False
    assert profile["fuel_margin_kg"] < 0


def test_evaluate_track_uses_meter_altitudes():
    """OpenSky izleri irtifayı metre verir; feet'e çevrilmeli."""
    perf = get_performance("B738")
    track = [
        [1_700_000_000 + i * 60, 38.0, 27.0 + i * 0.1, 10000, 90, False]
        for i in range(8)
    ]
    result = perf.evaluate_track(track)
    assert result is not None
    assert result["avg_altitude_ft"] == pytest.approx(32808, abs=20)
    assert result["track_points"] == 8
    assert result["fuel_kg"] > 0


def test_unknown_openap_type_uses_labelled_proxy():
    """A339 gibi OpenAP'ta olmayan tipler sessizce B738'e düşmemeli."""
    perf = get_performance("A339")
    assert perf.known_type is True
    assert perf.is_proxy is True
    assert perf.performance_type == "A333"
    assert perf.initial_mass(3000) > 120_000
    assert perf.fuel_flow_kg_s(160_000, 480, 34000) > 0.9


def test_widebody_proxy_fuel_is_not_narrowbody_scale():
    """A339 vekili 3.000 NM'de ~25 t yakmalı, 8-9 t değil."""
    perf = get_performance("A339")
    profile = perf.evaluate_route(
        [{"distance_nm": 3000 / 14, "headwind_kts": 0.0}] * 14,
        34000,
        CI_DEFAULT,
    )
    assert 18_000 < profile["fuel_kg"] < 40_000
    assert profile["time_min"] > 300


def test_track_gap_counts_time_instead_of_skipping():
    """Uzun ADS-B boşluğu süre/yakıttan düşülmemeli."""
    perf = get_performance("B738")
    track = [
        [1_700_000_000, 40.0, 30.0, 10000, 90, False],
        [1_700_000_060, 40.2, 30.2, 10000, 90, False],
        # 30 dakikalık okyanus boşluğu
        [1_700_001_860, 42.0, 32.0, 10000, 90, False],
    ]
    result = perf.evaluate_track(track)
    assert result is not None
    assert result["time_min"] == pytest.approx(31.0, abs=0.2)
    assert result["gap_count"] == 1
    assert result["max_gap_min"] == pytest.approx(30.0, abs=1)
    assert result["fuel_kg"] > 0


def test_validation_reliability_flags_partial_track():
    actual = {
        "distance_nm": 150.0,  # 3.000 NM'lik rotanın yalnızca %5'i
        "time_min": 20.0,
        "fuel_kg": 800.0,
    }
    standard = {"estimated_time_min": 360.0}
    reliable, note = _assess_reliability(actual, standard, gc_nm=3000.0)
    assert reliable is False
    assert "kapsıyor" in note


def test_validation_reliability_accepts_full_track():
    actual = {
        "distance_nm": 3075.0,
        "time_min": 368.0,
        "fuel_kg": 23_000.0,
    }
    standard = {"estimated_time_min": 355.0}
    reliable, note = _assess_reliability(actual, standard, gc_nm=2990.0)
    assert reliable is True
    assert note is None


def test_co2_conversion_factor():
    assert fuel_to_co2(1000) == pytest.approx(3160)
