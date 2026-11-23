"""Servis yardımcıları için ağsız birim testleri."""

from services.aircraft_service import classify_flight
from services.weather_service import _parse_visibility_sm


def test_visibility_string_values():
    assert _parse_visibility_sm("6+") == 6.0
    assert _parse_visibility_sm("10") == 10.0
    assert _parse_visibility_sm("1/2") == 0.5
    assert _parse_visibility_sm(None) is None
    assert _parse_visibility_sm("CAVOK") is None


def test_aircraft_class_from_type_code_wins():
    # Tip kodu, hız/irtifa sezgisinden daha güvenilirdir.
    assert classify_flight(200.0, 1000.0, type_code="B77W") == "heavy"
    assert classify_flight(120.0, 300.0, type_code="A320") == "narrow"
    assert classify_flight(None, None, type_code="C172") == "light"
    # C17 (Globemaster) C172 ile karıştırılmamalı.
    assert classify_flight(None, None, type_code="C17") == "military"


def test_aircraft_class_from_emitter_category():
    # Kategori 5 = heavy, 2 = light (ADS-B emitter category).
    assert classify_flight(250.0, 10000.0, emitter_category=5) == "heavy"
    assert classify_flight(50.0, 500.0, emitter_category=2) == "light"


def test_aircraft_class_heuristics_avoid_approach_mislabel():
    # Alçak irtifada 188 kt yaklaşan bir jet turboprop sayılmamalı.
    assert classify_flight(96.7, 830.0) == "narrow"
    # Cruise bandında yavaş uçan turboprop.
    assert classify_flight(123.0, 7000.0) == "turboprop"
    # Çok yavaş ve alçak: hafif uçak.
    assert classify_flight(50.0, 300.0) == "light"
