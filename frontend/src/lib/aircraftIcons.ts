/**
 * Uçak tipi ikonları — Leaflet divIcon üreteci.
 *
 * ADS-B `aircraft_class` alanına göre farklı silüetler çizilir ve uçağın
 * gerçek yönüne (`true_track`) göre döndürülür. İkonlar 10°'lik yön
 * kovalarına ve sınıfa göre cache'lenir; her trafik yenilemesinde yüzlerce
 * yeni DOM/SVG nesnesi üretilmez.
 */

import L from 'leaflet';
import type { AircraftClass } from '../services/api';

const NOSE_UP_VIEWBOX = '0 0 24 24';

/* ── Silüetler (burun yukarı) ───────────────────────────────────── */

const JET_BODY =
  'M12 1.6 L13.1 7.2 L13.7 11.6 L22.8 16.1 L22.8 17.9 L13.5 15.4 ' +
  'L13.3 19.6 L16.1 21.6 L16.1 23 L12 21.7 L7.9 23 L7.9 21.6 ' +
  'L10.7 19.6 L10.5 15.4 L1.2 17.9 L1.2 16.1 L10.3 11.6 L10.9 7.2 Z';

const SILHOUETTES: Record<string, string> = {
  // Gövde + 2 motor (dar gövde)
  narrow:
    `<path d="${JET_BODY}"/>` +
    '<rect x="9.1" y="12.6" width="1.6" height="4.2" rx=".7"/>' +
    '<rect x="13.3" y="12.6" width="1.6" height="4.2" rx=".7"/>',

  // Daha geniş kanat + 4 motor (geniş gövde)
  heavy:
    '<path d="M12 1.4 L13.4 7 L14 12 L23.4 16.9 L23.4 18.8 L13.8 16.1 ' +
    'L13.6 20 L16.6 22 L16.6 23.4 L12 22 L7.4 23.4 L7.4 22 L10.4 20 ' +
    'L10.2 16.1 L.6 18.8 L.6 16.9 L10 12 L10.6 7 Z"/>' +
    '<rect x="7.5" y="13.2" width="2" height="3" rx=".8"/>' +
    '<rect x="14.5" y="13.2" width="2" height="3" rx=".8"/>' +
    '<rect x="4.6" y="14.3" width="1.8" height="2.8" rx=".8"/>' +
    '<rect x="17.6" y="14.3" width="1.8" height="2.8" rx=".8"/>',

  // Bölgesel jet: düz kanat + T kuyruk
  regional:
    '<path d="M12 2.2 L12.9 8 L13.4 12.4 L21.6 16.4 L21.6 17.9 L13.2 15.8 ' +
    'L13.1 19 L15.6 20.8 L15.6 22 L12 21.1 L8.4 22 L8.4 20.8 L10.9 19 ' +
    'L10.8 15.8 L2.4 17.9 L2.4 16.4 L10.6 12.4 L11.1 8 Z"/>' +
    '<rect x="9.6" y="12.9" width="1.5" height="3.1" rx=".7"/>' +
    '<rect x="12.9" y="12.9" width="1.5" height="3.1" rx=".7"/>' +
    '<rect x="8.9" y="2.6" width="6.2" height=".9" rx=".4"/>',

  // Turboprop: düz kanat + pervane diskleri
  turboprop:
    '<path d="M12 2.6 L12.8 8.4 L13.1 12.6 L22.2 14.2 L22.2 15.8 L13 15.3 ' +
    'L12.9 19 L15.2 20.6 L15.2 21.8 L12 20.9 L8.8 21.8 L8.8 20.6 L11.1 19 ' +
    'L11 15.3 L1.8 15.8 L1.8 14.2 L10.9 12.6 L11.2 8.4 Z"/>' +
    '<circle cx="4.5" cy="15" r="1.8"/><circle cx="19.5" cy="15" r="1.8"/>' +
    '<rect x="11.7" y="1.4" width=".6" height="3.4" rx=".3"/>',

  // Hafif uçak: küçük gövde, düz kanat, burun pervanesi
  light:
    '<path d="M12 3.2 L12.7 9 L13 13.4 L21 14.6 L21 16 L13 15.5 ' +
    'L12.9 19 L14.9 20.4 L14.9 21.5 L12 20.8 L9.1 21.5 L9.1 20.4 ' +
    'L11.1 19 L11 15.5 L3 16 L3 14.6 L10.9 13.4 L11.2 9 Z"/>' +
    '<circle cx="12" cy="2.6" r="1.2"/>',

  // Helikopter: gövde + rotor + kuyruk
  rotor:
    '<ellipse cx="11" cy="13" rx="3.2" ry="4.6"/>' +
    '<rect x="10.4" y="3.4" width="1.2" height="18.2" rx=".5" opacity=".55"/>' +
    '<rect x="2.6" y="12.4" width="18.8" height="1.2" rx=".5" opacity=".55"/>' +
    '<path d="M12.4 15.4 L18.4 19.4 L18.9 20.6 L12.6 17.4 Z"/>' +
    '<circle cx="12" cy="13" r="1.35"/>',

  // Avcı uçağı: delta kanat
  fighter:
    '<path d="M12 1.8 L13 10 L21.8 17.6 L21.8 19 L13.2 16 L13 19.4 ' +
    'L15.2 21.2 L15.2 22.4 L12 21.4 L8.8 22.4 L8.8 21.2 L11 19.4 ' +
    'L10.8 16 L2.2 19 L2.2 17.6 L11 10 Z"/>' +
    '<circle cx="12" cy="8" r=".8"/>',

  // Askeri nakliye: yüksek kanat + 4 motor
  military:
    '<path d="M12 2.4 L13.6 8 L14 12.2 L23.2 14 L23.2 15.6 L14 15 ' +
    'L14 19 L17 21 L17 22.2 L12 21.4 L7 22.2 L7 21 L10 19 L10 15 ' +
    'L.8 15.6 L.8 14 L10 12.2 L10.4 8 Z"/>' +
    '<rect x="5.4" y="13.1" width="2.6" height="2" rx=".8"/>' +
    '<rect x="16" y="13.1" width="2.6" height="2" rx=".8"/>' +
    '<rect x="3.4" y="12.5" width="1.8" height="1.8" rx=".7"/>' +
    '<rect x="18.8" y="12.5" width="1.8" height="1.8" rx=".7"/>',

  // Bilinmeyen: basit ok
  unknown:
    '<path d="M12 2.4 L14 20.2 L12 18.6 L10 20.2 Z"/>',
};

export const AIRCRAFT_CLASS_COLORS: Record<string, string> = {
  heavy: '#f97316',
  narrow: '#fbbf24',
  regional: '#38bdf8',
  turboprop: '#a78bfa',
  light: '#34d399',
  rotor: '#22d3ee',
  fighter: '#f43f5e',
  military: '#94a3b8',
  unknown: '#eab308',
};

export const AIRCRAFT_CLASS_LABELS: Record<string, string> = {
  heavy: 'Geniş gövde',
  narrow: 'Dar gövde',
  regional: 'Bölgesel jet',
  turboprop: 'Turboprop',
  light: 'Hafif uçak',
  rotor: 'Helikopter',
  fighter: 'Avcı',
  military: 'Askeri',
  unknown: 'Bilinmeyen',
};

const iconCache = new Map<string, L.DivIcon>();

export function aircraftIcon(
  aircraftClass: AircraftClass | string | undefined,
  heading: number | null | undefined,
  options: { selected?: boolean; size?: number } = {}
): L.DivIcon {
  const cls = (aircraftClass && SILHOUETTES[aircraftClass]) ? aircraftClass : 'unknown';
  const track = Number.isFinite(heading as number) ? Number(heading) : 0;
  const bucket = Math.round(((track % 360) + 360) % 360 / 10) * 10 % 360;
  const size = options.size ?? 22;
  const color = options.selected ? '#00d4ff' : (AIRCRAFT_CLASS_COLORS[cls] ?? '#eab308');
  const key = `${cls}:${bucket}:${options.selected ? 1 : 0}:${size}`;

  const cached = iconCache.get(key);
  if (cached) return cached;

  const shadow = options.selected
    ? 'filter:drop-shadow(0 0 5px #00d4ff);'
    : 'filter:drop-shadow(0 0 2px rgba(0,0,0,.9));';

  const html = `
    <div class="aircraft-marker-inner" style="width:${size}px;height:${size}px;transform:rotate(${bucket}deg);${shadow}">
      <svg viewBox="${NOSE_UP_VIEWBOX}" width="${size}" height="${size}"
           fill="${color}" stroke="rgba(0,0,0,.55)" stroke-width=".55"
           aria-hidden="true" focusable="false">
        ${SILHOUETTES[cls]}
      </svg>
    </div>`;

  const icon = L.divIcon({
    className: 'aircraft-marker',
    html,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
  });
  iconCache.set(key, icon);
  return icon;
}

/** Legend için küçük SVG (HTML string). */
export function aircraftLegendSvg(aircraftClass: string, size = 16): string {
  const cls = SILHOUETTES[aircraftClass] ? aircraftClass : 'unknown';
  const color = AIRCRAFT_CLASS_COLORS[cls] ?? '#eab308';
  return `<svg viewBox="${NOSE_UP_VIEWBOX}" width="${size}" height="${size}" fill="${color}"
    stroke="rgba(0,0,0,.5)" stroke-width=".6" aria-hidden="true">${SILHOUETTES[cls]}</svg>`;
}

export const iconCacheSize = () => iconCache.size;
