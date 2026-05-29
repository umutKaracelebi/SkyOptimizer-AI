/**
 * SkyOptimizer AI — Backend API Client
 * FastAPI backend ile iletişim kurar.
 */

const API_BASE = "http://localhost:8000";

// ─── Genel Fetch Helper ─────────────────────────────────────────────

async function apiFetch<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (!response.ok) {
    throw new Error(`API Hatası: ${response.status} ${response.statusText}`);
  }

  return response.json();
}

// ─── Sistem ─────────────────────────────────────────────────────────

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  airports_loaded: number;
}

export interface APIStatus {
  opensky_limits: {
    daily_limit: number;
    requests_today: number;
    remaining: number;
    can_request: boolean;
  };
  cache_stats: {
    hit_count: number;
    miss_count: number;
    hit_rate: string;
  };
}

export async function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/health");
}

export async function getAPIStatus(): Promise<APIStatus> {
  return apiFetch<APIStatus>("/api/status");
}

// ─── Havalimanları ──────────────────────────────────────────────────

export interface Airport {
  icao: string;
  iata: string;
  name: string;
  city: string;
  country: string;
  type: string;
  latitude: number;
  longitude: number;
  elevation_ft: number | null;
}

export interface AirportSearchResult {
  query: string;
  count: number;
  results: Airport[];
}

export async function searchAirports(
  query: string,
  limit: number = 10
): Promise<AirportSearchResult> {
  return apiFetch<AirportSearchResult>(
    `/api/airports/search?q=${encodeURIComponent(query)}&limit=${limit}`
  );
}

export async function getAirport(icao: string): Promise<Airport> {
  return apiFetch<Airport>(`/api/airports/${icao}`);
}

export async function getTurkeyAirports(): Promise<{
  count: number;
  airports: Airport[];
}> {
  return apiFetch(`/api/airports/turkey/all`);
}

// ─── Meteoroloji ────────────────────────────────────────────────────

export interface WeatherData {
  icao: string;
  metar: {
    raw: string;
    temperature_c: number | null;
    wind_speed_kts: number | null;
    wind_direction: number | null;
    flight_category: string | null;
  };
  taf: {
    raw: string;
    valid_from: string;
    valid_to: string;
  };
}

export async function getWeather(icao: string): Promise<WeatherData> {
  return apiFetch<WeatherData>(`/api/weather/${icao}`);
}

export interface WindData {
  latitude: number;
  longitude: number;
  level_mb: number;
  wind_speed_kts: number;
  wind_direction: number;
  source: string;
}

export async function getWinds(
  lat: number,
  lon: number,
  levelMb: number = 300
): Promise<WindData> {
  return apiFetch<WindData>(
    `/api/winds?lat=${lat}&lon=${lon}&level_mb=${levelMb}`
  );
}

// ─── Trafik ─────────────────────────────────────────────────────────

export interface Flight {
  icao24: string;
  callsign: string;
  origin_country: string;
  longitude: number;
  latitude: number;
  altitude_m: number;
  velocity_ms: number;
  true_track: number;
  vertical_rate: number;
}

export interface LiveFlightsResult {
  flights: Flight[];
  count: number;
  from_cache: boolean;
  remaining: number;
}

export async function getLiveFlights(bbox?: {
  lamin: number; lamax: number; lomin: number; lomax: number;
}): Promise<LiveFlightsResult> {
  if (bbox) {
    const qs = `?lamin=${bbox.lamin}&lamax=${bbox.lamax}&lomin=${bbox.lomin}&lomax=${bbox.lomax}`;
    return apiFetch<LiveFlightsResult>(`/api/flights/live${qs}`);
  }
  return apiFetch<LiveFlightsResult>("/api/flights/live");
}

export async function getTrafficInfo(): Promise<{
  region: string;
  aircraft_count: number;
  from_cache: boolean;
  opensky_remaining: number;
}> {
  return apiFetch("/api/traffic");
}

// ─── Optimizasyon ───────────────────────────────────────────────────

export interface OptimizeRequest {
  origin: string;
  destination: string;
  aircraft_type?: string;
  optimization_weights?: {
    fuel: number;
    time: number;
    co2: number;
  };
}

export interface OptimizeResult {
  origin: Airport;
  destination: Airport;
  direct_distance_nm: number;
  estimated_time_min: number;
  origin_weather: Record<string, unknown>;
  destination_weather: Record<string, unknown>;
  optimized_route: unknown;
  standard_route: unknown;
  savings: unknown;
  message: string;
}

export async function optimizeRoute(
  request: OptimizeRequest
): Promise<OptimizeResult> {
  return apiFetch<OptimizeResult>("/api/optimize", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

export async function compareRoutes(
  origin: string,
  destination: string
): Promise<Record<string, unknown>> {
  return apiFetch("/api/compare", {
    method: "POST",
    body: JSON.stringify({ origin, destination }),
  });
}

// ─── Yapay Zekâ (ML) Tahmin ─────────────────────────────────────────

export interface PredictRequest {
  distance_nm: number;
  wind_speed_kts: number;
  wind_direction: number;
  heading: number;
  altitude_ft?: number;
}

export interface PredictionValues {
  fuel_kg: number;
  time_min: number;
  co2_kg: number;
  source: string;
}

export interface PredictResult {
  ai_prediction: PredictionValues | null;
  physics_prediction: PredictionValues;
  model_available: boolean;
}

export async function mlPredict(
  request: PredictRequest
): Promise<PredictResult> {
  return apiFetch<PredictResult>("/api/predict", {
    method: "POST",
    body: JSON.stringify(request),
  });
}
