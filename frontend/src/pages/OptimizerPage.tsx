import { useState, useCallback, useEffect, useRef } from 'react';
import {
  Plane, Wind, BarChart3, ArrowLeft, Search, Loader2, MapPin,
  Radio, Eye, EyeOff,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { searchAirports, optimizeRoute, getLiveFlights } from '../services/api';
import type { Airport, Flight, OptimizeResult } from '../services/api';
import StatsPanel from '../components/ui/StatsPanel';
import type { SavingsData } from '../components/ui/StatsPanel';

/* ── Leaflet ikon tanımları ────────────────────────────────────── */
const airportIcon = L.divIcon({
  className: '',
  html: '<div style="background:#00d4ff;width:10px;height:10px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 8px #00d4ff"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

const waypointIcon = L.divIcon({
  className: '',
  html: '<div style="background:#0ea5e9;width:6px;height:6px;border-radius:50%;opacity:0.6"></div>',
  iconSize: [6, 6],
  iconAnchor: [3, 3],
});

/* ── Waypoint → Polyline dönüştürücü ──────────────────────────── */
/**
 * Backend'den gelen waypoint listesini Leaflet polyline formatına çevirir.
 * Antimeridian (tarih çizgisi ±180°) geçişlerini düzgün işler:
 * ardışık noktalar arasında boylam farkı >180° ise unwrap yapar.
 */
function toPolyline(
  waypoints: { latitude: number; longitude: number }[],
): [number, number][] {
  if (!waypoints || waypoints.length === 0) return [];

  const result: [number, number][] = [];
  let prevLon = waypoints[0].longitude;

  for (let i = 0; i < waypoints.length; i++) {
    const lat = waypoints[i].latitude;
    let lon = waypoints[i].longitude;

    if (i > 0) {
      // Boylam farkı >180° ise unwrap (tarih çizgisi geçişi)
      while (lon - prevLon > 180) lon -= 360;
      while (lon - prevLon < -180) lon += 360;
    }

    result.push([lat, lon]);
    prevLon = lon;
  }

  return result;
}

/**
 * Rotayı tarih çizgisinde (±180°) BÖLER.
 *
 * Neden: unwrap edilmiş boylamlar ±180'in dışına çıkar (JFK→HKG'de -246°'ye
 * kadar). Leaflet bu noktaları dünya kopyalarında farklı yerlere çizdiği için
 * haritada düzlemin öbür ucuna giden kopuk bir çizgi oluşuyordu. Her parça
 * kendi dünya kopyasında kalacak şekilde bölünüp sınıra interpolasyon
 * noktası ekleniyor; böylece çizgi kesintisiz ve doğru görünür.
 */
function toSegments(
  waypoints: { latitude: number; longitude: number }[],
): [number, number][][] {
  if (!waypoints || waypoints.length === 0) return [];

  // 1) Boylamları sürekli hâle getir (unwrap)
  const pts = [{ lat: waypoints[0].latitude, lon: waypoints[0].longitude }];
  for (let i = 1; i < waypoints.length; i++) {
    let lon = waypoints[i].longitude;
    const prev = pts[i - 1].lon;
    while (lon - prev > 180) lon -= 360;
    while (lon - prev < -180) lon += 360;
    pts.push({ lat: waypoints[i].latitude, lon });
  }

  // 2) Dünya kopyası indeksi: 0 → [-180,180), -1 → bir batı, +1 → bir doğu
  const worldIndex = (lon: number) => Math.floor((lon + 180) / 360);
  const normalize = (lon: number, k: number) => lon - 360 * k;

  const segments: [number, number][][] = [];
  let k = worldIndex(pts[0].lon);
  let current: [number, number][] = [[pts[0].lat, normalize(pts[0].lon, k)]];

  for (let i = 1; i < pts.length; i++) {
    const p = pts[i];
    const prev = pts[i - 1];
    const kNext = worldIndex(p.lon);

    if (kNext === k) {
      current.push([p.lat, normalize(p.lon, k)]);
      continue;
    }

    // Sınırı geçiyor: kesişim enlemini interpolasyonla bul
    const seam = kNext > k ? 180 : -180;
    const t = (seam - prev.lon) / (p.lon - prev.lon || 1);
    const seamLat = prev.lat + (p.lat - prev.lat) * t;

    current.push([seamLat, normalize(seam, k)]);
    if (current.length > 1) segments.push(current);

    k = kNext;
    current = [
      [seamLat, normalize(seam, k)],
      [p.lat, normalize(p.lon, k)],
    ];
  }

  if (current.length > 1) segments.push(current);
  else if (current.length === 1 && segments.length > 0) {
    segments[segments.length - 1].push(current[0]);
  }

  return segments;
}

/* ── Mesafe / koridor yardımcıları ─────────────────────────────── */

const EARTH_RADIUS_NM = 3440.065;

/** İki koordinat arası haversine mesafesi (NM). */
function distanceNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_NM * Math.asin(Math.sqrt(a));
}

/**
 * Noktanın rota hattına en yakın mesafesi (NM).
 * Eşdikdörtgen (equirectangular) yaklaşımıyla nokta-doğru parçası mesafesi;
 * 150 NM'lik koridor için fazlasıyla yeterli.
 */
function distanceToRoute(
  lat: number,
  lon: number,
  points: [number, number][],
): number {
  if (points.length === 0) return Infinity;
  if (points.length === 1) return distanceNm(lat, lon, points[0][0], points[0][1]);

  let best = Infinity;
  for (let i = 0; i < points.length - 1; i++) {
    const [lat1, lon1] = points[i];
    const [lat2, lon2] = points[i + 1];

    // Yerel düzlem yaklaşımı
    const cosLat = Math.cos((lat * Math.PI) / 180);
    const ax = lon1 * cosLat, ay = lat1;
    const bx = lon2 * cosLat, by = lat2;
    const px = lon * cosLat, py = lat;

    const dx = bx - ax, dy = by - ay;
    const lenSq = dx * dx + dy * dy;
    let t = lenSq === 0 ? 0 : ((px - ax) * dx + (py - ay) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));

    const nearestLat = ay + t * dy;
    const nearestLon = (ax + t * dx) / cosLat;
    best = Math.min(best, distanceNm(lat, lon, nearestLat, nearestLon));
  }
  return best;
}

/* ── Harita görünümünü güncelleyen yardımcı ─────────────────────── */
function MapUpdater({ center, zoom, bounds }: {
  center: [number, number]; zoom: number;
  bounds?: [[number, number], [number, number]] | null;
}) {
  const map = useMap();

  // Harita mutasyonu render sırasında değil, effect içinde yapılmalı.
  useEffect(() => {
    if (bounds) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
    } else {
      map.setView(center, zoom);
    }
  }, [map, center, zoom, bounds]);

  return null;
}

/* ═══════════════════════════════════════════════════════════════════
   OptimizerPage
   ═══════════════════════════════════════════════════════════════════ */
export default function OptimizerPage() {
  const navigate = useNavigate();

  /* ── state ──────────────────────────────────────────────────── */
  const [originQuery, setOriginQuery] = useState('');
  const [destQuery, setDestQuery] = useState('');
  const [originResults, setOriginResults] = useState<Airport[]>([]);
  const [destResults, setDestResults] = useState<Airport[]>([]);
  const [selectedOrigin, setSelectedOrigin] = useState<Airport | null>(null);
  const [selectedDest, setSelectedDest] = useState<Airport | null>(null);
  const [result, setResult] = useState<OptimizeResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [weights, setWeights] = useState({ fuel: 40, time: 35, co2: 25 });
  const [aircraftType, setAircraftType] = useState('B738');
  const [mapCenter, setMapCenter] = useState<[number, number]>([30.0, 0.0]);
  const [mapZoom, setMapZoom] = useState(3);
  const [mapBounds, setMapBounds] = useState<[[number, number], [number, number]] | null>(null);

  /* ── Türetilmiş rota değerleri (trafik filtresi de kullanıyor) ── */
  const stdRoute  = result?.standard_route;
  const optRoute  = result?.optimized_route;
  const savings   = result?.savings;

  /* ── ADS-B canlı trafik state ──────────────────────────────── */
  const [showTraffic, setShowTraffic] = useState(false);
  // 'route' → yalnızca rota koridorundaki hava sahası, 'world' → tüm dünya
  const [trafficMode, setTrafficMode] = useState<'route' | 'world'>('route');
  const [liveFlights, setLiveFlights] = useState<Flight[]>([]);
  const [trafficLoading, setTrafficLoading] = useState(false);
  const [trafficCount, setTrafficCount] = useState(0);
  const [trafficError, setTrafficError] = useState('');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── Stats state ───────────────────────────────────────────── */
  const [latestSavings, setLatestSavings] = useState<SavingsData | null>(null);

  /* ── havalimanı arama ──────────────────────────────────────── */
  const handleSearch = useCallback(async (query: string, type: 'origin' | 'dest') => {
    const setResults = type === 'origin' ? setOriginResults : setDestResults;
    if (query.length < 2) {
      setResults([]);
      return;
    }
    try {
      const data = await searchAirports(query, 20); // Limit 6'dan 20'ye çıkarıldı ki tüm sonuçlar listelenebilsin
      setResults(data.results);
    } catch {
      /* ignore */
    }
  }, []);

  /* ── havalimanı seçimi ─────────────────────────────────────── */
  const selectAirport = (airport: Airport, type: 'origin' | 'dest') => {
    if (type === 'origin') {
      setSelectedOrigin(airport);
      setOriginQuery(`${airport.icao} — ${airport.name}`);
      setOriginResults([]);
    } else {
      setSelectedDest(airport);
      setDestQuery(`${airport.icao} — ${airport.name}`);
      setDestResults([]);
    }
  };

  /* ── ADS-B canlı trafik ───────────────────────────────────── */
  const fetchTraffic = useCallback(async () => {
    setTrafficLoading(true);
    setTrafficError('');
    try {
      // Rota modunda kaba bbox + koridor filtresi;
      // dünya modunda tüm küre (OpenSky tek istekte döndürür).
      let data;
      let routeLine: [number, number][] = [];

      if (trafficMode === 'world') {
        data = await getLiveFlights({
          lamin: -85, lamax: 85, lomin: -180, lomax: 180,
        });
      } else {
        if (!selectedOrigin || !selectedDest) {
          setLiveFlights([]);
          setTrafficCount(0);
          setTrafficLoading(false);
          return;
        }

        // Koridor hattı: optimize rota varsa onu, yoksa kalkış→varış düz hattı
        routeLine = optRoute
          ? toPolyline(optRoute.waypoints)
          : [
              [selectedOrigin.latitude, selectedOrigin.longitude],
              [selectedDest.latitude, selectedDest.longitude],
            ];

        const lats = routeLine.map(p => p[0]);
        const lons = routeLine.map(p => p[1]);
        const pad = 4; // derece — koridor filtresi için pay
        data = await getLiveFlights({
          lamin: Math.max(-85, Math.min(...lats) - pad),
          lamax: Math.min(85, Math.max(...lats) + pad),
          lomin: Math.max(-180, Math.min(...lons) - pad),
          lomax: Math.min(180, Math.max(...lons) + pad),
        });
      }

      if (data?.flights) {
        let flights = data.flights;

        // Rota modunda bbox dikdörtgeni yeterli değil — hattan uzak uçakları at
        if (trafficMode === 'route' && routeLine.length > 1) {
          const CORRIDOR_NM = 150;
          flights = flights.filter(f =>
            distanceToRoute(f.latitude, f.longitude, routeLine) <= CORRIDOR_NM
          );
        }

        setLiveFlights(flights);
        setTrafficCount(flights.length);
        if (data.error) setTrafficError(String(data.error));
      } else {
        setLiveFlights([]);
        setTrafficCount(0);
      }
    } catch (e) {
      setTrafficError(String(e));
    }
    setTrafficLoading(false);
  }, [trafficMode, selectedOrigin, selectedDest, optRoute]);

  useEffect(() => {
    if (showTraffic) {
      fetchTraffic();
      intervalRef.current = setInterval(fetchTraffic, 60_000);
    } else {
      setLiveFlights([]);
      setTrafficCount(0);
      setTrafficError('');
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [showTraffic, fetchTraffic]);

  /* ── optimizasyon ──────────────────────────────────────────── */
  const handleOptimize = async () => {
    if (!selectedOrigin || !selectedDest) {
      setError('Kalkış ve varış havalimanı seçiniz');
      return;
    }
    setLoading(true);
    setError('');
    try {
      const data = await optimizeRoute({
        origin: selectedOrigin.icao,
        destination: selectedDest.icao,
        aircraft_type: aircraftType,
        optimization_weights: {
          fuel: weights.fuel / 100,
          time: weights.time / 100,
          co2: weights.co2 / 100,
        },
      });
      if (data && 'error' in data && data.error) {
        setError(String(data.error));
      } else {
        setResult(data);

        // Harita görünümünü rota waypoint'lerine göre fitBounds ile ayarla
        const optWaypoints = data?.optimized_route?.waypoints;
        if (optWaypoints && optWaypoints.length > 0) {
          const unwrapped = toPolyline(optWaypoints);
          const lats = unwrapped.map((p: [number, number]) => p[0]);
          const lons = unwrapped.map((p: [number, number]) => p[1]);
          setMapBounds([
            [Math.min(...lats) - 2, Math.min(...lons) - 5],
            [Math.max(...lats) + 2, Math.max(...lons) + 5],
          ]);
        } else {
          setMapBounds(null);
          const midLat = (selectedOrigin.latitude + selectedDest.latitude) / 2;
          const midLon = (selectedOrigin.longitude + selectedDest.longitude) / 2;
          setMapCenter([midLat, midLon]);
          setMapZoom(4);
        }

        // Savings'i stats panel'e gönder
        const s = data?.savings;
        if (s) {
          setLatestSavings({
            fuel_saved_kg: s.fuel_saved_kg || 0,
            time_saved_min: s.time_saved_min || 0,
            co2_saved_kg: s.co2_saved_kg || 0,
            cost_saved_usd: s.cost_saved_usd || 0,
          });
        }
      }
    } catch (e) {
      setError(`Optimizasyon hatası: ${e}`);
    }
    setLoading(false);
  };

  /* ── yardımcılar ───────────────────────────────────────────── */



  /* ═══════════════ JSX ═══════════════════════════════════════════ */
  return (
    <div className="dark min-h-screen bg-[hsl(224,71%,4%)] text-white font-mono">
      {/* ── Header ────────────────────────────────────────────── */}
      <header className="border-b border-cyan-500/20 bg-black/60 backdrop-blur-sm sticky top-0 z-[1000]">
        <div className="container mx-auto px-4 lg:px-8 py-2.5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={() => navigate('/')} className="text-cyan-500/60 hover:text-cyan-400 transition-colors">
              <ArrowLeft size={18} />
            </button>
            <div className="font-mono text-cyan-400 text-base font-bold tracking-widest">
              SKYOPTIMIZER<span className="text-cyan-600 text-xs ml-1">AI</span>
            </div>
            <div className="h-3 w-px bg-cyan-500/30" />
            <span className="text-cyan-500/50 text-[10px] hidden sm:inline">ROTA OPTİMİZASYONU</span>
          </div>
          <div className="flex items-center gap-2 text-[10px] text-cyan-500/50">
            <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
            <span className="hidden sm:inline">AKTİF</span>
          </div>
        </div>
      </header>

      {/* ── İki-sütun layout ─────────────────────────────────── */}
      <div className="flex flex-col lg:flex-row h-[calc(100vh-41px)]">

        {/* ══ Sol Panel ═══════════════════════════════════════════ */}
        <div className="w-full lg:w-[340px] overflow-y-auto border-r border-cyan-500/10 bg-black/40 panel-scroll">
          <div className="p-4 space-y-4">

            {/* -- Uçuş Bilgileri -- */}
            <div className="glass-card rounded-xl p-4 fade-in-up">
              <h2 className="text-xs font-bold text-cyan-400 mb-3 flex items-center gap-2">
                <Plane size={14} /> UÇUŞ BİLGİLERİ
              </h2>

              {/* Kalkış */}
              <div className="mb-3 relative">
                <label className="text-[9px] text-gray-500 uppercase tracking-wider">Kalkış</label>
                <div className="relative mt-1">
                  <Search size={12} className="absolute left-2.5 top-2.5 text-gray-500" />
                  <input
                    value={originQuery}
                    onChange={e => { setOriginQuery(e.target.value); handleSearch(e.target.value, 'origin'); }}
                    placeholder="KJFK, London, Istanbul..."
                    className="w-full bg-black/60 border border-cyan-500/20 rounded-lg pl-8 pr-3 py-2 text-xs text-white placeholder-gray-600 focus:border-cyan-500/50 focus:outline-none transition-colors"
                  />
                </div>
                {originResults.length > 0 && (
                  <div className="absolute z-50 mt-1 w-full bg-gray-900 border border-cyan-500/30 rounded-lg overflow-y-auto max-h-48 shadow-xl custom-scrollbar">
                    {originResults.map(ap => (
                      <button key={ap.icao} onClick={() => selectAirport(ap, 'origin')}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-cyan-500/10 border-b border-gray-800 last:border-0 transition-colors">
                        <span className="text-cyan-400 font-bold">{ap.icao}</span>
                        {ap.iata && <span className="text-gray-500 ml-1">({ap.iata})</span>}
                        <span className="text-gray-400 ml-2">{ap.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Varış */}
              <div className="mb-3 relative">
                <label className="text-[9px] text-gray-500 uppercase tracking-wider">Varış</label>
                <div className="relative mt-1">
                  <Search size={12} className="absolute left-2.5 top-2.5 text-gray-500" />
                  <input
                    value={destQuery}
                    onChange={e => { setDestQuery(e.target.value); handleSearch(e.target.value, 'dest'); }}
                    placeholder="EGLL, Tokyo, Antalya..."
                    className="w-full bg-black/60 border border-cyan-500/20 rounded-lg pl-8 pr-3 py-2 text-xs text-white placeholder-gray-600 focus:border-cyan-500/50 focus:outline-none transition-colors"
                  />
                </div>
                {destResults.length > 0 && (
                  <div className="absolute z-50 mt-1 w-full bg-gray-900 border border-cyan-500/30 rounded-lg overflow-y-auto max-h-48 shadow-xl custom-scrollbar">
                    {destResults.map(ap => (
                      <button key={ap.icao} onClick={() => selectAirport(ap, 'dest')}
                        className="w-full text-left px-3 py-2 text-xs hover:bg-cyan-500/10 border-b border-gray-800 last:border-0 transition-colors">
                        <span className="text-cyan-400 font-bold">{ap.icao}</span>
                        {ap.iata && <span className="text-gray-500 ml-1">({ap.iata})</span>}
                        <span className="text-gray-400 ml-2">{ap.name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {/* Uçak Tipi */}
              <div className="mb-3">
                <label className="text-[9px] text-gray-500 uppercase tracking-wider">Uçak Tipi</label>
                <select
                  value={aircraftType}
                  onChange={e => setAircraftType(e.target.value)}
                  className="w-full mt-1 bg-black/60 border border-cyan-500/20 rounded-lg px-3 py-2 text-xs text-cyan-400 focus:border-cyan-500/50 focus:outline-none appearance-none cursor-pointer"
                >
                  <option value="B738">B738 — Boeing 737-800</option>
                  <option value="A320">A320 — Airbus A320</option>
                  <option value="A321">A321 — Airbus A321</option>
                  <option value="B77W">B77W — Boeing 777-300ER</option>
                  <option value="A388">A388 — Airbus A380-800</option>
                  <option value="B789">B789 — Boeing 787-9</option>
                  <option value="E190">E190 — Embraer E190</option>
                </select>
              </div>

              {/* Optimize butonu */}
              <button
                onClick={handleOptimize}
                disabled={loading || !selectedOrigin || !selectedDest}
                className="w-full mt-2 px-4 py-2.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/50 rounded-lg text-xs hover:bg-cyan-500/20 hover:shadow-[0_0_20px_rgba(0,212,255,0.15)] transition-all glow-primary disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2 active:scale-[0.98]"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Plane size={14} />}
                {loading ? 'OPTİMİZE EDİLİYOR...' : '✈ ROTAYI OPTİMİZE ET'}
              </button>
              {error && <p className="text-red-400 text-[10px] mt-2">{error}</p>}
            </div>

            {/* -- Optimizasyon Ağırlıkları -- */}
            <div className="glass-card rounded-xl p-4 fade-in-up" style={{ animationDelay: '0.1s' }}>
              <h2 className="text-xs font-bold text-cyan-400 mb-3 flex items-center gap-2">
                <BarChart3 size={14} /> OPTİMİZASYON ÖNCELİKLERİ
              </h2>
              {([
                { key: 'fuel' as const, label: 'Yakıt', color: 'bg-emerald-500' },
                { key: 'time' as const, label: 'Süre',  color: 'bg-blue-500'    },
                { key: 'co2'  as const, label: 'CO₂',   color: 'bg-amber-500'   },
              ]).map(item => (
                <div key={item.key} className="mb-2">
                  <div className="flex justify-between text-[10px] text-gray-400 mb-1">
                    <span>{item.label}</span><span>%{weights[item.key]}</span>
                  </div>
                  <input
                    type="range" min="0" max="100" value={weights[item.key]}
                    onChange={e => setWeights(prev => ({ ...prev, [item.key]: +e.target.value }))}
                    className="w-full h-1.5 bg-gray-800 rounded-full appearance-none cursor-pointer accent-cyan-500"
                  />
                </div>
              ))}
              {/*
                Dürüstlük notu: bu fizik modelinde CO₂ = 3.16 × yakıt ve yakıt
                süreyle neredeyse orantılıdır; üç kriter aynı hedefi ölçer.
                Ağırlıklar yol seçimini yalnızca marjinal etkiler.
              */}
              <p className="mt-2 pt-2 border-t border-gray-800 text-[9px] leading-snug text-gray-600">
                Bu modelde CO₂ = 3.16 × yakıt ve yakıt süreyle orantılıdır; üç
                ağırlık aynı hedefi ölçer, rota seçimini yalnızca marjinal etkiler.
              </p>
            </div>

            {/* -- Canlı Trafik Toggle -- */}
            <div className="glass-card rounded-xl p-4 fade-in-up" style={{ animationDelay: '0.15s' }}>
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-bold text-cyan-400 flex items-center gap-2">
                  <Radio size={14} className={showTraffic ? 'text-amber-400' : ''} />
                  CANLI TRAFİK
                </h2>
                <button
                  onClick={() => setShowTraffic(!showTraffic)}
                  className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold transition-all ${
                    showTraffic
                      ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.15)]'
                      : 'bg-gray-800/50 text-gray-500 border border-gray-700 hover:border-gray-600'
                  }`}
                >
                  {showTraffic ? <Eye size={10} /> : <EyeOff size={10} />}
                  {showTraffic ? 'AKTİF' : 'KAPALI'}
                </button>
              </div>
              {showTraffic && (
                <>
                  {/* Kapsam seçimi: rota hava sahası ↔ tüm dünya */}
                  <div className="mt-2 grid grid-cols-2 gap-1 p-1 rounded-lg bg-black/40 border border-gray-800">
                    {([
                      { key: 'route' as const, label: 'ROTA SAHASI' },
                      { key: 'world' as const, label: 'TÜM DÜNYA' },
                    ]).map(opt => (
                      <button
                        key={opt.key}
                        onClick={() => setTrafficMode(opt.key)}
                        className={`py-1 rounded-md text-[9px] font-bold tracking-wide transition-colors ${
                          trafficMode === opt.key
                            ? 'bg-amber-500/20 text-amber-400'
                            : 'text-gray-500 hover:text-gray-400'
                        }`}
                      >
                        {opt.label}
                      </button>
                    ))}
                  </div>

                  <div className="mt-2 flex items-center gap-2 text-[10px] text-gray-400">
                    {trafficLoading && <Loader2 size={10} className="animate-spin text-amber-400" />}
                    <span className="text-amber-400 font-bold">{trafficCount}</span>
                    {trafficMode === 'route' ? 'uçak rotada (150 NM)' : 'uçak dünya geneli'}
                    <span className="ml-auto text-gray-600">60sn</span>
                  </div>

                  {trafficMode === 'route' && (!selectedOrigin || !selectedDest) && (
                    <p className="mt-1 text-[9px] text-gray-500 leading-snug">
                      Rota hava sahası için kalkış ve varış seçilmeli.
                    </p>
                  )}
                  {trafficError && (
                    <p className="mt-1 text-[9px] text-red-400/80 leading-snug">{trafficError}</p>
                  )}
                </>
              )}
            </div>

            {/* -- Tasarruf Paneli -- */}
            {savings && (
              <div className="glass-card rounded-xl p-4 fade-in-up">
                <h2 className="text-xs font-bold text-emerald-400 mb-3 flex items-center gap-2">
                  <Wind size={14} /> TASARRUF
                </h2>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-2 text-center">
                    <div className="text-emerald-400 text-lg font-bold">{savings.fuel_saved_kg}</div>
                    <div className="text-gray-500 text-[8px]">KG YAKIT</div>
                  </div>
                  <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-2 text-center">
                    <div className="text-blue-400 text-lg font-bold">{savings.time_saved_min}</div>
                    <div className="text-gray-500 text-[8px]">DK SÜRE</div>
                  </div>
                  <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-2 text-center">
                    <div className="text-amber-400 text-lg font-bold">{savings.co2_saved_kg}</div>
                    <div className="text-gray-500 text-[8px]">KG CO₂</div>
                  </div>
                  <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-2 text-center">
                    <div className="text-purple-400 text-lg font-bold">${savings.cost_saved_usd}</div>
                    <div className="text-gray-500 text-[8px]">MALİYET</div>
                  </div>
                </div>
                {/* Rota karşılaştırma */}
                {stdRoute && optRoute && (
                  <div className="mt-3 space-y-1.5">
                    <div className="flex items-center gap-2 text-[10px]">
                      <div className="w-3 h-0.5 bg-red-500 rounded" />
                      <span className="text-gray-400">Standart: {stdRoute.total_distance_nm} NM, {stdRoute.estimated_fuel_kg} kg, {stdRoute.estimated_time_min} dk</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px]">
                      <div className="w-3 h-0.5 bg-cyan-400 rounded" />
                      <span className="text-gray-400">Optimize: {optRoute.total_distance_nm} NM, {optRoute.estimated_fuel_kg} kg, {optRoute.estimated_time_min} dk</span>
                    </div>
                    {result && !result.has_measurable_savings ? (
                      <div className="text-[10px] text-gray-400 mt-1 leading-relaxed">
                        Bu rota için optimizasyon farkı yok — en kısa yol zaten
                        maliyet-optimal.
                      </div>
                    ) : (
                      <div
                        className={`text-[10px] font-bold mt-1 ${
                          savings.fuel_saved_kg >= 0 ? 'text-cyan-400' : 'text-red-400'
                        }`}
                      >
                        {savings.fuel_saved_kg >= 0 ? '▲' : '▼'} %
                        {Math.abs(savings.fuel_saved_percent)} yakıt
                        {savings.fuel_saved_kg >= 0 ? ' tasarrufu' : ' artışı'}
                        {savings.distance_delta_nm !== 0 && (
                          <span className="text-gray-500 font-normal">
                            {' '}(rota {Math.abs(savings.distance_delta_nm)} NM{' '}
                            {savings.distance_delta_nm > 0 ? 'daha uzun' : 'daha kısa'})
                          </span>
                        )}
                      </div>
                    )}
                    {result?.comparison_basis && (
                      <div className="text-[9px] text-gray-600 leading-snug pt-1">
                        İki rota da aynı rüzgârla hesaplandı. Optimize rota ağırlıkları:
                        yakıt %{Math.round(result.comparison_basis.weights.fuel * 100)},
                        süre %{Math.round(result.comparison_basis.weights.time * 100)},
                        CO₂ %{Math.round(result.comparison_basis.weights.co2 * 100)}.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* -- Birikimli Tasarruf -- */}
            <div className="fade-in-up" style={{ animationDelay: '0.2s' }}>
              <StatsPanel latestSavings={latestSavings} />
            </div>
          </div>
        </div>

        {/* ══ Harita ══════════════════════════════════════════════ */}
        <div className="flex-1 relative">
          <MapContainer
            center={mapCenter}
            zoom={mapZoom}
            className="w-full h-full"
            style={{ background: '#0a0e27' }}
            zoomControl={false}
            minZoom={2}
            worldCopyJump={true}
            preferCanvas={true}
          >
            <MapUpdater center={mapCenter} zoom={mapZoom} bounds={mapBounds} />
            {/*
              Harita karoları: Esri World Dark Gray (anahtarsız).
              NOT: Önceden CARTO dark_all kullanılıyordu; CARTO artık karo
              sunucusunda API anahtarı istiyor ve harita "API KEY REQUIRED"
              filigranıyla doluyordu. Esri bu katmanı anahtarsız sunuyor.
            */}
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
              attribution='Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıcıları'
              maxZoom={16}
            />
            {/* Yer etiketleri (şehir/ülke adları) ayrı şeffaf katman */}
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
              maxZoom={16}
            />

            {/* Optimize rota — cyan parlak çizgi (önce çizilir, altta kalır).
                Tarih çizgisini geçen rotalar segmentlere bölünerek çizilir. */}
            {optRoute && toSegments(optRoute.waypoints).map((segment, i) => (
              <Polyline
                key={`opt-${i}`}
                positions={segment}
                pathOptions={{ color: '#00d4ff', weight: 4, opacity: 0.85 }}
              />
            ))}

            {/* Standart rota — kırmızı kesik çizgi (üstte çizilir, her zaman görünür) */}
            {stdRoute && toSegments(stdRoute.waypoints).map((segment, i) => (
              <Polyline
                key={`std-${i}`}
                positions={segment}
                pathOptions={{ color: '#ef4444', weight: 2.5, opacity: 0.7, dashArray: '10,8' }}
              />
            ))}

            {/* Havalimanı marker'ları — rota varsa unwrapped koordinat kullan */}
            {selectedOrigin && (() => {
              const positions = optRoute ? toPolyline(optRoute.waypoints) : null;
              const pos: [number, number] = positions && positions.length > 0
                ? positions[0]
                : [selectedOrigin.latitude, selectedOrigin.longitude];
              return (
                <Marker position={pos} icon={airportIcon}>
                  <Popup><div className="text-xs font-mono"><strong className="text-cyan-600">{selectedOrigin.icao}</strong><br/>{selectedOrigin.name}</div></Popup>
                </Marker>
              );
            })()}
            {selectedDest && (() => {
              const positions = optRoute ? toPolyline(optRoute.waypoints) : null;
              const pos: [number, number] = positions && positions.length > 0
                ? positions[positions.length - 1]
                : [selectedDest.latitude, selectedDest.longitude];
              return (
                <Marker position={pos} icon={airportIcon}>
                  <Popup><div className="text-xs font-mono"><strong className="text-cyan-600">{selectedDest.icao}</strong><br/>{selectedDest.name}</div></Popup>
                </Marker>
              );
            })()}



            {/* Optimize rota waypoint noktaları — unwrapped */}
            {optRoute?.waypoints && (() => {
              const unwrapped = toPolyline(optRoute.waypoints);
              return optRoute.waypoints
                .map((wp: { type: string; name: string }, i: number) => {
                  if (wp.type !== 'waypoint' && wp.type !== 'corridor') return null;
                  return (
                    <Marker key={`opt-${i}`} position={unwrapped[i]} icon={waypointIcon}>
                      <Popup><span className="text-xs font-mono">{wp.name}</span></Popup>
                    </Marker>
                  );
                });
            })()}

            {/* ── ADS-B Canlı Uçaklar ──────────────────────────────
                Dünya modunda 10.000+ uçak dönebildiği için divIcon yerine
                canvas üzerine çizilen CircleMarker kullanılıyor (preferCanvas). */}
            {showTraffic && liveFlights.map(flight => {
              if (!flight.latitude || !flight.longitude) return null;
              return (
                <CircleMarker
                  key={flight.icao24}
                  center={[flight.latitude, flight.longitude]}
                  radius={2.5}
                  pathOptions={{
                    color: '#f59e0b',
                    weight: 1,
                    fillColor: '#fbbf24',
                    fillOpacity: 0.85,
                  }}
                >
                  <Popup>
                    <div className="text-xs font-mono space-y-0.5 min-w-[140px]">
                      <div className="font-bold text-amber-600 text-sm">
                        {flight.callsign || flight.icao24}
                      </div>
                      <div className="text-gray-600">{flight.origin_country}</div>
                      <hr className="border-gray-300 my-1" />
                      <div className="flex justify-between">
                        <span className="text-gray-500">İrtifa</span>
                        <span>{flight.altitude_m ? `${Math.round(flight.altitude_m * 3.281)} ft` : '—'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Hız</span>
                        <span>{flight.velocity_ms ? `${Math.round(flight.velocity_ms * 1.944)} kts` : '—'}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-gray-500">Yön</span>
                        <span>{flight.true_track ? `${Math.round(flight.true_track)}°` : '—'}</span>
                      </div>
                    </div>
                  </Popup>
                </CircleMarker>
              );
            })}
          </MapContainer>

          {/* Legend */}
          <div className="absolute bottom-4 right-4 z-[1000] glass-card rounded-lg p-3">
            <div className="text-[9px] font-mono text-gray-400 space-y-1.5">
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-red-500 rounded" style={{ borderStyle: 'dashed' }} />
                <span>Standart Rota</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-emerald-500 rounded" />
                <span>Optimize Rota</span>
              </div>
              <div className="flex items-center gap-2">
                <MapPin size={8} className="text-cyan-400" />
                <span>Havalimanı</span>
              </div>

              {showTraffic && (
                <div className="flex items-center gap-2">
                  <span className="text-[10px]">✈</span>
                  <span className="text-amber-400">Canlı Trafik ({trafficCount})</span>
                </div>
              )}
            </div>
          </div>

          {/* İlk açılış bilgi kutusu */}
          {!result && (
            <div className="absolute inset-0 flex items-center justify-center z-[999] pointer-events-none">
              <div className="text-center glass-card rounded-xl p-6 pointer-events-auto max-w-sm fade-in-up">
                <Plane size={36} className="mx-auto mb-3 text-cyan-500/40" />
                <h3 className="text-sm font-bold text-cyan-400 mb-2">Rota Seçin</h3>
                <p className="text-[11px] text-gray-500">
                  Sol panelden kalkış ve varış havalimanı seçerek
                  yapay zekâ optimizasyonunu başlatın.
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
