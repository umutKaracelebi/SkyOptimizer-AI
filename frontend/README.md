# SkyOptimizer AI — Frontend

React 18 + TypeScript + Vite arayüzü. Backend `http://localhost:8000` üzerinde
çalışan FastAPI sunucusuna bağlanır.

## Çalıştırma

```bash
npm install
npm run dev        # http://localhost:5173
```

Backend adresi `VITE_API_BASE` ortam değişkeniyle değiştirilir:

```bash
# frontend/.env.local
VITE_API_BASE=http://192.168.1.20:8000
```

## Komutlar

| Komut | Açıklama |
|-------|----------|
| `npm run dev` | Geliştirme sunucusu (HMR) |
| `npm run build` | Tip kontrolü + üretim derlemesi (`dist/`) |
| `npm run lint` | ESLint |
| `npm run preview` | Üretim derlemesini önizleme |

## Sayfalar

- `/` — `pages/HomePage.tsx` → `components/ui/hero-globe.tsx` (Three.js globe + pipeline anlatımı)
- `/optimizer` — `pages/OptimizerPage.tsx` (Leaflet harita, havalimanı arama, rota karşılaştırma, canlı ADS-B trafiği)
- `/about` — `pages/AboutPage.tsx`

## Yapı

```
src/
├── pages/            # 3 sayfa
├── components/ui/    # HeroGlobe, StatsPanel, ComparePanel, globe/surface bileşenleri
├── services/api.ts   # Backend API istemcisi (tipli)
└── index.css         # Tailwind + siber-havacılık teması
```

`services/api.ts` içindeki tipler backend yanıtlarıyla birebir eşleşir; backend
şeması değişirse önce buradaki tipler güncellenmelidir.
