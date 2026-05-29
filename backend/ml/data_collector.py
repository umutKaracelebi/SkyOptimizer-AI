"""
SkyOptimizer AI — ML Veri Toplayıcı
Uçuş rotaları, rüzgâr koşulları ve CostModel'in hesapladığı
yakıt/süre/CO₂ maliyetlerini içeren eğitim veri seti oluşturur.

Kullanım:
    python ml/data_collector.py
"""

import csv
import random
import math
import os
import sys
import numpy as np

# Backend kök dizinini path'e ekle
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from optimization.cost_model import CostModel
from utils.geo import haversine_nm, initial_bearing, wind_components


def generate_dataset(num_samples: int = 50_000, output_file: str = "flight_data.csv"):
    """
    Rastgele mesafe, rüzgâr ve irtifa koşullarında CostModel'i çalıştırarak
    eğitim verisi üretir.

    Özellikler (Features):
        distance_nm, wind_speed_kts, wind_direction_deg,
        aircraft_heading_deg, altitude_ft, headwind_kts, crosswind_kts

    Hedefler (Labels):
        fuel_kg, time_min, co2_kg
    """
    print(f"[ML] {num_samples:,} adet veri noktası üretiliyor...")

    cost_model = CostModel(aircraft_type="B738")
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), output_file)

    with open(file_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "distance_nm",
            "wind_speed_kts",
            "wind_direction_deg",
            "aircraft_heading_deg",
            "altitude_ft",
            "headwind_kts",
            "crosswind_kts",
            "ground_speed_kts",
            "fuel_kg",
            "time_min",
            "co2_kg",
        ])

        for i in range(num_samples):
            # Log-uniform distance: kisa ucuslara daha fazla agirlik
            # log(80) ile log(2500) arasi uniform, sonra exp
            dist = math.exp(random.uniform(math.log(80), math.log(2500)))
            wind_spd = random.uniform(0, 150)         # 0-150 kts (jet-stream dahil)
            wind_dir = random.uniform(0, 360)
            heading = random.uniform(0, 360)
            alt_ft = random.choice([29000, 31000, 33000, 35000, 37000, 39000, 41000])

            # CostModel ile ground truth hesapla
            segment = cost_model.calculate_segment_cost(
                distance_nm=dist,
                wind_speed_kts=wind_spd,
                wind_direction=wind_dir,
                aircraft_heading=heading,
                altitude_ft=alt_ft,
            )

            writer.writerow([
                round(dist, 2),
                round(wind_spd, 2),
                round(wind_dir, 2),
                round(heading, 2),
                alt_ft,
                round(segment["headwind_kts"], 2),
                round(segment["crosswind_kts"], 2),
                round(segment["ground_speed_kts"], 2),
                round(segment["fuel_kg"], 2),
                round(segment["time_min"], 2),
                round(segment["co2_kg"], 2),
            ])

            if (i + 1) % 10_000 == 0:
                print(f"  {i+1:>6,} / {num_samples:,} tamamlandı")

    size_mb = os.path.getsize(file_path) / (1024 * 1024)
    print(f"[ML] Veri seti oluşturuldu: {file_path}  ({size_mb:.1f} MB)")
    return file_path


if __name__ == "__main__":
    generate_dataset(200_000, "flight_data.csv")
