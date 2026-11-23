import { useState, useCallback, useEffect, useRef, useMemo } from 'react';
import {
  Plane, Wind, BarChart3, ArrowLeft, Search, Loader2, MapPin,
  Radio, Eye, EyeOff, Gauge, Clock, Layers, Share2, Download, Printer,
  Check, AlertTriangle, ChevronDown,
} from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import {
  MapContainer, TileLayer, Polyline, Marker, Popup, CircleMarker,
  GeoJSON, useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  searchAirports, optimizeRoute, getLiveFlights, getAirport,
  getAirspaces, validateRoute, getConfig,
} from '../services/api';
import type {
  Airport, Flight, OptimizeResult, AirspaceResponse, ValidationResult,
  AppConfig, AircraftTypeOption,
} from '../services/api';
import StatsPanel from '../components/ui/StatsPanel';
import type { SavingsData } from '../components/ui/StatsPanel';
import WeatherCard from '../components/ui/WeatherCard';
import AircraftDetailPanel from '../components/ui/AircraftDetailPanel';
import ValidationCard from '../components/ui/ValidationCard';
import {
  aircraftIcon, aircraftLegendSvg, AIRCRAFT_CLASS_LABELS,
  AIRCRAFT_CLASS_COLORS,
} from '../lib/aircraftIcons';

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
 * haritada düzlemin öbür ucuna giden kopuk bir çizgi oluşuyordu.
 */
function toSegments(
  waypoints: { latitude: number; longitude: number }[],
): [number, number][][] {
  if (!waypoints || waypoints.length === 0) return [];

  const pts = [{ lat: waypoints[0].latitude, lon: waypoints[0].longitude }];
  for (let i = 1; i < waypoints.length; i++) {
    let lon = waypoints[i].longitude;
    const prev = pts[i - 1].lon;
    while (lon - prev > 180) lon -= 360;
    while (lon - prev < -180) lon += 360;
    pts.push({ lat: waypoints[i].latitude, lon });
  }

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

function distanceNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(((lon2 - lon1 + 180) % 360) - 180);
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

  useEffect(() => {
    if (bounds) {
      map.fitBounds(bounds, { padding: [40, 40], maxZoom: 8 });
    } else {
      map.setView(center, zoom);
    }
  }, [map, center, zoom, bounds]);

  return null;
}

/* ── Biçimlendirme ─────────────────────────────────────────────── */
const fmt = (value: number | null | undefined, digits = 0) =>
  value == null ? '—' : value.toLocaleString('tr-TR', {
    minimumFractionDigits: digits, maximumFractionDigits: digits,
  });

const fmtClock = (minutes: number) => {
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return h > 0 ? `${h}s ${m.toString().padStart(2, '0')}dk` : `${m}dk`;
};

const isoToLocalInput = (iso: string) => {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

const localInputToIso = (value: string): string | null => {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString();
};

/* ── Rota fazı çubuğu ─────────────────────────────────────────── */
function PhaseBar({
  phases,
}: {
  phases: { climb: { fuel_kg: number; time_min: number }; cruise: { fuel_kg: number; time_min: number }; descent: { fuel_kg: number; time_min: number } };
}) {
  const totalFuel = phases.climb.fuel_kg + phases.cruise.fuel_kg + phases.descent.fuel_kg || 1;
  const items = [
    { key: 'TIRMANMA', fuel: phases.climb.fuel_kg, time: phases.climb.time_min, color: 'bg-cyan-400' },
    { key: 'CRUISE', fuel: phases.cruise.fuel_kg, time: phases.cruise.time_min, color: 'bg-emerald-400' },
    { key: 'ALÇALMA', fuel: phases.descent.fuel_kg, time: phases.descent.time_min, color: 'bg-amber-400' },
  ];
  return (
    <div>
      <div className="flex h-2 rounded-full overflow-hidden bg-gray-800">
        {items.map(item => (
          <div
            key={item.key}
            className={item.color}
            style={{ width: `${(item.fuel / totalFuel) * 100}%` }}
            title={`${item.key}: ${fmt(item.fuel)} kg`}
          />
        ))}
      </div>
      <div className="mt-1.5 grid grid-cols-3 gap-1 text-[8px] text-gray-500">
        {items.map(item => (
          <div key={item.key} className="flex items-center gap-1">
            <span className={`w-1.5 h-1.5 rounded-full ${item.color}`} />
            <span>{item.key}</span>
            <span className="text-gray-400 tabular-nums">{fmt(item.fuel)} kg</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════
   OptimizerPage
   ═══════════════════════════════════════════════════════════════════ */
export default function OptimizerPage() {
  const navigate = useNavigate();

  /* ── konfigürasyon ───────────────────────────────────────────── */
  const [config, setConfig] = useState<AppConfig | null>(null);
  const aircraftOptions: AircraftTypeOption[] = config?.aircraft_types?.length
    ? config.aircraft_types
    : [
        { code: 'B738', name: 'Boeing 737-800' },
        { code: 'A320', name: 'Airbus A320' },
        { code: 'A321', name: 'Airbus A321' },
        { code: 'A20N', name: 'Airbus A320neo' },
        { code: 'A21N', name: 'Airbus A321neo' },
        { code: 'B77W', name: 'Boeing 777-300ER' },
        { code: 'B789', name: 'Boeing 787-9' },
        { code: 'A359', name: 'Airbus A350-900' },
        { code: 'A388', name: 'Airbus A380-800' },
        { code: 'E190', name: 'Embraer E190' },
        { code: 'AT76', name: 'ATR 72-600' },
      ];

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
  const [costIndex, setCostIndex] = useState(30);
  const [departureInput, setDepartureInput] = useState('');
  const [avoidAirspace, setAvoidAirspace] = useState(true);
  const [mapCenter, setMapCenter] = useState<[number, number]>([30.0, 0.0]);
  const [mapZoom, setMapZoom] = useState(3);
  const [mapBounds, setMapBounds] = useState<[[number, number], [number, number]] | null>(null);
  const [showMethodNotes, setShowMethodNotes] = useState(false);
  const [shareState, setShareState] = useState<'idle' | 'copied' | 'failed'>('idle');

  /* ── Türetilmiş rota değerleri (trafik filtresi de kullanıyor) ── */
  const stdRoute = result?.standard_route;
  const optRoute = result?.optimized_route;
  const savings = result?.savings;

  /* ── ADS-B canlı trafik state ──────────────────────────────── */
  const [showTraffic, setShowTraffic] = useState(false);
  const [trafficMode, setTrafficMode] = useState<'route' | 'world'>('route');
  const [liveFlights, setLiveFlights] = useState<Flight[]>([]);
  const [trafficLoading, setTrafficLoading] = useState(false);
  const [trafficCount, setTrafficCount] = useState(0);
  const [trafficError, setTrafficError] = useState('');
  const [selectedFlight, setSelectedFlight] = useState<Flight | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* ── Hava sahası katmanı ──────────────────────────────────── */
  const [showAirspaces, setShowAirspaces] = useState(false);
  const [airspaceData, setAirspaceData] = useState<AirspaceResponse | null>(null);

  /* ── Gerçek uçuş doğrulama ───────────────────────────────── */
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [validationLoading, setValidationLoading] = useState(false);
  const [validationError, setValidationError] = useState('');

  /* ── Stats state ───────────────────────────────────────────── */
  const [latestSavings, setLatestSavings] = useState<SavingsData | null>(null);
  const [statsRefreshKey, setStatsRefreshKey] = useState(0);

  const autoRunRef = useRef(false);

  /* ── konfigürasyonu yükle ─────────────────────────────────── */
  useEffect(() => {
    getConfig()
      .then(cfg => {
        setConfig(cfg);
        setCostIndex(cfg.cost_index.default);
        if (cfg.default_aircraft) setAircraftType(cfg.default_aircraft);
      })
      .catch(() => { /* varsayılanlar kullanılır */ });
  }, []);

  /* ── havalimanı arama ──────────────────────────────────────── */
  const handleSearch = useCallback(async (query: string, type: 'origin' | 'dest') => {
    const setResults = type === 'origin' ? setOriginResults : setDestResults;
    if (query.length < 2) {
      setResults([]);
      return;
    }
    try {
      const data = await searchAirports(query, 20);
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

  /* ── optimizasyon ──────────────────────────────────────────── */
  const handleOptimize = useCallback(async (
    originArg?: Airport,
    destArg?: Airport,
    overrides?: {
      aircraftType?: string;
      costIndex?: number;
      weights?: { fuel: number; time: number; co2: number };
      departureInput?: string;
    },
  ) => {
    const origin = originArg ?? selectedOrigin;
    const dest = destArg ?? selectedDest;
    const acType = overrides?.aircraftType ?? aircraftType;
    const ci = overrides?.costIndex ?? costIndex;
    const w = overrides?.weights ?? weights;
    const depInput = overrides?.departureInput ?? departureInput;
    if (!origin || !dest) {
      setError('Kalkış ve varış havalimanı seçiniz');
      return;
    }
    setLoading(true);
    setError('');
    setValidation(null);
    setValidationError('');
    try {
      const data = await optimizeRoute({
        origin: origin.icao,
        destination: dest.icao,
        aircraft_type: acType,
        optimization_weights: {
          fuel: w.fuel / 100,
          time: w.time / 100,
          co2: w.co2 / 100,
        },
        cost_index: ci,
        departure_time: localInputToIso(depInput),
        avoid_airspace: avoidAirspace,
        record: true,
      });

      if (data && 'error' in data && data.error) {
        setError(String(data.error));
      } else {
        setResult(data);
        setStatsRefreshKey(k => k + 1);

        // Harita görünümü: optimize rota waypoint'lerine fitBounds
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
          setMapCenter([
            (origin.latitude + dest.latitude) / 2,
            (origin.longitude + dest.longitude) / 2,
          ]);
          setMapZoom(4);
        }

        if (data?.savings) {
          setLatestSavings({
            fuel_saved_kg: data.savings.fuel_saved_kg || 0,
            time_saved_min: data.savings.time_saved_min || 0,
            co2_saved_kg: data.savings.co2_saved_kg || 0,
            cost_saved_usd: data.savings.cost_saved_usd || 0,
          });
        }
      }
    } catch (e) {
      setError(`Optimizasyon hatası: ${e}`);
    }
    setLoading(false);
  }, [selectedOrigin, selectedDest, aircraftType, weights, costIndex, departureInput, avoidAirspace]);

  /* ── URL'den durum geri yükleme + otomatik çalıştırma ─────── */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const originIcao = params.get('origin');
    const destIcao = params.get('destination');
    if (!originIcao || !destIcao || autoRunRef.current) return;
    autoRunRef.current = true;

    const ci = params.get('ci');
    const fuel = params.get('fuel');
    const time = params.get('time');
    const co2 = params.get('co2');
    const aircraft = params.get('aircraft');
    const dep = params.get('dep');

    if (ci && Number.isFinite(Number(ci))) setCostIndex(Math.max(0, Math.min(200, Number(ci))));
    if (fuel && time && co2) {
      setWeights({ fuel: Number(fuel), time: Number(time), co2: Number(co2) });
    }
    if (aircraft) setAircraftType(aircraft);
    if (dep) setDepartureInput(dep);

    Promise.all([getAirport(originIcao), getAirport(destIcao)])
      .then(([origin, dest]) => {
        if (!origin?.icao || !dest?.icao) return;
        selectAirport(origin, 'origin');
        selectAirport(dest, 'dest');
        if (params.get('auto') === '1') {
          const parsedWeights = (fuel && time && co2)
            ? { fuel: Number(fuel), time: Number(time), co2: Number(co2) }
            : undefined;
          setTimeout(() => handleOptimize(origin, dest, {
            aircraftType: aircraft ?? undefined,
            costIndex: ci ? Number(ci) : undefined,
            weights: parsedWeights,
            departureInput: dep ?? '',
          }), 50);
        }
      })
      .catch(() => { /* geçersiz link */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /* ── paylaşım linki / JSON / rapor ────────────────────────── */
  const shareUrl = useMemo(() => {
    if (!selectedOrigin || !selectedDest) return '';
    const params = new URLSearchParams({
      origin: selectedOrigin.icao,
      destination: selectedDest.icao,
      aircraft: aircraftType,
      ci: String(costIndex),
      fuel: String(weights.fuel),
      time: String(weights.time),
      co2: String(weights.co2),
      auto: '1',
    });
    if (departureInput) params.set('dep', departureInput);
    return `${window.location.origin}/optimizer?${params.toString()}`;
  }, [selectedOrigin, selectedDest, aircraftType, costIndex, weights, departureInput]);

  const handleShare = async () => {
    if (!shareUrl) return;
    try {
      await navigator.clipboard.writeText(shareUrl);
      setShareState('copied');
    } catch {
      setShareState('failed');
    }
    setTimeout(() => setShareState('idle'), 2500);
  };

  const handleDownloadJson = () => {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `skyoptimizer-${result.origin.icao}-${result.destination.icao}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handlePrint = () => window.print();

  /* ── gerçek uçuş doğrulama ───────────────────────────────── */
  const handleValidate = async () => {
    if (!selectedOrigin || !selectedDest) return;
    setValidationLoading(true);
    setValidationError('');
    try {
      const data = await validateRoute({
        origin: selectedOrigin.icao,
        destination: selectedDest.icao,
        aircraft_type: aircraftType,
        cost_index: costIndex,
        optimization_weights: {
          fuel: weights.fuel / 100,
          time: weights.time / 100,
          co2: weights.co2 / 100,
        },
        hours: 12,
      });
      setValidation(data);
    } catch (e) {
      setValidationError(`Doğrulama hatası: ${e}`);
    }
    setValidationLoading(false);
  };

  /* ── hava sahası katmanı ─────────────────────────────────── */
  useEffect(() => {
    if (showAirspaces && !airspaceData) {
      getAirspaces()
        .then(setAirspaceData)
        .catch(() => setShowAirspaces(false));
    }
  }, [showAirspaces, airspaceData]);

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

        routeLine = optRoute
          ? toPolyline(optRoute.waypoints)
          : [
              [selectedOrigin.latitude, selectedOrigin.longitude],
              [selectedDest.latitude, selectedDest.longitude],
            ];

        const lats = routeLine.map(p => p[0]);
        const lons = routeLine.map(p => p[1]);
        const pad = 4;
        data = await getLiveFlights({
          lamin: Math.max(-85, Math.min(...lats) - pad),
          lamax: Math.min(85, Math.max(...lats) + pad),
          lomin: Math.max(-180, Math.min(...lons) - pad),
          lomax: Math.min(180, Math.max(...lons) + pad),
        });
      }

      if (data?.flights) {
        let flights = data.flights;

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
      setSelectedFlight(null);
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [showTraffic, fetchTraffic]);

  // Seçili uçağın verileri her yenilemede tazelensin
  useEffect(() => {
    if (!selectedFlight) return;
    const fresh = liveFlights.find(f => f.icao24 === selectedFlight.icao24);
    if (fresh && fresh !== selectedFlight) setSelectedFlight(fresh);
  }, [liveFlights, selectedFlight]);

  /* ── ikon / canvas eşiği ──────────────────────────────────── */
  const useAircraftIcons = liveFlights.length <= 900;

  const classCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const f of liveFlights) {
      const key = f.aircraft_class || 'unknown';
      counts[key] = (counts[key] ?? 0) + 1;
    }
    return counts;
  }, [liveFlights]);

  /* ═══════════════ JSX ═══════════════════════════════════════════ */
  return (
    <div className="dark min-h-screen bg-[hsl(224,71%,4%)] text-white font-mono">
      {/* ── Header ────────────────────────────────────────────── */}
      <header className="border-b border-cyan-500/20 bg-black/60 backdrop-blur-sm sticky top-0 z-[1000] print:hidden">
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
            {config && <span className="hidden md:inline text-cyan-500/30">v{config.version}</span>}
          </div>
        </div>
      </header>

      {/* ── İki-sütun layout ─────────────────────────────────── */}
      <div className="flex flex-col lg:flex-row h-[calc(100vh-41px)] print:block print:h-auto">

        {/* ══ Sol Panel ═══════════════════════════════════════════ */}
        <div className="w-full lg:w-[340px] overflow-y-auto border-r border-cyan-500/10 bg-black/40 panel-scroll print:hidden">
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
                  {aircraftOptions.map(opt => (
                    <option key={opt.code} value={opt.code}>{opt.code} — {opt.name}</option>
                  ))}
                </select>
              </div>

              {/* Cost Index */}
              <div className="mb-3">
                <div className="flex items-center justify-between">
                  <label className="text-[9px] text-gray-500 uppercase tracking-wider flex items-center gap-1">
                    <Gauge size={10} /> COST INDEX
                  </label>
                  <span className="text-[10px] text-cyan-300 font-bold tabular-nums">{costIndex}</span>
                </div>
                <input
                  type="range" min="0" max="200" step="5" value={costIndex}
                  onChange={e => setCostIndex(Number(e.target.value))}
                  className="w-full mt-1.5 h-1.5 bg-gray-800 rounded-full appearance-none cursor-pointer accent-cyan-500"
                />
                <div className="flex justify-between text-[8px] text-gray-600 mt-0.5">
                  <span>LRC · ekonomik</span>
                  <span>ECON</span>
                  <span>HSC · hızlı</span>
                </div>
                <p className="text-[8px] text-gray-600 leading-snug mt-1">
                  Havayollarının hız–yakıt takası. Düşük CI az yakıt/uçak yavaş,
                  yüksek CI hızlı/çok yakıt.
                </p>
              </div>

              {/* Kalkış zamanı */}
              <div className="mb-3">
                <div className="flex items-center justify-between">
                  <label className="text-[9px] text-gray-500 uppercase tracking-wider flex items-center gap-1">
                    <Clock size={10} /> KALKIŞ ZAMANI (GFS TAHMİNİ)
                  </label>
                  {departureInput && (
                    <button
                      onClick={() => setDepartureInput('')}
                      className="text-[8px] text-gray-500 hover:text-cyan-400"
                    >
                      SIFIRLA
                    </button>
                  )}
                </div>
                <input
                  type="datetime-local"
                  value={departureInput}
                  onChange={e => setDepartureInput(e.target.value)}
                  className="w-full mt-1 bg-black/60 border border-cyan-500/20 rounded-lg px-3 py-2 text-xs text-cyan-300 focus:border-cyan-500/50 focus:outline-none [color-scheme:dark]"
                />
                <div className="flex gap-1 mt-1.5">
                  {[
                    { label: 'ŞİMDİ', hours: 0 },
                    { label: '+6s', hours: 6 },
                    { label: '+12s', hours: 12 },
                    { label: '+24s', hours: 24 },
                  ].map(opt => (
                    <button
                      key={opt.label}
                      onClick={() => {
                        if (opt.hours === 0) {
                          setDepartureInput('');
                        } else {
                          const target = new Date(Date.now() + opt.hours * 3600_000);
                          setDepartureInput(isoToLocalInput(target.toISOString()));
                        }
                      }}
                      className="flex-1 py-1 rounded border border-gray-800 text-[8px] text-gray-500 hover:text-cyan-400 hover:border-cyan-500/30 transition-colors"
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
                {result?.departure_time?.note && (
                  <p className="mt-1 text-[8px] text-amber-400/80 leading-snug">
                    {result.departure_time.note}
                  </p>
                )}
              </div>

              {/* Kısıtlı hava sahası */}
              <label className="flex items-center gap-2 text-[9px] text-gray-500 mb-3 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={avoidAirspace}
                  onChange={e => setAvoidAirspace(e.target.checked)}
                  className="accent-cyan-500"
                />
                Yasak/sınırlı hava sahalarından kaçın
              </label>

              {/* Optimize butonu */}
              <button
                onClick={() => handleOptimize()}
                disabled={loading || !selectedOrigin || !selectedDest}
                className="w-full mt-1 px-4 py-2.5 bg-cyan-500/10 text-cyan-400 border border-cyan-500/50 rounded-lg text-xs hover:bg-cyan-500/20 hover:shadow-[0_0_20px_rgba(0,212,255,0.15)] transition-all glow-primary disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center gap-2 active:scale-[0.98]"
              >
                {loading ? <Loader2 size={14} className="animate-spin" /> : <Plane size={14} />}
                {loading ? 'OPTİMİZE EDİLİYOR...' : '✈ ROTAYI OPTİMİZE ET'}
              </button>
              {error && <p className="text-red-400 text-[10px] mt-2">{error}</p>}

              {/* Paylaşım */}
              {result && (
                <div className="mt-2 grid grid-cols-3 gap-1">
                  <button
                    onClick={handleShare}
                    className="py-1.5 rounded-md border border-gray-800 text-[8px] text-gray-400 hover:text-cyan-400 hover:border-cyan-500/30 transition-colors flex items-center justify-center gap-1"
                  >
                    {shareState === 'copied' ? <Check size={9} /> : <Share2 size={9} />}
                    {shareState === 'copied' ? 'KOPYALANDI' : shareState === 'failed' ? 'HATA' : 'PAYLAŞ'}
                  </button>
                  <button
                    onClick={handleDownloadJson}
                    className="py-1.5 rounded-md border border-gray-800 text-[8px] text-gray-400 hover:text-cyan-400 hover:border-cyan-500/30 transition-colors flex items-center justify-center gap-1"
                  >
                    <Download size={9} /> JSON
                  </button>
                  <button
                    onClick={handlePrint}
                    className="py-1.5 rounded-md border border-gray-800 text-[8px] text-gray-400 hover:text-cyan-400 hover:border-cyan-500/30 transition-colors flex items-center justify-center gap-1"
                  >
                    <Printer size={9} /> RAPOR
                  </button>
                </div>
              )}
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
              <p className="mt-2 pt-2 border-t border-gray-800 text-[9px] leading-snug text-gray-600">
                Ağırlıklar mutlak maliyete uygulanır: yakıt
                {result?.comparison_basis?.fuel_price_usd_per_kg
                  ? ` ${result.comparison_basis.fuel_price_usd_per_kg} USD/kg`
                  : ' 0.80 USD/kg'},
                süre
                {result?.comparison_basis?.time_cost_usd_per_min
                  ? ` ${result.comparison_basis.time_cost_usd_per_min} USD/dk`
                  : ' 25 USD/dk'},
                CO₂ 0.08 USD/kg. Cost index hızı, ağırlıklar da rota/irtifayı seçer.
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

                  {liveFlights.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-x-2.5 gap-y-1">
                      {Object.entries(classCounts)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 6)
                        .map(([cls, count]) => (
                          <span
                            key={cls}
                            className="text-[8px] flex items-center gap-1 text-gray-500"
                          >
                            <span dangerouslySetInnerHTML={{ __html: aircraftLegendSvg(cls, 11) }} />
                            {AIRCRAFT_CLASS_LABELS[cls] ?? cls}
                            <span className="tabular-nums" style={{ color: AIRCRAFT_CLASS_COLORS[cls] }}>
                              {count}
                            </span>
                          </span>
                        ))}
                    </div>
                  )}

                  {liveFlights.length > 900 && (
                    <p className="mt-1 text-[8px] text-gray-600 leading-snug">
                      Yoğun trafikte (900+ uçak) performans için nokta gösterimi
                      kullanılıyor. Rota modunda ikonlar görünür.
                    </p>
                  )}

                  {trafficMode === 'route' && (!selectedOrigin || !selectedDest) && (
                    <p className="mt-1 text-[9px] text-gray-500 leading-snug">
                      Rota hava sahası için kalkış ve varış seçilmeli.
                    </p>
                  )}
                  {trafficError && (
                    <p className="mt-1 text-[9px] text-red-400/80 leading-snug">{trafficError}</p>
                  )}
                  <p className="mt-1 text-[8px] text-gray-600 leading-snug">
                    Bir uçağa tıklayınca tip, operatör ve rota detayı açılır.
                  </p>
                </>
              )}
            </div>

            {/* -- Hava Durumu -- */}
            {result && (
              <div className="fade-in-up space-y-2">
                <WeatherCard data={result.weather?.origin ?? null} role="KALKIŞ" />
                <WeatherCard data={result.weather?.destination ?? null} role="VARIŞ" />
              </div>
            )}

            {/* -- Tasarruf Paneli -- */}
            {savings && result && (
              <div className="glass-card rounded-xl p-4 fade-in-up">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="text-xs font-bold text-emerald-400 flex items-center gap-2">
                    <Wind size={14} /> TASARRUF
                  </h2>
                  <span className="text-[9px] text-gray-500">
                    {result.departure_time?.hours_ahead
                      ? `+${result.departure_time.hours_ahead}s tahmini`
                      : 'şimdi'}
                  </span>
                </div>

                {/* Fiziksel uygulanabilirlik */}
                {!result.feasibility.feasible && (
                  <div className="mb-2 flex items-start gap-1.5 rounded-lg border border-red-500/30 bg-red-500/10 p-2">
                    <AlertTriangle size={12} className="text-red-400 shrink-0 mt-0.5" />
                    <p className="text-[9px] text-red-300/90 leading-snug">
                      {result.feasibility.note}
                    </p>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-emerald-500/10 border border-emerald-500/30 rounded-lg p-2 text-center">
                    <div className="text-emerald-400 text-lg font-bold tabular-nums">{fmt(savings.fuel_saved_kg)}</div>
                    <div className="text-gray-500 text-[8px]">KG YAKIT</div>
                  </div>
                  <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-2 text-center">
                    <div className="text-blue-400 text-lg font-bold tabular-nums">{fmt(savings.time_saved_min, 1)}</div>
                    <div className="text-gray-500 text-[8px]">DK SÜRE</div>
                  </div>
                  <div className="bg-amber-500/10 border border-amber-500/30 rounded-lg p-2 text-center">
                    <div className="text-amber-400 text-lg font-bold tabular-nums">{fmt(savings.co2_saved_kg)}</div>
                    <div className="text-gray-500 text-[8px]">KG CO₂</div>
                  </div>
                  <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-2 text-center">
                    <div className="text-purple-400 text-lg font-bold tabular-nums">${fmt(savings.cost_saved_usd)}</div>
                    <div className="text-gray-500 text-[8px]">MALİYET</div>
                  </div>
                </div>

                <div className="mt-2 flex items-center justify-between rounded-lg bg-black/30 border border-gray-800 px-2 py-1.5">
                  <span className="text-[9px] text-gray-500">AĞIRLIKLI MALİYET</span>
                  <span className="text-[10px] text-cyan-300 font-bold tabular-nums">
                    ${fmt(savings.score_standard_usd)} → ${fmt(savings.score_optimized_usd)}
                    <span className="text-emerald-400 ml-1">
                      (%{fmt(savings.score_saved_percent, 2)})
                    </span>
                  </span>
                </div>

                {/* Rota karşılaştırma */}
                <div className="mt-3 space-y-1.5">
                  <RouteRow
                    color="bg-red-500"
                    label="Standart"
                    distance={stdRoute?.total_distance_nm}
                    fuel={stdRoute?.estimated_fuel_kg}
                    time={stdRoute?.estimated_time_min}
                    level={stdRoute?.cruise_altitude_ft}
                  />
                  <RouteRow
                    color="bg-cyan-400"
                    label="Optimize"
                    distance={optRoute?.total_distance_nm}
                    fuel={optRoute?.estimated_fuel_kg}
                    time={optRoute?.estimated_time_min}
                    level={optRoute?.cruise_altitude_ft}
                  />
                  {!result.has_measurable_savings ? (
                    <div className="text-[10px] text-gray-400 mt-1 leading-relaxed">
                      Bu rota için ölçülebilir fark yok — en kısa yol zaten
                      maliyet-optimal.
                    </div>
                  ) : (
                    <div className={`text-[10px] font-bold mt-1 ${
                      savings.fuel_saved_kg >= 0 ? 'text-cyan-400' : 'text-red-400'
                    }`}>
                      {savings.fuel_saved_kg >= 0 ? '▲' : '▼'} %
                      {Math.abs(savings.fuel_saved_percent).toFixed(2)} yakıt
                      {savings.fuel_saved_kg >= 0 ? ' tasarrufu' : ' artışı'}
                      {savings.distance_delta_nm !== 0 && (
                        <span className="text-gray-500 font-normal">
                          {' '}(rota {Math.abs(savings.distance_delta_nm).toFixed(0)} NM{' '}
                          {savings.distance_delta_nm > 0 ? 'daha uzun' : 'daha kısa'})
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Uçuş profili */}
                {optRoute && (
                  <div className="mt-3 pt-3 border-t border-gray-800 space-y-2">
                    <div className="grid grid-cols-3 gap-1.5 text-center">
                      <MiniInfo label="CRUISE" value={optRoute.cruise_altitude_ft ? `FL${Math.round(optRoute.cruise_altitude_ft / 100)}` : '—'} />
                      <MiniInfo label="MACH" value={optRoute.mach?.toFixed(3) ?? '—'} />
                      <MiniInfo label="TAS" value={optRoute.tas_kts ? `${optRoute.tas_kts} kt` : '—'} />
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      <MiniInfo label="KALKIŞ KÜTLESİ" value={`${fmt(optRoute.takeoff_mass_kg)} kg`} />
                      <MiniInfo label="İNİŞ KÜTLESİ" value={`${fmt(optRoute.landing_mass_kg)} kg`} />
                    </div>
                    <div>
                      <div className="text-[8px] text-gray-500 mb-1">YAKIT FAZ DAĞILIMI</div>
                      <PhaseBar phases={optRoute.phases} />
                    </div>
                    <div className="text-[8px] text-gray-600 leading-snug">
                      Tırmanma {fmtClock(optRoute.phases.climb.time_min)} · cruise{' '}
                      {fmtClock(optRoute.phases.cruise.time_min)} · alçalma{' '}
                      {fmtClock(optRoute.phases.descent.time_min)}
                    </div>
                  </div>
                )}

                {/* İrtifa katmanları */}
                {result.levels?.length > 0 && (
                  <details className="mt-3 pt-3 border-t border-gray-800">
                    <summary className="text-[9px] text-cyan-400/80 cursor-pointer hover:text-cyan-300 list-none flex items-center gap-1">
                      <Layers size={10} /> İRTİFA KATMANI TARAMASI ▾
                    </summary>
                    <div className="mt-1.5 overflow-x-auto">
                      <table className="w-full text-[8px]">
                        <thead>
                          <tr className="text-gray-600 border-b border-gray-800">
                            <th className="text-left py-1 font-normal">KATMAN</th>
                            <th className="text-right font-normal">YAKIT (kg)</th>
                            <th className="text-right font-normal">SÜRE (dk)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.levels.map(lv => (
                            <tr
                              key={lv.level_mb}
                              className={`border-b border-gray-900 ${
                                lv.selected_optimized ? 'text-cyan-300' : 'text-gray-500'
                              }`}
                            >
                              <td className="py-1">
                                {lv.label}
                                {lv.selected_optimized && <span className="ml-1 text-cyan-500">●</span>}
                                {lv.selected_standard && !lv.selected_optimized && (
                                  <span className="ml-1 text-red-400">○</span>
                                )}
                              </td>
                              <td className="text-right tabular-nums">
                                {fmt(lv.optimized_fuel_kg)}
                                <span className="text-gray-700"> / {fmt(lv.standard_fuel_kg)}</span>
                              </td>
                              <td className="text-right tabular-nums">
                                {fmt(lv.optimized_time_min)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="mt-1 text-[8px] text-gray-600 leading-snug">
                        ● seçilen optimize katman · ○ seçilen standart katman.
                        Her katman kendi rüzgârıyla değerlendirilir.
                      </p>
                    </div>
                  </details>
                )}

                {/* Graf / performans */}
                {result.graph_stats && (
                  <div className="mt-2 text-[8px] text-gray-600 tabular-nums">
                    GRAF {fmt(result.graph_stats.nodes)} düğüm · {fmt(result.graph_stats.edges)} kenar
                    {result.graph_stats.topology_ms != null && (
                      <> · topoloji {result.graph_stats.topology_ms} ms</>
                    )}
                    {result.graph_stats.total_ms != null && (
                      <> · uçtan uca {result.graph_stats.total_ms} ms</>
                    )}
                  </div>
                )}

                {/* Hava sahası */}
                <div className="mt-3 pt-3 border-t border-gray-800 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[9px] text-gray-500 flex items-center gap-1">
                      <AlertTriangle size={10} className="text-amber-500/70" /> KISITLI HAVA SAHASI
                    </span>
                    <button
                      onClick={() => setShowAirspaces(v => !v)}
                      className={`text-[8px] px-1.5 py-0.5 rounded border transition-colors ${
                        showAirspaces
                          ? 'border-red-500/40 text-red-300 bg-red-500/10'
                          : 'border-gray-800 text-gray-500 hover:text-gray-300'
                      }`}
                    >
                      {showAirspaces ? 'GİZLE' : 'HARİTADA GÖSTER'}
                    </button>
                  </div>
                  <div className="text-[9px] text-gray-400 leading-snug">
                    {result.airspace.avoidance === 'disabled'
                      ? 'Uyarı: kaçınma rotayı tıkadı; kısıtsız graf kullanıldı.'
                      : result.airspace.avoidance === 'active'
                        ? `${result.airspace.blocked_edges} kenar hava sahası nedeniyle elendi.`
                        : 'Kaçınma kapalı.'}
                    {result.airspace.areas_on_route.length > 0 && (
                      <span className="block mt-0.5 text-amber-400/80">
                        Rota bölgesinde: {result.airspace.areas_on_route.map(a => a.id).join(', ')}
                      </span>
                    )}
                  </div>
                  {result.airspace.areas_on_route.length > 0 && (
                    <div className="space-y-0.5">
                      {result.airspace.areas_on_route.slice(0, 4).map(area => (
                        <div key={area.id} className="text-[8px] text-gray-500 truncate">
                          <span className="text-amber-500/80">{area.id}</span> {area.name}
                          <span className="text-gray-700"> ({area.floor}-{area.ceiling})</span>
                        </div>
                      ))}
                    </div>
                  )}
                  {result.airspace.blocked_edges > 0 && result.airspace.areas_on_route.length === 0 && (
                    <p className="text-[8px] text-gray-600 leading-snug">
                      Saha verisi küçük bir gösterim setidir; gerçek kapsam için
                      AIP/OpenAIP yüklenir.
                    </p>
                  )}
                </div>

                {/* Yöntem notları */}
                <button
                  onClick={() => setShowMethodNotes(v => !v)}
                  className="mt-3 w-full flex items-center justify-between text-[8px] text-gray-500 hover:text-cyan-400 transition-colors"
                >
                  <span>MODEL VARSAYIMLARI</span>
                  <ChevronDown size={10} className={`transition-transform ${showMethodNotes ? 'rotate-180' : ''}`} />
                </button>
                {showMethodNotes && (
                  <div className="mt-1 space-y-1 text-[8px] text-gray-500 leading-snug">
                    {Object.entries(result.method_notes ?? config?.method_notes ?? {}).map(([key, value]) => (
                      <p key={key}>
                        <span className="text-cyan-500/70">{key}:</span> {value}
                      </p>
                    ))}
                    <p className="text-gray-600">
                      Ağırlıklar: yakıt %{Math.round((result.comparison_basis.weights.fuel ?? 0) * 100)},
                      süre %{Math.round((result.comparison_basis.weights.time ?? 0) * 100)},
                      CO₂ %{Math.round((result.comparison_basis.weights.co2 ?? 0) * 100)} ·
                      CI {result.comparison_basis.cost_index} ·
                      {' '}{result.wind_info.sample_points} rüzgâr örneği.
                    </p>
                    {result.warnings?.map(w => (
                      <p key={w} className="text-amber-500/80">{w}</p>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* -- Gerçek Uçuş Doğrulama -- */}
            {result && (
              <ValidationCard
                result={validation}
                loading={validationLoading}
                error={validationError}
                onRun={handleValidate}
              />
            )}

            {/* -- Birikimli Tasarruf -- */}
            <div className="fade-in-up" style={{ animationDelay: '0.2s' }}>
              <StatsPanel latestSavings={latestSavings} refreshKey={statsRefreshKey} />
            </div>
          </div>
        </div>

        {/* ══ Harita ══════════════════════════════════════════════ */}
        <div className="flex-1 relative print:hidden">
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
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
              attribution='Esri, HERE, Garmin, &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> katkıcıları'
              maxZoom={16}
            />
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}"
              maxZoom={16}
            />

            {/* Kısıtlı hava sahaları */}
            {showAirspaces && airspaceData?.geojson && (
              <GeoJSON
                key={`airspace-${airspaceData.meta.count}`}
                data={airspaceData.geojson}
                style={{
                  color: '#ef4444',
                  weight: 1,
                  opacity: 0.7,
                  fillColor: '#ef4444',
                  fillOpacity: 0.12,
                  dashArray: '4,4',
                }}
              />
            )}

            {/* Optimize rota — cyan parlak çizgi */}
            {optRoute && toSegments(optRoute.waypoints).map((segment, i) => (
              <Polyline
                key={`opt-${i}`}
                positions={segment}
                pathOptions={{ color: '#00d4ff', weight: 4, opacity: 0.85 }}
              />
            ))}

            {/* Standart rota — kırmızı kesik çizgi */}
            {stdRoute && toSegments(stdRoute.waypoints).map((segment, i) => (
              <Polyline
                key={`std-${i}`}
                positions={segment}
                pathOptions={{ color: '#ef4444', weight: 2.5, opacity: 0.7, dashArray: '10,8' }}
              />
            ))}

            {/* Havalimanı marker'ları */}
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

            {/* Optimize rota waypoint noktaları */}
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
                Rota modunda (~binlerce değil, yüzlerce uçak) tip ikonları
                kullanılır; dünya modunda 10.000+ uçak dönebildiği için
                performans amacıyla canvas noktalarına düşülür. */}
            {showTraffic && (useAircraftIcons
              ? liveFlights.map(flight => {
                  if (!flight.latitude || !flight.longitude) return null;
                  const isSelected = selectedFlight?.icao24 === flight.icao24;
                  return (
                    <Marker
                      key={flight.icao24}
                      position={[flight.latitude, flight.longitude]}
                      icon={aircraftIcon(flight.aircraft_class, flight.true_track, { selected: isSelected })}
                      eventHandlers={{
                        click: () => setSelectedFlight(flight),
                      }}
                      zIndexOffset={isSelected ? 1000 : 0}
                    />
                  );
                })
              : liveFlights.map(flight => {
                  if (!flight.latitude || !flight.longitude) return null;
                  return (
                    <CircleMarker
                      key={flight.icao24}
                      center={[flight.latitude, flight.longitude]}
                      radius={selectedFlight?.icao24 === flight.icao24 ? 5 : 2.5}
                      pathOptions={{
                        color: selectedFlight?.icao24 === flight.icao24 ? '#00d4ff' : '#f59e0b',
                        weight: 1,
                        fillColor: selectedFlight?.icao24 === flight.icao24 ? '#00d4ff' : '#fbbf24',
                        fillOpacity: 0.85,
                      }}
                      eventHandlers={{ click: () => setSelectedFlight(flight) }}
                    />
                  );
                }))}
          </MapContainer>

          {/* Seçili uçak detay paneli */}
          {selectedFlight && (
            <AircraftDetailPanel
              flight={selectedFlight}
              onClose={() => setSelectedFlight(null)}
              onOptimizeRoute={(originIcao, destIcao) => {
                Promise.all([getAirport(originIcao), getAirport(destIcao)])
                  .then(([origin, dest]) => {
                    if (!origin?.icao || !dest?.icao) return;
                    selectAirport(origin, 'origin');
                    selectAirport(dest, 'dest');
                    setSelectedFlight(null);
                    handleOptimize(origin, dest);
                  })
                  .catch(() => { /* bilinmeyen havalimanı */ });
              }}
            />
          )}

          {/* Sonuç özeti — haritanın üzerinde, kaydırmadan görünür */}
          {result && (
            <div className="hidden lg:flex absolute top-4 right-4 z-[1000] glass-card rounded-lg px-3 py-2 gap-4 items-center pointer-events-none">
              <div>
                <div className="text-[8px] text-gray-500 tracking-wider">TASARRUF</div>
                <div className={`text-xs font-bold tabular-nums ${
                  result.savings.fuel_saved_kg > 0 ? 'text-emerald-400' : 'text-amber-400'
                }`}>
                  {result.savings.fuel_saved_kg > 0 ? '−' : '+'}
                  {Math.abs(result.savings.fuel_saved_kg).toFixed(0)} kg
                </div>
              </div>
              <div className="w-px h-7 bg-gray-800" />
              <div>
                <div className="text-[8px] text-gray-500 tracking-wider">SÜRE</div>
                <div className="text-xs font-bold text-cyan-300 tabular-nums">
                  {result.savings.time_saved_min.toFixed(0)} dk
                </div>
              </div>
              <div className="w-px h-7 bg-gray-800" />
              <div>
                <div className="text-[8px] text-gray-500 tracking-wider">İRTİFA</div>
                <div className="text-xs font-bold text-cyan-300 tabular-nums">
                  FL{Math.round(result.optimized_route.cruise_altitude_ft / 100)}
                </div>
              </div>
              {!result.has_measurable_savings && (
                <span className="text-[9px] text-amber-400 border border-amber-500/30 rounded px-1.5 py-0.5">
                  ÖLÇÜLEBİLİR FARK YOK
                </span>
              )}
            </div>
          )}

          {/* Legend */}
          <div className="absolute bottom-4 right-4 z-[1000] glass-card rounded-lg p-3 max-w-[220px]">
            <div className="text-[9px] font-mono text-gray-400 space-y-1.5">
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-red-500 rounded" style={{ borderStyle: 'dashed' }} />
                <span>Standart Rota</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="w-4 h-0.5 bg-cyan-400 rounded" />
                <span>Optimize Rota</span>
              </div>
              <div className="flex items-center gap-2">
                <MapPin size={8} className="text-cyan-400" />
                <span>Havalimanı</span>
              </div>
              {showAirspaces && (
                <div className="flex items-center gap-2">
                  <div className="w-4 h-2 bg-red-500/20 border border-red-500/50 rounded-sm" />
                  <span>Kısıtlı Saha</span>
                </div>
              )}
              {showTraffic && (
                <div className="pt-1 border-t border-gray-800 space-y-0.5">
                  <div className="text-amber-400">Canlı Trafik ({trafficCount})</div>
                  {Object.entries(classCounts)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 5)
                    .map(([cls, count]) => (
                      <div key={cls} className="flex items-center gap-1.5 text-[8px] text-gray-500">
                        <span dangerouslySetInnerHTML={{ __html: aircraftLegendSvg(cls, 12) }} />
                        {AIRCRAFT_CLASS_LABELS[cls] ?? cls} · {count}
                      </div>
                    ))}
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

      {/* ── Yazdırma raporu (yalnızca print) ─────────────────── */}
      {result && <PrintReport result={result} />}
    </div>
  );
}

/* ── Küçük yardımcı bileşenler ────────────────────────────────── */

function MiniInfo({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-black/40 border border-gray-800 rounded-lg px-1.5 py-1">
      <div className="text-[7px] text-gray-500">{label}</div>
      <div className="text-[10px] text-gray-300 font-bold tabular-nums">{value}</div>
    </div>
  );
}

function RouteRow({
  color, label, distance, fuel, time, level,
}: {
  color: string; label: string;
  distance?: number; fuel?: number; time?: number; level?: number;
}) {
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <div className={`w-3 h-0.5 ${color} rounded`} />
      <span className="text-gray-400 flex-1">
        {label}: {fmt(distance)} NM, {fmt(fuel)} kg, {fmt(time, 1)} dk
        {level ? `, FL${Math.round(level / 100)}` : ''}
      </span>
    </div>
  );
}

/**
 * Tarayıcı yazdırma raporu.
 *
 * PDF bağımlılığı eklemek yerine yazdırma için tasarlanmış bir sayfa
 * kullanılır: kullanıcı "RAPOR" → tarayıcıdan "PDF olarak kaydet".
 */
function PrintReport({ result }: { result: OptimizeResult }) {
  const s = result.savings;
  return (
    <div className="hidden print:block print:text-black print:bg-white p-8 font-mono text-[11px] leading-relaxed">
      <div className="flex items-center justify-between border-b border-gray-400 pb-2 mb-4">
        <div>
          <div className="text-lg font-bold">SKYOPTIMIZER AI — ROTA RAPORU</div>
          <div className="text-[10px]">
            {result.origin.icao} ({result.origin.name}) → {result.destination.icao} ({result.destination.name})
          </div>
        </div>
        <div className="text-right text-[10px]">
          <div>Uçak: {result.aircraft_type}</div>
          <div>Cost Index: {result.aircraft_performance.cost_index}</div>
          <div>Kalkış: {result.departure_time.resolved_utc}</div>
        </div>
      </div>

      <table className="w-full border-collapse mb-4">
        <thead>
          <tr className="border-b border-gray-400 text-left">
            <th className="py-1">Rota</th>
            <th>Mesafe (NM)</th>
            <th>Yakıt (kg)</th>
            <th>Süre (dk)</th>
            <th>CO₂ (kg)</th>
            <th>Katman</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td className="py-1">Standart (en kısa)</td>
            <td>{fmt(result.standard_route.total_distance_nm)}</td>
            <td>{fmt(result.standard_route.estimated_fuel_kg)}</td>
            <td>{fmt(result.standard_route.estimated_time_min, 1)}</td>
            <td>{fmt(result.standard_route.co2_emission_kg)}</td>
            <td>{result.standard_route.cruise_altitude_ft} ft</td>
          </tr>
          <tr>
            <td className="py-1">Optimize</td>
            <td>{fmt(result.optimized_route.total_distance_nm)}</td>
            <td>{fmt(result.optimized_route.estimated_fuel_kg)}</td>
            <td>{fmt(result.optimized_route.estimated_time_min, 1)}</td>
            <td>{fmt(result.optimized_route.co2_emission_kg)}</td>
            <td>{result.optimized_route.cruise_altitude_ft} ft</td>
          </tr>
        </tbody>
      </table>

      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <div className="font-bold mb-1">Tasarruf</div>
          <div>Yakıt: {fmt(s.fuel_saved_kg)} kg (%{fmt(s.fuel_saved_percent, 2)})</div>
          <div>Süre: {fmt(s.time_saved_min, 1)} dk (%{fmt(s.time_saved_percent, 2)})</div>
          <div>CO₂: {fmt(s.co2_saved_kg)} kg</div>
          <div>Maliyet: ${fmt(s.cost_saved_usd)}</div>
        </div>
        <div>
          <div className="font-bold mb-1">Fizik profili</div>
          <div>Mach {result.optimized_route.mach} · TAS {result.optimized_route.tas_kts} kt</div>
          <div>Kalkış kütlesi: {fmt(result.optimized_route.takeoff_mass_kg)} kg</div>
          <div>İniş kütlesi: {fmt(result.optimized_route.landing_mass_kg)} kg</div>
          <div>Rüzgâr: {result.wind_info.avg_speed_kts} kt / {result.wind_info.avg_direction_deg}°</div>
        </div>
      </div>

      <div className="mb-3">
        <div className="font-bold mb-1">Yakıt fazları</div>
        <div>Tırmanma: {fmt(result.optimized_route.phases.climb.fuel_kg)} kg</div>
        <div>Cruise: {fmt(result.optimized_route.phases.cruise.fuel_kg)} kg</div>
        <div>Alçalma: {fmt(result.optimized_route.phases.descent.fuel_kg)} kg</div>
      </div>

      {!result.feasibility.feasible && (
        <div className="mb-3 border border-red-600 p-2 text-red-700">
          {result.feasibility.note}
        </div>
      )}

      <div className="text-[9px] text-gray-600 border-t border-gray-400 pt-2">
        Yöntem: OpenAP 2.4 yakıt modeli, cost index {result.aircraft_performance.cost_index},
        3B GFS rüzgârı, kütle azalmalı rota profili. CO₂ = 3.16 × yakıt.
        Bu rapor SkyOptimizer AI tarafından üretilmiştir.
      </div>
    </div>
  );
}
