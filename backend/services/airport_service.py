"""
SkyOptimizer AI — Havalimanı Servisi
OurAirports CSV verilerinden havalimanı bilgilerini yükler ve sorgular.
"""

import csv
from pathlib import Path
from typing import Optional

from services.cache_manager import cache
from utils.geo import haversine_nm

# CSV dosya yolu
DATA_DIR = Path(__file__).parent.parent / "data"
AIRPORTS_CSV = DATA_DIR / "airports.csv"

# Bellek içi havalimanı veritabanı
_airports_db: dict = {}
_loaded = False


def _load_airports():
    """CSV'den havalimanlarını belleğe yükle."""
    global _airports_db, _loaded
    if _loaded:
        return

    if not AIRPORTS_CSV.exists():
        print(f"[UYARI] airports.csv bulunamadı: {AIRPORTS_CSV}")
        _loaded = True
        return

    with open(AIRPORTS_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ident = row.get("ident", "").strip().upper()
            if not ident:
                continue

            # Sadece orta/büyük havalimanlarını al (performans için)
            airport_type = row.get("type", "")
            if airport_type not in ("large_airport", "medium_airport"):
                continue

            try:
                lat = float(row.get("latitude_deg", 0))
                lon = float(row.get("longitude_deg", 0))
            except (ValueError, TypeError):
                continue

            _airports_db[ident] = {
                "icao": ident,
                "iata": row.get("iata_code", "").strip(),
                "name": row.get("name", "").strip(),
                "city": row.get("municipality", "").strip(),
                "country": row.get("iso_country", "").strip(),
                "type": airport_type,
                "latitude": lat,
                "longitude": lon,
                "elevation_ft": _safe_float(row.get("elevation_ft")),
            }

    _loaded = True
    print(f"[INFO] {len(_airports_db)} havalimanı yüklendi.")


def _safe_float(val) -> Optional[float]:
    """Güvenli float dönüşümü."""
    try:
        return float(val) if val else None
    except (ValueError, TypeError):
        return None


def get_airport(icao: str) -> Optional[dict]:
    """ICAO koduna göre havalimanı bilgisi döndürür."""
    _load_airports()
    return _airports_db.get(icao.upper())


def search_airports(query: str, limit: int = 10) -> list:
    """
    Global havalimanı arama — ICAO, IATA kodu veya isim ile aranabilir.
    Büyük havalimanları öncelikli sıralanır.
    """
    _load_airports()

    # Cache kontrolü
    cache_key = f"search:{query}:{limit}"
    cached = cache.get("airport", cache_key)
    if cached is not None:
        return cached

    query_upper = query.upper().strip()
    if not query_upper:
        return []

    results = []
    for airport in _airports_db.values():
        score = 0
        icao = airport["icao"]
        iata = airport.get("iata", "")
        name = airport.get("name", "").upper()
        city = airport.get("city", "").upper()

        # Tam eşleşme — en yüksek skor
        if icao == query_upper:
            score = 100
        elif iata == query_upper:
            score = 90
        # Başlangıç eşleşmesi
        elif icao.startswith(query_upper):
            score = 70
        elif iata.startswith(query_upper):
            score = 60
        # İçerik eşleşmesi
        elif query_upper in name:
            score = 40
        elif query_upper in city:
            score = 30

        if score > 0:
            # Büyük havalimanlarına bonus
            if airport.get("type") == "large_airport":
                score += 15

            results.append({**airport, "_score": score})

    # Skora göre sırala, limit uygula
    results.sort(key=lambda x: x["_score"], reverse=True)
    results = [{k: v for k, v in r.items() if k != "_score"} for r in results[:limit]]

    cache.set("airport", cache_key, results)
    return results


def get_nearby_airports(lat: float, lon: float, radius_nm: float = 100) -> list:
    """Belirli koordinata yakın havalimanlarını döndürür."""
    _load_airports()

    nearby = []
    for airport in _airports_db.values():
        dist = haversine_nm(lat, lon, airport["latitude"], airport["longitude"])
        if dist <= radius_nm:
            nearby.append({**airport, "distance_nm": round(dist, 1)})

    nearby.sort(key=lambda x: x["distance_nm"])
    return nearby


def get_turkey_airports() -> list:
    """Tüm Türkiye havalimanlarını döndürür (geriye uyumluluk)."""
    _load_airports()
    return [a for a in _airports_db.values() if a.get("country") == "TR"]


def get_corridor_airports(
    lat1: float, lon1: float, lat2: float, lon2: float,
    radius_nm: float = 200,
) -> list:
    """
    İki nokta arasındaki uçuş koridorundaki havalimanlarını döndürür.
    Great-circle rota üzerindeki birden fazla noktaya yakın olanlar dahil edilir.
    Antimeridian-crossing rotaları (JFK→Tokyo gibi) doğru işler.
    """
    _load_airports()
    from utils.geo import great_circle_waypoints

    # Great-circle üzerinde 5 örnekleme noktası
    gc_points = great_circle_waypoints(lat1, lon1, lat2, lon2, num_points=5)

    found = {}
    for gc_lat, gc_lon in gc_points:
        for airport in _airports_db.values():
            if airport["icao"] in found:
                continue
            dist = haversine_nm(gc_lat, gc_lon, airport["latitude"], airport["longitude"])
            if dist <= radius_nm:
                found[airport["icao"]] = airport

    return list(found.values())


def get_all_airports_count() -> int:
    """Yüklü havalimanı sayısını döndürür."""
    _load_airports()
    return len(_airports_db)
