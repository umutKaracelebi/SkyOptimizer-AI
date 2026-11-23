"""
SkyOptimizer AI — Birikimli Tasarruf Deposu (SQLite)

Önceden birikimli istatistikler yalnızca tarayıcının localStorage'ında
tutuluyordu: tarayıcı değişince rakam sıfırlanıyor, ekip ortak istatistik
göremiyordu. Bu modül optimizasyon sonuçlarını sunucuda saklar.

SQLite standart kütüphanededir; ek bağımlılık yoktur.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_DB = DATA_DIR / "savings.db"


def db_path() -> Path:
    env = os.getenv("SAVINGS_DB_PATH", "").strip()
    if env:
        p = Path(env)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DEFAULT_DB


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Tabloları oluştur (idempotent)."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS optimizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                origin TEXT NOT NULL,
                destination TEXT NOT NULL,
                aircraft_type TEXT,
                cost_index INTEGER,
                cruise_altitude_ft REAL,
                standard_fuel_kg REAL,
                optimized_fuel_kg REAL,
                fuel_saved_kg REAL,
                time_saved_min REAL,
                co2_saved_kg REAL,
                cost_saved_usd REAL,
                departure_time TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_opt_created ON optimizations(created_at)"
        )


def record_optimization(result: dict, departure_time: Optional[str] = None) -> bool:
    """
    Bir optimizasyon sonucunu kaydet.

    Aynı rota için ölçülebilir tasarruf yoksa da kaydedilir; toplam sayaç
    yalnızca tasarrufları toplar, `optimizations` sayısı tüm çağrıları.
    """
    try:
        init_db()
        origin = (result.get("origin") or {}).get("icao") or result.get("origin_icao") or ""
        dest = (result.get("destination") or {}).get("icao") or result.get("destination_icao") or ""
        savings = result.get("savings") or {}
        optimized = result.get("optimized_route") or {}
        standard = result.get("standard_route") or {}
        perf = result.get("aircraft_performance") or {}

        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO optimizations (
                    created_at, origin, destination, aircraft_type, cost_index,
                    cruise_altitude_ft, standard_fuel_kg, optimized_fuel_kg,
                    fuel_saved_kg, time_saved_min, co2_saved_kg, cost_saved_usd,
                    departure_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    origin,
                    dest,
                    result.get("aircraft_type"),
                    int(perf.get("cost_index", 0) or 0),
                    optimized.get("cruise_altitude_ft"),
                    standard.get("estimated_fuel_kg"),
                    optimized.get("estimated_fuel_kg"),
                    savings.get("fuel_saved_kg", 0.0),
                    savings.get("time_saved_min", 0.0),
                    savings.get("co2_saved_kg", 0.0),
                    savings.get("cost_saved_usd", 0.0),
                    departure_time,
                ),
            )
        return True
    except Exception as exc:  # pragma: no cover - depo hatası uygulamayı durdurmaz
        print(f"[UYARI] Tasarruf kaydedilemedi: {exc}")
        return False


def get_totals(limit_recent: int = 12) -> dict:
    """
    Birikimli toplamlar + son optimizasyonlar.

    `totals.total_co2_ton`: jüriye gösterilecek "toplam X ton CO₂" değeri.
    """
    try:
        init_db()
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total_optimizations,
                    COALESCE(SUM(fuel_saved_kg), 0) AS total_fuel_kg,
                    COALESCE(SUM(time_saved_min), 0) AS total_time_min,
                    COALESCE(SUM(co2_saved_kg), 0) AS total_co2_kg,
                    COALESCE(SUM(cost_saved_usd), 0) AS total_cost_usd,
                    COUNT(DISTINCT origin || '-' || destination) AS distinct_routes
                FROM optimizations
                """
            ).fetchone()
            recent = conn.execute(
                """
                SELECT created_at, origin, destination, aircraft_type,
                       fuel_saved_kg, time_saved_min, co2_saved_kg, cost_saved_usd
                FROM optimizations ORDER BY id DESC LIMIT ?
                """,
                (max(1, int(limit_recent)),),
            ).fetchall()

        totals = {
            "total_optimizations": int(row["total_optimizations"]),
            "total_fuel_kg": round(float(row["total_fuel_kg"]), 1),
            "total_time_min": round(float(row["total_time_min"]), 1),
            "total_co2_kg": round(float(row["total_co2_kg"]), 1),
            "total_co2_ton": round(float(row["total_co2_kg"]) / 1000.0, 3),
            "total_cost_usd": round(float(row["total_cost_usd"]), 2),
            "distinct_routes": int(row["distinct_routes"]),
        }
        return {
            "storage": str(db_path()),
            "totals": totals,
            "recent": [dict(r) for r in recent],
        }
    except Exception as exc:  # pragma: no cover
        print(f"[UYARI] İstatistik okunamadı: {exc}")
        return {
            "storage": str(db_path()),
            "totals": {
                "total_optimizations": 0, "total_fuel_kg": 0.0,
                "total_time_min": 0.0, "total_co2_kg": 0.0,
                "total_co2_ton": 0.0, "total_cost_usd": 0.0,
                "distinct_routes": 0,
            },
            "recent": [],
            "error": str(exc),
        }
