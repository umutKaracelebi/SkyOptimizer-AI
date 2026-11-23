"""
SkyOptimizer AI — Kısıtlı / Yasak Hava Sahası Servisi

Statik GeoJSON'dan (varsayılan: data/restricted_airspaces.geojson)
yasak (prohibited) ve sınırlı (restricted) sahaları yükler; rota
kenarlarının bu sahalardan geçmesini engeller.

ÖNEMLİ: Paket içindeki veri seti küçük ve gösterim amaçlıdır (FAA SUA
kaynaklı dört saha). Gerçek operasyonel kapsam için ulusal AIP/OpenAIP
verisi `RESTRICTED_AIRSPACE_FILE` ortam değişkeniyle bu dosyanın yerine
yüklenmelidir. Bu sınırlama API yanıtında da raporlanır.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

DATA_DIR = Path(__file__).parent.parent / "data"
DEFAULT_FILE = DATA_DIR / "restricted_airspaces.geojson"


def _airspace_path() -> Path:
    env_path = os.getenv("RESTRICTED_AIRSPACE_FILE", "").strip()
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    return DEFAULT_FILE


def _point_in_ring(lat: float, lon: float, ring: list) -> bool:
    """Ray casting — ring [[lon, lat], ...] kapalı çokgen."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > lat) != (yj > lat)):
            x_cross = (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi
            if lon < x_cross:
                inside = not inside
        j = i
    return inside


@lru_cache(maxsize=1)
def load_airspaces() -> tuple:
    """
    GeoJSON'u yükler. Dönüş: (features, meta) — features demet olarak
    cache'lenir, her eleman:
        {"id", "name", "type", "floor", "ceiling",
         "rings": [[(lon, lat), ...], ...], "bbox": (minlon, minlat, maxlon, maxlat)}
    """
    path = _airspace_path()
    if not path.exists():
        return tuple(), {"source": str(path), "count": 0, "available": False}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[UYARI] Kısıtlı hava sahası okunamadı: {exc}")
        return tuple(), {"source": str(path), "count": 0, "available": False}

    features = []
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Polygon":
            continue
        rings = geom.get("coordinates") or []
        if not rings:
            continue
        lons = [pt[0] for pt in rings[0]]
        lats = [pt[1] for pt in rings[0]]
        props = feature.get("properties") or {}
        features.append({
            "id": props.get("id") or props.get("name") or "UNKNOWN",
            "name": props.get("name") or "Kısıtlı saha",
            "type": props.get("type") or "restricted",
            "floor": props.get("floor"),
            "ceiling": props.get("ceiling"),
            "source": props.get("source"),
            "rings": [tuple(map(tuple, ring)) for ring in rings],
            "bbox": (min(lons), min(lats), max(lons), max(lats)),
        })

    meta = {
        "source": str(path),
        "file": path.name,
        "count": len(features),
        "available": bool(features),
        "note": (data.get("metadata") or {}).get("note", ""),
        "demo": bool((data.get("metadata") or {}).get("description", "").startswith(
            "SkyOptimizer"
        )),
    }
    return tuple(features), meta


def airspace_meta() -> dict:
    """Veri seti hakkında özet (API yanıtı ve arayüz için)."""
    features, meta = load_airspaces()
    return {**meta, "features": [
        {
            "id": f["id"], "name": f["name"], "type": f["type"],
            "floor": f["floor"], "ceiling": f["ceiling"], "source": f["source"],
        }
        for f in features
    ]}


def feature_geojson() -> dict:
    """Harita katmanı için ham GeoJSON."""
    path = _airspace_path()
    if not path.exists():
        return {"type": "FeatureCollection", "features": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"type": "FeatureCollection", "features": []}


def point_blocked(lat: float, lon: float) -> Optional[dict]:
    """Nokta herhangi bir sahanın içinde mi? İlk eşleşen sahayı döndürür."""
    features, _ = load_airspaces()
    for feature in features:
        min_lon, min_lat, max_lon, max_lat = feature["bbox"]
        if not (min_lat <= lat <= max_lat and min_lon <= lon <= max_lon):
            continue
        if _point_in_ring(lat, lon, feature["rings"][0]):
            return {
                "id": feature["id"],
                "name": feature["name"],
                "type": feature["type"],
            }
    return None


def segment_blocked(
    lat1: float, lon1: float, lat2: float, lon2: float,
    samples: int = 5,
) -> Optional[dict]:
    """
    İki nokta arasındaki kenar bir sahayı kesiyor mu?

    Kenar üzerinde `samples` nokta test edilir. Rota grafındaki kenarlar
    kısa (≤350 NM) olduğu için 5 örnek yeterlidir; her testte önce bbox
    kontrolü yapılır, bu yüzden saha yoksa maliyet ~sıfırdır.
    """
    features, _ = load_airspaces()
    if not features:
        return None

    # Hızlı bbox ön filtresi: kenar bbox'ı hiçbir sahayla kesişmiyorsa çık
    edge_min_lat, edge_max_lat = min(lat1, lat2), max(lat1, lat2)
    edge_min_lon, edge_max_lon = min(lon1, lon2), max(lon1, lon2)
    candidates = [
        f for f in features
        if not (
            f["bbox"][3] < edge_min_lat or f["bbox"][1] > edge_max_lat
            or f["bbox"][2] < edge_min_lon or f["bbox"][0] > edge_max_lon
        )
    ]
    if not candidates:
        return None

    # Antimeridian geçişlerinde boylam farkını kısalt
    dlon = lon2 - lon1
    if dlon > 180:
        dlon -= 360
    elif dlon < -180:
        dlon += 360

    for k in range(samples + 1):
        t = k / samples
        lat = lat1 + (lat2 - lat1) * t
        lon = ((lon1 + dlon * t + 180) % 360) - 180
        for feature in candidates:
            if _point_in_ring(lat, lon, feature["rings"][0]):
                return {
                    "id": feature["id"],
                    "name": feature["name"],
                    "type": feature["type"],
                }
    return None


def relevant_features(
    origin: tuple, destination: tuple, padding_deg: float = 2.0,
) -> list:
    """Rota bbox'ı ile kesişen sahalar (harita/rapor için)."""
    features, _ = load_airspaces()
    if not features:
        return []

    (lat1, lon1), (lat2, lon2) = origin, destination
    min_lat, max_lat = min(lat1, lat2) - padding_deg, max(lat1, lat2) + padding_deg
    min_lon, max_lon = min(lon1, lon2) - padding_deg, max(lon1, lon2) + padding_deg

    return [
        {
            "id": f["id"], "name": f["name"], "type": f["type"],
            "floor": f["floor"], "ceiling": f["ceiling"],
            "bbox": f["bbox"],
        }
        for f in features
        if not (
            f["bbox"][3] < min_lat or f["bbox"][1] > max_lat
            or f["bbox"][2] < min_lon or f["bbox"][0] > max_lon
        )
    ]
