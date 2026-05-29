"""
SkyOptimizer AI — Cache Yöneticisi
API isteklerini önbellekler ve rate limiting uygular.
OpenSky günlük 4000 istek limitini takip eder.
"""

import time
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Optional

from cachetools import TTLCache

from config import (
    OPENSKY_CACHE_TTL,
    OPENSKY_DAILY_LIMIT,
    OPENSKY_MIN_INTERVAL_SEC,
    WEATHER_CACHE_TTL,
    WIND_CACHE_TTL,
    AIRPORT_CACHE_TTL,
)


class APIRateLimiter:
    """API istek hız sınırlayıcı ve günlük kota takipçisi."""

    def __init__(self, daily_limit: int, min_interval: float):
        self.daily_limit = daily_limit
        self.min_interval = min_interval
        self.request_count = 0
        self.last_request_time = 0.0
        self.reset_date = datetime.now(timezone.utc).date()

    def _check_daily_reset(self):
        """Gün değiştiyse sayacı sıfırla."""
        today = datetime.now(timezone.utc).date()
        if today > self.reset_date:
            self.request_count = 0
            self.reset_date = today

    def can_request(self) -> bool:
        """İstek yapılıp yapılamayacağını kontrol et."""
        self._check_daily_reset()
        if self.request_count >= self.daily_limit:
            return False
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            return False
        return True

    def wait_if_needed(self):
        """Gerekirse minimum aralık süresince bekle."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)

    def record_request(self):
        """Yapılan isteği kaydet."""
        self._check_daily_reset()
        self.request_count += 1
        self.last_request_time = time.time()

    @property
    def remaining_requests(self) -> int:
        """Kalan günlük istek sayısı."""
        self._check_daily_reset()
        return max(0, self.daily_limit - self.request_count)

    @property
    def status(self) -> dict:
        """Mevcut durum bilgisi."""
        self._check_daily_reset()
        return {
            "daily_limit": self.daily_limit,
            "requests_today": self.request_count,
            "remaining": self.remaining_requests,
            "reset_date": self.reset_date.isoformat(),
            "can_request": self.can_request(),
        }


class CacheManager:
    """Çoklu TTL cache yöneticisi."""

    def __init__(self):
        self.caches = {
            "opensky": TTLCache(maxsize=500, ttl=OPENSKY_CACHE_TTL),
            "weather": TTLCache(maxsize=200, ttl=WEATHER_CACHE_TTL),
            "wind": TTLCache(maxsize=100, ttl=WIND_CACHE_TTL),
            "airport": TTLCache(maxsize=1000, ttl=AIRPORT_CACHE_TTL),
        }
        self._hit_count = 0
        self._miss_count = 0

    def get(self, cache_name: str, key: str) -> Optional[Any]:
        """Cache'den veri al."""
        cache = self.caches.get(cache_name)
        if cache is None:
            return None
        value = cache.get(key)
        if value is not None:
            self._hit_count += 1
        else:
            self._miss_count += 1
        return value

    def set(self, cache_name: str, key: str, value: Any):
        """Cache'e veri yaz."""
        cache = self.caches.get(cache_name)
        if cache is not None:
            cache[key] = value

    def clear(self, cache_name: Optional[str] = None):
        """Cache temizle (belirli veya tümü)."""
        if cache_name:
            cache = self.caches.get(cache_name)
            if cache:
                cache.clear()
        else:
            for cache in self.caches.values():
                cache.clear()

    @property
    def stats(self) -> dict:
        """Cache istatistikleri."""
        total = self._hit_count + self._miss_count
        return {
            "hit_count": self._hit_count,
            "miss_count": self._miss_count,
            "hit_rate": f"{(self._hit_count / total * 100):.1f}%" if total > 0 else "N/A",
            "cache_sizes": {
                name: len(cache) for name, cache in self.caches.items()
            },
        }


# ─── Singleton Instances ────────────────────────────────────────────
opensky_limiter = APIRateLimiter(
    daily_limit=OPENSKY_DAILY_LIMIT,
    min_interval=OPENSKY_MIN_INTERVAL_SEC,
)

cache = CacheManager()
