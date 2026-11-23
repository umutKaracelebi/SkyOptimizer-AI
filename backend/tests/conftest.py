"""
pytest yapılandırması — backend kökünü sys.path'e ekler, SQLite birikim
dosyasını geçici bir yola yönlendirir ve ağ çağrılarını varsayılan olarak
kapatmaz (testler kendi monkeypatch'lerini kurar).
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Testler gerçek birikim veritabanını kirletmesin
_TMP_DB = Path(tempfile.gettempdir()) / "skyoptimizer_test_savings.db"
os.environ.setdefault("SAVINGS_DB_PATH", str(_TMP_DB))
if _TMP_DB.exists():
    _TMP_DB.unlink()
