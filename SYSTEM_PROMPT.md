# SkyOptimizer AI — Sistem Prompt Dokümanı

## 🎯 Proje Tanımı

**SkyOptimizer AI**, yapay zekâ ve fizik tabanlı modelleri birleştirerek uçuş rotalarını optimize eden, gerçek zamanlı hava durumu verisiyle çalışan akıllı bir uçuş rota optimizasyon sistemidir. Sistem, herhangi iki havalimanı arasında en yakıt-verimli rotayı hesaplar ve standart rota ile karşılaştırarak tasarruf analizi sunar.

---

## 🏗️ Mimari Genel Bakış

### Teknoloji Yığını

| Katman | Teknoloji |
|--------|-----------|
| **Frontend** | React 18 + TypeScript + Vite |
| **Backend** | Python 3.11 + FastAPI + Uvicorn |
| **Optimizasyon** | NetworkX (graf), A* algoritması |
| **Fizik Motoru** | OpenAP (yakıt akışı, emisyon, uçak performansı) |
| **Yapay Zekâ** | PyTorch DNN (512→256→128→64→3 nöron) |
| **Hava Verisi** | Open-Meteo API (üst seviye rüzgâr, METAR, TAF) |
| **Canlı Uçuş** | OpenSky Network ADS-B API |
| **3D Görselleştirme** | Three.js (dönen dünya, dotted surface) |
| **Eğitim Donanımı** | NVIDIA RTX 4070 (CUDA) |

---

## 🔄 Optimizasyon Pipeline'ı (6 Adım)

```
[1] Havalimanı Seçimi → [2] Rüzgâr Taraması → [3] Graf Oluşturma
        ↓                       ↓                       ↓
[6] Tasarruf Raporu ← [5] AI Doğrulama ← [4] A* Optimizasyon
```

### Adım 1: Havalimanı Seçimi
- Kullanıcı kalkış ve varış ICAO kodlarını girer (örn: LTFM → EGLL)
- 5.278 havalimanı veritabanından eşleşme yapılır
- Koordinat, yükseklik, pist bilgisi çekilir

### Adım 2: Rüzgâr Taraması
- Rota boyunca **7 nokta** × **3 koridor ofseti** = **21 rüzgâr örneği** toplanır
- Open-Meteo API'den **NOAA GFS** modeliyle 300 hPa (~FL300) üst seviye rüzgâr verisi alınır
- 21 örnek **tek HTTP isteğinde** çekilir (Open-Meteo çoklu koordinat destekler)
- Open-Meteo erişilemezse OpenWeatherMap yüzey rüzgârından tahmine düşülür ve
  `source: owm_extrapolated` ile işaretlenir
- Rüzgâr hızı (kts) ve yönü (°) kaydedilir
- Koridor ofsetleri: merkez hat ± 0.8° (~48 NM) dik sapma

### Adım 3: Graf Oluşturma (NetworkX DiGraph)
- **Düğüm Tipleri:**
  - `airport` — Kalkış, varış ve koridor havalimanları
  - `waypoint` (WP) — Great-circle üzerinde ~100 NM aralıklarla oluşturulan ara noktalar
  - `corridor` (COR) — Her WP'den ±25-60 NM dik ofsette oluşturulan alternatif noktalar
- **Kenar Oluşturma:**
  - `effective_max_edge = total_distance × 0.35` ile mesafe sınırı
  - Doğrudan Origin→Destination kenarı engellenir (ara düğüm kullanımı zorunlu)
  - Her kenar: mesafe (NM), bearing (°), yakıt (kg), süre (dk), CO₂ (kg) bilgisi taşır

### Adım 4: A* Optimizasyon (Tek Graf, İki Hedef)

İki rota **aynı graf, aynı rüzgâr verisi ve aynı fizik motoruyla** aranır.
Tek fark amaç fonksiyonudur — karşılaştırmanın dürüstlüğü buna dayanır.

#### Standart Rota
- **Ağırlık:** `distance_nm` (en kısa mesafe)
- **Heuristic:** Haversine (admissible)
- **Anlam:** Rüzgâr optimizasyonu yapmayan pilotun en kısa yol rotası
- **Yakıt/süre:** Gerçek rüzgârla, optimize rota ile **aynı** kenar maliyetlerinden hesaplanır

#### Optimize Rota
- **Ağırlık:** `composite_cost` (yakıt×0.40 + süre×0.35 + CO₂×0.25)
- **Heuristic:** Haversine × (kenar başına en düşük maliyet) — admissible ve consistent
- **Normalizasyon:** Her bileşen standart rotanın toplamına bölünür; standart rotanın
  kompozit maliyeti tam 1.0 olur, optimize rota ≤ 1.0 bulur. Bu sayede arayüzdeki
  ağırlık kaydırıcıları gerçekten etki eder.
- **Anlam:** Rüzgârı hesaba katarak en verimli yolu bulan rota

> **Tasarruf sıfır çıkabilir.** Rüzgâr yoksa iki rota çakışır ve `has_measurable_savings: false`
> döner. %0.1'in altındaki farklar gürültü sayılır ve kazanç olarak sunulmaz.
> Optimize rota **daha uzun ama daha az yakıtlı** olabilir; `distance_delta_nm` bunu raporlar.

### Adım 5: AI Doğrulama (PyTorch DNN)
- Eğitilmiş model ayrıca yakıt/süre/CO₂ tahmini yapar
- Fizik motoru (OpenAP) sonucuyla karşılaştırılır
- Model mimarisi: `7 input → 512 → 256 → 128 → 64 → 3 output`
- Aktivasyon: LeakyReLU(0.01) + BatchNorm
- Eğitim verisi: 200.000 sentetik uçuş segmenti (flight_data.csv, ~14 MB)
- **Surrogate model:** Model, CostModel çıktısıyla eğitildiği için fizik motorunu
  taklit eder; fizikten daha iyi olduğu iddia edilmez. `/api/predict` iki sonucu ve
  aralarındaki sapmayı (`ai_vs_physics_error_percent`) döndürür — ölçülen sapma %0.1-0.5.
  AI sonucu hiçbir şekilde fizik sonucuna göre "iyileştirilmez".

### Adım 6: Tasarruf Raporu
- Standart vs Optimize karşılaştırması
- Hesaplanan metrikler:
  - Yakıt tasarrufu (kg ve %)
  - Süre tasarrufu (dk ve %)
  - CO₂ emisyon azaltması (kg)
  - Maliyet tasarrufu (USD, $0.80/kg JetA1)

---

## ⚙️ Fizik Motoru (CostModel)

### OpenAP Entegrasyonu
```
Yakıt Akışı = FuelFlow(aircraft_type).enroute(mass, TAS, altitude)
CO₂ Emisyon = fuel_kg × 3.16 (JetA1 karbon faktörü)
```

### Rüzgâr Etkisi
```
Headwind = wind_speed × cos(wind_direction - aircraft_heading)
Ground Speed = TAS - Headwind
Segment Time = distance / ground_speed × 60
Segment Fuel = fuel_flow × (segment_time / 60)
```

### Composite Maliyet Fonksiyonu
```
ref       = standart rotanın toplamları (fuel_kg, time_min, co2_kg)
cost_edge = w_fuel × (fuel_edge / ref_fuel)
          + w_time × (time_edge / ref_time)
          + w_co2  × (co2_edge  / ref_co2)

Varsayılan ağırlıklar: w_fuel=0.40, w_time=0.35, w_co2=0.25 (toplam 1'e normalize edilir)
```

Kenar maliyetleri **yuvarlanmaz** — yuvarlama A*'ın maliyet fonksiyonuna gürültü
ekliyordu. Yuvarlama yalnızca sunum katmanında (API yanıtı) yapılır.

---

## 🌐 API Endpoint'leri

| Method | Endpoint | Açıklama |
|--------|----------|----------|
| `GET` | `/health` | Sistem sağlık kontrolü |
| `GET` | `/api/airports/search?q=` | Havalimanı arama (ICAO/isim) |
| `GET` | `/api/airports/{icao}` | Tek havalimanı detayı |
| `POST` | `/api/optimize` | Rota optimizasyonu (A* + rüzgâr) |
| `POST` | `/api/predict` | AI model tahmini |
| `POST` | `/api/compare` | Standart vs optimize karşılaştırma |
| `GET` | `/api/weather/metar/{icao}` | METAR hava durumu |
| `GET` | `/api/weather/taf/{icao}` | TAF hava tahmini |
| `POST` | `/api/winds/upper` | Üst seviye rüzgâr verisi |
| `GET` | `/api/flights/live` | Canlı ADS-B uçuş verisi |

---

## 🖥️ Frontend Yapısı

### Sayfalar
- **HomePage** — 3D dönen dünya + hero section + pipeline animasyonu
- **OptimizerPage** — Rota optimizasyon arayüzü (harita, istatistik, karşılaştırma)
- **AboutPage** — Proje hakkında bilgi

### Bileşenler
- `hero-globe.tsx` — Three.js wireframe dünya + DottedSurface yerçekimi efekti
- `StatsPanel.tsx` — Yakıt/süre/CO₂ tasarruf kartları
- `ComparePanel.tsx` — AI vs Fizik motoru karşılaştırma tablosu
- `dotted-surface.tsx` — Three.js noktalı yüzey (gravity well efekti)
- `wireframe-dotted-globe.tsx` — Dönen noktalı dünya küresi

### Tasarım Dili
- **Tema:** Koyu (dark mode), siber-havacılık estetiği
- **Renkler:** Cyan (#00D4FF), siyah arka plan, cam efekti (glassmorphism)
- **Tipografi:** Mono font (JetBrains Mono / system-ui)
- **Animasyonlar:** Glow-pulse, border-glow, float, scanline, count-up

---

## 📊 Veri Akışı

```
Kullanıcı (ICAO giriş)
    │
    ▼
Frontend (React) ──POST /api/optimize──▶ Backend (FastAPI)
    │                                         │
    │                                    ┌────┴─────┐
    │                                    ▼          ▼
    │                              Open-Meteo   airport_db
    │                              (rüzgâr)    (5.278 AP)
    │                                    │          │
    │                                    ▼          ▼
    │                              build_graph()
    │                              (NetworkX DiGraph)
    │                                    │
    │                              ┌─────┴──────┐
    │                              ▼            ▼
    │                         A*(distance)  A*(composite)
    │                         [WP only]    [COR only]
    │                              │            │
    │                              ▼            ▼
    │                          Standart     Optimize
    │                          (rüzgârsız)  (rüzgârlı)
    │                              │            │
    │                              ▼            ▼
    │                          _savings() ◄─────┘
    │                              │
    ◄──── JSON Response ───────────┘
    │
    ▼
Harita + İstatistik Paneli + AI Karşılaştırma
```

---

## 🧠 ML Model Detayları

### Mimari
```
Input (7) → Linear(512) → LeakyReLU → BN
         → Linear(256) → LeakyReLU → BN
         → Linear(128) → LeakyReLU → BN
         → Linear(64)  → LeakyReLU
         → Linear(3)   → Output
```

### Giriş Özellikleri (7)
| # | Özellik | Birim |
|---|---------|-------|
| 1 | distance_nm | Deniz mili |
| 2 | wind_speed_kts | Knot |
| 3 | wind_direction_deg | Derece |
| 4 | aircraft_heading_deg | Derece |
| 5 | altitude_ft | Feet |
| 6 | headwind_kts | Knot |
| 7 | crosswind_kts | Knot |

### Çıkış Değerleri (3)
| # | Çıkış | Birim |
|---|-------|-------|
| 1 | fuel_kg | Kilogram |
| 2 | time_min | Dakika |
| 3 | co2_kg | Kilogram |

### Eğitim
- **Veri:** 200.000 sentetik segment (OpenAP fizik motorundan üretilmiş)
- **Normalleştirme:** StandardScaler (X), MinMaxScaler (y) + sqrt transform
- **Optimizer:** AdamW (lr=1e-3, weight_decay=1e-4)
- **Scheduler:** ReduceLROnPlateau
- **Loss:** MSELoss
- **Donanım:** NVIDIA RTX 4070 (CUDA)
- **Model Boyutu:** ~729 KB (model.pt)

---

## 🌍 Desteklenen Menzil

| Kategori | Menzil | Örnek |
|----------|--------|-------|
| Kısa mesafe | 50–300 NM | LTFM → LTBJ (İstanbul → İzmir) |
| Orta mesafe | 300–1500 NM | LTFM → EGLL (İstanbul → Londra) |
| Uzun mesafe | 1500–5000 NM | KJFK → EGLL (New York → Londra) |
| Ultra uzun | 5000–12000 NM | KJFK → VHHH (New York → Hong Kong) |

---

## 📁 Proje Dosya Yapısı

```
deneyap-takimlasma-proje/
├── backend/
│   ├── main.py                    # FastAPI ana uygulama
│   ├── config.py                  # Yapılandırma sabitleri
│   ├── optimization/
│   │   ├── astar.py               # A* pathfinding (çift rota)
│   │   ├── cost_model.py          # OpenAP fizik motoru
│   │   ├── graph_builder.py       # NetworkX graf oluşturucu
│   │   └── ml_predictor.py        # PyTorch model inferansı
│   ├── services/
│   │   ├── airport_service.py     # Havalimanı veritabanı
│   │   ├── weather_service.py     # METAR/TAF servisi
│   │   ├── wind_service.py        # Üst seviye rüzgâr
│   │   ├── adsb_service.py        # OpenSky ADS-B
│   │   └── cache_manager.py       # TTL cache + rate limiter
│   ├── ml/
│   │   ├── train_model.py         # PyTorch eğitim scripti
│   │   ├── data_collector.py      # Sentetik veri üretici
│   │   ├── flight_data.csv        # Eğitim verisi (~14 MB)
│   │   ├── model.pt               # Eğitilmiş model (~729 KB)
│   │   └── scaler.pkl             # Normalleştirme parametreleri
│   └── utils/
│       └── geo.py                 # Haversine, great-circle, rüzgâr bileşenleri
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HomePage.tsx       # Ana sayfa (3D globe)
│   │   │   ├── OptimizerPage.tsx  # Rota optimizasyon sayfası
│   │   │   └── AboutPage.tsx      # Hakkında sayfası
│   │   ├── components/ui/
│   │   │   ├── hero-globe.tsx     # Hero section + pipeline
│   │   │   ├── dotted-surface.tsx # Three.js gravity surface
│   │   │   ├── StatsPanel.tsx     # Tasarruf istatistikleri
│   │   │   └── ComparePanel.tsx   # AI vs Fizik karşılaştırma
│   │   ├── services/
│   │   │   └── api.ts             # Backend API istemcisi
│   │   └── index.css              # Global stiller
│   └── package.json
└── SYSTEM_PROMPT.md               # Bu dosya
```

---

## 🔑 Temel Tasarım Kararları

1. **Eşit Koşullu Karşılaştırma:** İki rota aynı graf, aynı rüzgâr ve aynı fizik motoruyla
   hesaplanır; tek fark amaç fonksiyonudur (mesafe vs kompozit maliyet). Yapay tasarruf üretilmez.
2. **Ölçülebilirlik Eşiği:** %0.1'in altındaki fark kazanç sayılmaz (`has_measurable_savings: false`).
3. **OpenAP Fizik Motoru:** Gerçekçi yakıt akışı ve emisyon hesaplamaları; cruise yakıt akışı
   bir kez hesaplanıp cache'lenir (rota başına ~50x hızlanma).
4. **Surrogate AI:** ML modeli fizik motorunu taklit eder, onun yerine geçmez. Sapma raporlanır,
   sonuç "iyileştirilmez".
5. **Gerçek Üst Seviye Rüzgâr:** Open-Meteo / NOAA GFS 300 hPa verisi, tek istekte 21 örnek.
6. **Responsive Tasarım:** Mobil ve masaüstü uyumlu siber-havacılık arayüzü

---

## 👥 Takım

**İnoTürk** — Deneyap Takımlaşma Projesi

---

*Bu doküman SkyOptimizer AI v0.2.0 için hazırlanmıştır.*
