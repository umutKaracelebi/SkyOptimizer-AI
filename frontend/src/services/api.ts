/**
 * SkyOptimizer AI — Backend API Client
 * FastAPI backend ile iletişim kurar.
 */

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ?? "http://localhost:8000";

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
  airspaces_loaded: number;
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

export interface AircraftTypeOption {
  code: string;
  name: string;
}

export interface AppConfig {
  version: string;
  cost_index: {
    min: number;
    max: number;
    default: number;
    description: string;
  };
  aircraft_types: AircraftTypeOption[];
  default_aircraft: string;
  cruise_levels_hpa: number[];
  method_notes: Record<string, string>;
}

export async function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>("/health");
}

export async function getAPIStatus(): Promise<APIStatus> {
  return apiFetch<APIStatus>("/api/status");
}

export async function getConfig(): Promise<AppConfig> {
  return apiFetch<AppConfig>("/api/config");
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

export interface MetarData {
  icao: string;
  raw?: string;
  temperature_c?: number | null;
  dewpoint_c?: number | null;
  wind_speed_kts?: number | null;
  wind_gust_kts?: number | null;
  wind_direction?: number | null;
  visibility_raw?: string | null;
  visibility_sm?: number | null;
  visibility_m?: number | null;
  weather?: string | null;
  altimeter_hpa?: number | null;
  flight_category?: string | null;
  observation_time?: string | null;
  error?: string;
}

export interface TafData {
  icao: string;
  raw?: string;
  issue_time?: string;
  valid_from?: string;
  valid_to?: string;
  forecasts?: unknown[];
  error?: string;
}

export interface WeatherCard {
  icao: string;
  metar: MetarData;
  taf: TafData;
}

export interface WeatherData {
  icao: string;
  metar: MetarData;
  taf: TafData;
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

// ─── Hava Sahası ────────────────────────────────────────────────────

export interface AirspaceFeature {
  id: string;
  name: string;
  type: string;
  floor: string | null;
  ceiling: string | null;
  source: string | null;
  bbox: [number, number, number, number];
}

export interface AirspaceResponse {
  meta: {
    count: number;
    available: boolean;
    note?: string;
    demo?: boolean;
    features: AirspaceFeature[];
  };
  geojson: GeoJSON.FeatureCollection;
}

export async function getAirspaces(): Promise<AirspaceResponse> {
  return apiFetch<AirspaceResponse>("/api/airspaces");
}

// ─── Trafik ─────────────────────────────────────────────────────────

export type AircraftClass =
  | "heavy"
  | "narrow"
  | "regional"
  | "turboprop"
  | "light"
  | "rotor"
  | "fighter"
  | "military"
  | "unknown";

export interface Flight {
  icao24: string;
  callsign: string;
  origin_country: string;
  longitude: number;
  latitude: number;
  altitude_m: number | null;
  velocity_ms: number | null;
  true_track: number | null;
  vertical_rate: number | null;
  geo_altitude_m?: number | null;
  squawk?: string | null;
  emitter_category?: number | null;
  aircraft_class?: AircraftClass;
  type_code?: string | null;
  operator?: string | null;
}

export interface LiveFlightsResult {
  flights: Flight[];
  count: number;
  from_cache: boolean;
  remaining: number;
  /** Kota/limit nedeniyle boş döndüyse sebebi */
  error?: string;
  timestamp?: number;
  region?: {
    lamin: number; lamax: number; lomin: number; lomax: number;
  };
}

export async function getLiveFlights(
  bbox?: {
    lamin: number; lamax: number; lomin: number; lomax: number;
  },
  enrich: boolean = true
): Promise<LiveFlightsResult> {
  const params = new URLSearchParams();
  if (bbox) {
    params.set("lamin", String(bbox.lamin));
    params.set("lamax", String(bbox.lamax));
    params.set("lomin", String(bbox.lomin));
    params.set("lomax", String(bbox.lomax));
  }
  params.set("enrich", String(enrich));
  return apiFetch<LiveFlightsResult>(`/api/flights/live?${params.toString()}`);
}

export async function getTrafficInfo(): Promise<{
  region: string;
  aircraft_count: number;
  from_cache: boolean;
  opensky_remaining: number;
}> {
  return apiFetch("/api/traffic");
}

// ─── Uçak Kimliği ───────────────────────────────────────────────────

export interface AircraftRoute {
  origin: string;
  destination: string;
  raw: string;
  updated_at?: number | null;
  source: string;
}

export interface AircraftMetadata {
  icao24: string;
  available: boolean;
  reason?: string;
  registration?: string | null;
  type_code?: string | null;
  model?: string | null;
  manufacturer?: string | null;
  operator?: string | null;
  category?: AircraftClass;
  route?: AircraftRoute | null;
  source?: string;
}

export async function getAircraft(
  icao24: string,
  callsign?: string
): Promise<AircraftMetadata> {
  const qs = callsign ? `?callsign=${encodeURIComponent(callsign)}` : "";
  return apiFetch<AircraftMetadata>(`/api/aircraft/${icao24}${qs}`);
}

export interface RecentFlight {
  icao24: string;
  callsign: string;
  departure: string | null;
  destination: string | null;
  first_seen: number;
  last_seen: number;
  departure_distance_m?: number | null;
  arrival_distance_m?: number | null;
}

export async function getRecentFlights(
  airport: string,
  direction: "arrival" | "departure" = "arrival",
  hours: number = 12
): Promise<{
  airport: string;
  hours: number;
  history_limit_hours?: number;
  authenticated?: boolean;
  flights: RecentFlight[];
  count: number;
  error?: string;
}> {
  return apiFetch(
    `/api/flights/recent?airport=${airport}&direction=${direction}&hours=${hours}`
  );
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
  /** 0 = ekonomik (LRC), 200 = hızlı (HSC) */
  cost_index?: number;
  /** ISO-8601 kalkış zamanı; boşsa şimdi */
  departure_time?: string | null;
  avoid_airspace?: boolean;
  record?: boolean;
}

export interface RouteWaypoint {
  id: string;
  name: string;
  latitude: number;
  longitude: number;
  type: string;
}

export interface PhaseInfo {
  time_min: number;
  fuel_kg: number;
  distance_nm: number;
  altitude_ft: number;
}

export interface RoutePhaseBreakdown {
  climb: PhaseInfo;
  cruise: PhaseInfo;
  descent: PhaseInfo;
}

export interface RouteInfo {
  type: "standard" | "optimized";
  waypoints: RouteWaypoint[];
  waypoint_count: number;
  level_mb: number;
  cruise_altitude_ft: number;
  cruise_distance_nm: number;
  total_distance_nm: number;
  estimated_fuel_kg: number;
  estimated_time_min: number;
  co2_emission_kg: number;
  fuel_cost_usd: number;
  takeoff_mass_kg: number;
  landing_mass_kg: number;
  tas_kts: number;
  mach: number;
  avg_ground_speed_kts: number;
  avg_headwind_kts: number;
  cost_index: number;
  feasible: boolean;
  fuel_capacity_kg: number;
  fuel_margin_kg: number;
  phases: RoutePhaseBreakdown;
  mass_samples_kg: number[];
}

export interface SavingsData {
  fuel_saved_kg: number;
  fuel_saved_percent: number;
  time_saved_min: number;
  time_saved_percent: number;
  co2_saved_kg: number;
  cost_saved_usd: number;
  /** Optimize rota standart rotadan kaç NM daha uzun/kısa (negatif = daha kısa) */
  distance_delta_nm: number;
  score_standard_usd: number;
  score_optimized_usd: number;
  score_saved_usd: number;
  score_saved_percent: number;
}

export interface WindInfo {
  sample_points: number;
  positions_per_level?: number;
  levels?: number[];
  spacing_nm?: number;
  corridor_offsets_nm?: number[];
  avg_speed_kts: number;
  avg_direction_deg: number;
  source: string;
}

export interface LevelRow {
  level_mb: number;
  label: string;
  altitude_ft: number;
  wind_samples: number;
  standard_fuel_kg: number;
  optimized_fuel_kg: number;
  standard_time_min: number;
  optimized_time_min: number;
  score_usd: number;
  selected_standard: boolean;
  selected_optimized: boolean;
}

export interface AirspaceInfo {
  avoidance: "active" | "off" | "disabled";
  blocked_edges: number;
  note?: string | null;
  areas_on_route: AirspaceFeature[];
}

export interface DepartureTimeInfo {
  requested: string | null;
  resolved_utc: string;
  hours_ahead: number;
  note: string | null;
}

export interface AircraftPerformanceInfo {
  aircraft_type: string;
  known_type: boolean;
  cost_index: number;
  mach: number;
  cruise_altitude_ft: number;
  takeoff_mass_kg: number;
  landing_mass_kg: number;
  method_notes: Record<string, string>;
}

export interface FeasibilityInfo {
  feasible: boolean;
  fuel_capacity_kg: number;
  fuel_margin_kg: number;
  note: string | null;
}

export interface OptimizeResult {
  origin: Airport;
  destination: Airport;
  aircraft_type: string;
  wind_info: WindInfo;
  departure_time: DepartureTimeInfo;
  weather: {
    origin: WeatherCard | null;
    destination: WeatherCard | null;
  };
  optimized_route: RouteInfo;
  standard_route: RouteInfo;
  savings: SavingsData;
  /** İki rota birebir aynı düğüm dizisini izliyorsa true */
  routes_identical: boolean;
  /** Ölçülebilir tasarruf var mı (%0.1 eşiği) — yoksa "fark yok" gösterilir */
  has_measurable_savings: boolean;
  comparison_basis: {
    description: string;
    weights: { fuel: number; time: number; co2: number };
    wind_samples: number;
    wind_levels?: Record<string, number>;
    cost_index?: number;
    time_cost_usd_per_min?: number;
    fuel_price_usd_per_kg?: number;
  };
  levels: LevelRow[];
  airspace: AirspaceInfo;
  feasibility: FeasibilityInfo;
  optimization_reverted: boolean;
  graph_stats: {
    nodes: number;
    edges: number;
    great_circle_nm?: number;
    effective_max_edge_nm?: number;
    airspace_avoidance?: string;
    airspace_blocked_edges?: number;
    airspace_note?: string | null;
    topology_ms?: number;
    total_ms?: number;
  };
  aircraft_performance: AircraftPerformanceInfo;
  method_notes?: Record<string, string>;
  warnings?: string[];
  error?: string;
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

// ─── Gerçek Uçuş Doğrulama ──────────────────────────────────────────

export interface TrackEstimate {
  track_points: number;
  distance_nm: number;
  fuel_kg: number;
  time_min: number;
  co2_kg: number;
  avg_altitude_ft: number | null;
  landing_mass_kg: number;
  cost_index: number;
  source: string;
}

export interface ValidationComparison {
  fuel_saved_vs_actual_kg: number;
  fuel_saved_vs_actual_percent: number;
  time_saved_vs_actual_min: number;
  time_saved_vs_actual_percent: number;
  co2_saved_vs_actual_kg: number;
  distance_delta_vs_actual_nm: number;
  actual_vs_shortest_extra_nm: number;
  optimized_is_better: boolean;
}

export interface ValidationResult {
  available: boolean;
  reason?: string;
  method?: string;
  origin?: string;
  destination?: string;
  flight?: {
    icao24: string;
    callsign: string;
    departure: string | null;
    destination: string | null;
    aircraft_type: string;
    registration?: string | null;
    operator?: string | null;
    model?: string | null;
    track_points: number;
    first_seen_utc?: string | null;
    last_seen_utc?: string | null;
  };
  actual?: TrackEstimate;
  optimized?: {
    distance_nm: number;
    fuel_kg: number;
    time_min: number;
    co2_kg: number;
    cruise_altitude_ft: number;
  };
  standard?: {
    distance_nm: number;
    fuel_kg: number;
    time_min: number;
    co2_kg: number;
    cruise_altitude_ft: number;
  };
  comparison?: ValidationComparison;
  wind_info?: WindInfo;
  caveats?: string[];
  error?: string;
}

export async function validateRoute(request: {
  origin: string;
  destination: string;
  aircraft_type?: string;
  cost_index?: number;
  optimization_weights?: { fuel: number; time: number; co2: number };
  hours?: number;
}): Promise<ValidationResult> {
  return apiFetch<ValidationResult>("/api/validate", {
    method: "POST",
    body: JSON.stringify(request),
  });
}

// ─── Birikimli Tasarruf (sunucu) ────────────────────────────────────

export interface SavingsTotals {
  total_optimizations: number;
  total_fuel_kg: number;
  total_time_min: number;
  total_co2_kg: number;
  total_co2_ton: number;
  total_cost_usd: number;
  distinct_routes: number;
}

export interface SavingsStats {
  storage: string;
  totals: SavingsTotals;
  recent: Array<{
    created_at: string;
    origin: string;
    destination: string;
    aircraft_type: string;
    fuel_saved_kg: number;
    time_saved_min: number;
    co2_saved_kg: number;
    cost_saved_usd: number;
  }>;
  error?: string;
}

export async function getSavingsStats(limit: number = 12): Promise<SavingsStats> {
  return apiFetch<SavingsStats>(`/api/stats/savings?limit=${limit}`);
}

// ─── Yapay Zekâ (ML) Tahmin ─────────────────────────────────────────

export interface PredictRequest {
  distance_nm: number;
  wind_speed_kts: number;
  wind_direction: number;
  heading: number;
  altitude_ft?: number;
  cost_index?: number;
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
  /** Modelin fizik motorundan ne kadar saptığı (%) — surrogate model kalitesi */
  ai_vs_physics_error_percent: {
    fuel_kg: number;
    time_min: number;
    co2_kg: number;
  };
}

export async function mlPredict(
  request: PredictRequest
): Promise<PredictResult> {
  return apiFetch<PredictResult>("/api/predict", {
    method: "POST",
    body: JSON.stringify(request),
  });
}
