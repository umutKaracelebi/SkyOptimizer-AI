# ✈️ SkyOptimizer AI

**Yapay Zekâ Destekli Uçuş Rota Optimizasyon Sistemi**

> **İnoTürk** ekibi tarafından Deneyap Takımlaşma Projesi kapsamında geliştirilmiştir.
>
> Sivil havacılıkta sabit hava koridorlarının yarattığı zaman ve yakıt kayıplarını minimize etmek için
> ADS-B, canlı meteoroloji ve üst seviye rüzgâr verilerini kullanarak optimum uçuş rotaları hesaplayan
> akıllı bir sistem.

---

## 🌟 Özellikler

| Özellik | Açıklama |
|---------|----------|
| 🛫 **ADS-B Canlı Takip** | OpenSky Network üzerinden gerçek zamanlı uçak pozisyonları |
| 🌦️ **Meteoroloji Entegrasyonu** | METAR, TAF raporları + NOAA GFS üst seviye rüzgâr (300 hPa ≈ FL300) |
| 🤖 **A\* Rota Optimizasyonu** | NetworkX graf + A\* pathfinding ile rüzgâr-optimizasyonlu rota |
| 🧠 **PyTorch Derin Öğrenme** | 4 gizli katmanlı DNN ile yakıt/süre/CO₂ tahminleri (RTX 4070 CUDA) |
| ⛽ **OpenAP Yakıt Modeli** | Gerçek uçak performans verileriyle fizik tabanlı maliyet hesabı |
| 🗺️ **İnteraktif Harita** | Leaflet dark theme harita + optimize vs standart rota karşılaştırma |
| 📊 **Dashboard** | Tasarruf sayaçları, AI vs Fizik karşılaştırma, birikimli istatistikler |
| 🌍 **5.278 Havalimanı** | OurAirports veritabanı ile küresel havalimanı desteği |

---

## 🏗️ Mimari

```mermaid
graph TB
    subgraph Frontend["Frontend (React + TypeScript)"]
        HP[Ana Sayfa<br/>D3.js Globe]
        OP[Optimizer Sayfası<br/>Leaflet Harita]
        AP[Hakkında Sayfası]
        SP[StatsPanel]
    end

    subgraph Backend["Backend (FastAPI)"]
        API[REST API Endpoints]
        AS[Airport Service<br/>5.278 havalimanı]
        WS[Weather Service<br/>METAR / TAF]
        WIND[Wind Service<br/>FL300 rüzgâr]
        ADSB[ADS-B Service<br/>OpenSky Network]
    end

    subgraph Optimization["Optimizasyon Motoru"]
        GB[Graph Builder<br/>NetworkX]
        CM[Cost Model<br/>OpenAP]
        ASTAR[A* Pathfinding]
    end

    subgraph ML["Yapay Zekâ"]
        DC[Data Collector<br/>50K eğitim verisi]
        TM[Train Model<br/>PyTorch DNN]
        MP[ML Predictor<br/>Inference]
    end

    OP --> API
    API --> AS & WS & WIND & ADSB
    API --> ASTAR
    ASTAR --> GB & CM
    API --> MP
    DC --> TM --> MP

    style Frontend fill:#0e1a2b,color:#00d4ff,stroke:#00d4ff
    style Backend fill:#1a0e2b,color:#a855f7,stroke:#a855f7
    style Optimization fill:#0e2b1a,color:#10b981,stroke:#10b981
    style ML fill:#2b1a0e,color:#f59e0b,stroke:#f59e0b
```

---

## 🚀 Kurulum

### Gereksinimler

- **Python** 3.10+
- **Node.js** 18+
- **NVIDIA GPU** (opsiyonel — CUDA 11.8+ model eğitimi için)

### 1. Repo'yu klonlayın

```bash
git clone https://github.com/<user>/deneyap-takimlasma-proje.git
cd deneyap-takimlasma-proje
```

### 2. Backend kurulumu

```bash
cd backend

# Sanal ortam oluştur
python -m venv venv
.\venv\Scripts\activate    # Windows
# source venv/bin/activate  # macOS/Linux

# Bağımlılıkları kur
pip install -r requirements.txt

# GPU ile model eğitimi (opsiyonel)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

### 3. API Anahtarları

Proje kökünde aşağıdaki dosyaları oluşturun:

**`credentials.json`**
```json
{
  "clientId": "YOUR_OPENSKY_CLIENT_ID",
  "clientSecret": "YOUR_OPENSKY_CLIENT_SECRET"
}
```

**`openweatherapi.txt`**
```
YOUR_OPENWEATHERMAP_API_KEY
```

### 4. ML Model eğitimi (opsiyonel)

```bash
cd backend

# Eğitim verisi üret (200.000 satır)
.\venv\Scripts\python ml\data_collector.py

# Model eğit (GPU varsa ~1-2 dk)
.\venv\Scripts\python ml\train_model.py
```

### 5. Frontend kurulumu

```bash
cd frontend
npm install
```

### 6. Çalıştırma

```bash
# Terminal 1 — Backend (port 8000)
cd backend
.\venv\Scripts\python -m uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend (port 5173)
cd frontend
npm run dev
```

Tarayıcıda `http://localhost:5173` adresine gidin.

---

## 📡 API Endpoints

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `GET` | `/health` | Sistem sağlık kontrolü |
| `GET` | `/api/status` | API limit ve cache istatistikleri |
| `GET` | `/api/airports/search?q=istanbul` | Havalimanı arama |
| `GET` | `/api/airports/{icao}` | Havalimanı detayı |
| `GET` | `/api/airports/turkey/all` | Tüm Türkiye havalimanları |
| `GET` | `/api/weather/{icao}` | METAR + TAF hava durumu |
| `GET` | `/api/winds?lat=39&lon=35` | Üst seviye rüzgâr (300 hPa, Open-Meteo/GFS) |
| `GET` | `/api/flights/live` | Canlı ADS-B uçuş verileri |
| `GET` | `/api/traffic` | Türkiye hava sahası trafik özeti |
| `POST` | `/api/optimize` | A* ile optimum rota hesapla |
| `POST` | `/api/compare` | Standart vs optimize rota karşılaştır |
| `POST` | `/api/predict` | AI modeli ile yakıt/süre/CO₂ tahmini |

---

## 🧠 Optimizasyon Algoritması

### A* Pathfinding

1. İki havalimanı arasında **great-circle** hattı çizilir
2. Hat üzerinde **waypoint**'ler + rota ekseninin sağına/soluna **koridor** sapma noktaları eklenir
   (koridor genişliği rotaya göre değişir: kısa rotada ±10–60 NM, transatlantikte ±200 NM)
3. **NetworkX** graf oluşturulur (düğüm/kenar sayısı rotaya göre değişir — ör. LTFM→EGLL için ~560 düğüm / ~100 bin kenar)
4. Her kenar için **OpenAP** yakıt modeli + gerçek rüzgâr bileşenleri ile maliyet hesaplanır
   (cruise yakıt akışı sabit olduğu için bir kez hesaplanır — rota başına ~2 sn)
5. **İki rota AYNI graf, AYNI rüzgâr ve AYNI fizik motoruyla** aranır; tek fark hedeftir:
   - **Standart rota** → en kısa mesafe (`distance_nm`)
   - **Optimize rota** → en düşük **kompozit maliyet**: `Yakıt %40 + Süre %35 + CO₂ %25`
6. Kompozit maliyet, standart rotanın toplamlarına göre normalize edilir; böylece
   standart rotanın maliyeti tam `1.0` olur ve ağırlık kaydırıcıları gerçekten etki eder
7. Tasarruf = standart − optimize. Optimize rota **daha uzun ama daha az yakıtlı** olabilir;
   bu durum `distance_delta_nm` ile açıkça raporlanır. Rüzgâr yoksa iki rota çakışır ve
   `has_measurable_savings: false` döner — yapay tasarruf üretilmez.

### PyTorch DNN Modeli

- **Mimari**: 7 → 512 → 256 → 128 → 64 → 3 nöron (LeakyReLU + BatchNorm)
- **Eğitim verisi**: 200.000 örnek (CostModel ile üretilmiş sentetik segment)
- **Not**: Model, fizik motorunun çıktısını taklit eden bir *surrogate* modeldir;
  fizik motorundan daha iyi olduğu iddia edilmez. `/api/predict` iki sonucu yan yana
  ve aradaki sapmayı (`ai_vs_physics_error_percent`) döndürür.
- **Özellikler**: mesafe, rüzgâr hızı/yönü, heading, irtifa, headwind, crosswind
- **Çıktılar**: yakıt (kg), süre (dk), CO₂ (kg)
- **Cihaz**: NVIDIA RTX 4070 (CUDA)

---

## 🧪 Testler

```bash
cd backend
venv/Scripts/python.exe -m pytest tests/ -v
```

21 smoke testi ağ erişimi olmadan çalışır: havalimanı veritabanı (5.278 kayıt),
graf kurulumu, OpenAP maliyet modeli, A*'ın iki rotayı da aynı rüzgârla hesapladığı,
rüzgârsız durumda tasarruf üretmediği, API rota sırası ve ML tahmininin
deterministik olduğu doğrulanır.

---

## 📂 Proje Yapısı

```
deneyap-takimlasma-proje/
├── credentials.json              # OpenSky API credentials
├── openweatherapi.txt            # OpenWeatherMap API key
├── README.md
│
├── backend/
│   ├── main.py                   # FastAPI sunucu
│   ├── config.py                 # API key yönetimi
│   ├── requirements.txt
│   ├── requirements-dev.txt      # pytest
│   ├── services/
│   │   ├── airport_service.py    # 5.278 havalimanı DB
│   │   ├── adsb_service.py       # OpenSky canlı trafik
│   │   ├── weather_service.py    # METAR/TAF
│   │   ├── wind_service.py       # Üst seviye rüzgâr
│   │   └── cache_manager.py      # Cache + rate limiter
│   ├── optimization/
│   │   ├── graph_builder.py      # NetworkX graf
│   │   ├── cost_model.py         # OpenAP yakıt modeli
│   │   ├── astar.py              # A* pathfinding
│   │   └── ml_predictor.py       # PyTorch inference
│   ├── ml/
│   │   ├── data_collector.py     # Eğitim verisi üretici
│   │   ├── train_model.py        # PyTorch DNN eğitimi
│   │   ├── flight_data.csv       # 50K eğitim verisi
│   │   ├── model.pt              # Eğitilmiş model
│   │   └── scaler.pkl            # Normalizasyon parametreleri
│   ├── tests/
│   │   └── test_smoke.py         # 21 smoke testi (ağ gerektirmez)
│   └── utils/
│       └── geo.py                # Haversine, great-circle
│
└── frontend/
    ├── src/
    │   ├── App.tsx               # React Router
    │   ├── index.css             # Tailwind + cyber-aviation tema
    │   ├── pages/
    │   │   ├── HomePage.tsx      # D3.js globe hero
    │   │   ├── OptimizerPage.tsx  # Harita + optimizasyon
    │   │   └── AboutPage.tsx
    │   ├── services/
    │   │   └── api.ts            # TypeScript API client
    │   └── components/ui/
    │       ├── StatsPanel.tsx     # Birikimli tasarruf sayaçları
        │       ├── hero-globe.tsx     # Globe hero bileşeni
    │       └── wireframe-dotted-globe.tsx  # D3.js dönen dünya
    └── package.json
```

---

## 🔧 Teknolojiler

| Katman | Teknoloji |
|--------|-----------|
| Backend | Python, FastAPI, uvicorn |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS 3 |
| Harita | Leaflet, react-leaflet, Esri World Dark Gray (anahtarsız) |
| Optimizasyon | NetworkX, A* pathfinding, OpenAP |
| Yapay Zekâ | PyTorch, CUDA, scikit-learn |
| Veri Kaynakları | OpenSky Network, AviationWeather.gov, Open-Meteo (GFS), OpenWeatherMap (yedek), OurAirports |
| Animasyonlar | D3.js (globe), CSS animations, Lucide icons |

---

## 📋 Proje Bilgisi

<table>
  <tbody>
    <tr>
      <td><strong>Geliştirici Takım</strong></td>
      <td><strong>İnoTürk</strong></td>
    </tr>
    <tr>
      <td><strong>Program</strong></td>
      <td>Deneyap Takımlaşma Projesi 2026</td>
    </tr>
    <tr>
      <td><strong>Lisans</strong></td>
      <td>MIT</td>
    </tr>
  </tbody>
</table>

---

*SkyOptimizer AI — Daha akıllı rotalar, daha az yakıt, daha temiz gökyüzü.* ✈️🌍
