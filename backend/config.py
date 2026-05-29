"""
SkyOptimizer AI — Yapılandırma Modülü
Proje kök dizinindeki credentials.json ve openweatherapi.txt dosyalarından
API anahtarlarını okur.
"""

import json
import os
from pathlib import Path

# Proje kök dizini (backend/ klasörünün bir üstü)
PROJECT_ROOT = Path(__file__).parent.parent

# ─── OpenSky Network Credentials ────────────────────────────────────
_credentials_path = PROJECT_ROOT / "credentials.json"
if _credentials_path.exists():
    with open(_credentials_path, "r") as f:
        _creds = json.load(f)
    OPENSKY_CLIENT_ID = _creds.get("clientId", "")
    OPENSKY_CLIENT_SECRET = _creds.get("clientSecret", "")
else:
    OPENSKY_CLIENT_ID = os.getenv("OPENSKY_CLIENT_ID", "")
    OPENSKY_CLIENT_SECRET = os.getenv("OPENSKY_CLIENT_SECRET", "")

# ─── OpenWeatherMap API Key ─────────────────────────────────────────
_owm_path = PROJECT_ROOT / "openweatherapi.txt"
if _owm_path.exists():
    with open(_owm_path, "r") as f:
        OPENWEATHER_API_KEY = f.read().strip()
else:
    OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

# ─── API Endpoints ──────────────────────────────────────────────────
OPENSKY_BASE_URL = "https://opensky-network.org/api"
OPENSKY_TOKEN_URL = "https://opensky-network.org/api/oauth/token"
AVIATION_WEATHER_BASE_URL = "https://aviationweather.gov/api/data"
OPENWEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5"
NOAA_GFS_BASE_URL = "https://nomads.ncep.noaa.gov"

# ─── Rate Limiting & Cache ──────────────────────────────────────────
OPENSKY_DAILY_LIMIT = 4000           # Günlük maksimum istek sayısı
OPENSKY_MIN_INTERVAL_SEC = 5         # İstekler arası minimum süre (saniye)
OPENSKY_CACHE_TTL = 900              # 15 dakika (saniye)
WEATHER_CACHE_TTL = 300              # 5 dakika
WIND_CACHE_TTL = 21600               # 6 saat (GFS güncelleme periyodu)
AIRPORT_CACHE_TTL = 86400            # 24 saat

# ─── Varsayılan Uçak Performans Parametreleri ───────────────────────
DEFAULT_AIRCRAFT = "B738"            # Boeing 737-800
DEFAULT_CRUISE_ALTITUDE_FT = 35000   # Cruise irtifası (feet)
DEFAULT_CRUISE_SPEED_KTS = 460       # Cruise hızı (knots TAS)
DEFAULT_MASS_KG = 65000              # Ortalama uçuş kütlesi

# ─── Varsayılan Harita Görünümü ─────────────────────────────────────
DEFAULT_MAP_VIEW = {
    "center_lat": 30.0,
    "center_lon": 0.0,
    "zoom": 3,
}

# ─── Türkiye Hava Sahası Sınırları (trafik verisi için) ─────────────
TURKEY_BBOX = {
    "lamin": 35.8,   # Güney sınır (enlem)
    "lamax": 42.2,   # Kuzey sınır
    "lomin": 25.5,   # Batı sınır (boylam)
    "lomax": 44.8,   # Doğu sınır
}

# ─── Global Hub Havalimanları ───────────────────────────────────────
GLOBAL_HUB_AIRPORTS = [
    # Türkiye
    "LTFM", "LTAI", "LTAC", "LTBJ",
    # Avrupa
    "EGLL", "LFPG", "EDDF", "EHAM", "LEMD", "LIRF",
    # Kuzey Amerika
    "KJFK", "KLAX", "KORD", "KATL", "KDFW",
    # Asya
    "OMDB", "VHHH", "RJTT", "RKSI", "WSSS",
    # Diğer
    "YSSY", "FAOR", "SBGR",
]

# ─── CORS ────────────────────────────────────────────────────────────
CORS_ORIGINS = [
    "http://localhost:5173",    # Vite dev server
    "http://localhost:3000",    # Alternatif
    "http://127.0.0.1:5173",
]
