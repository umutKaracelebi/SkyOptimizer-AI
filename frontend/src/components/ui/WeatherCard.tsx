import { CloudSun, Wind, Thermometer, Eye, Gauge } from 'lucide-react';
import type { WeatherCard as WeatherCardData } from '../../services/api';

/**
 * METAR/TAF kartı — kalkış ve varış hava durumu.
 *
 * Veri zaten `/api/optimize` yanıtında geliyor; önceden hiç
 * gösterilmiyordu. Uçuş kategorisi renk kodludur (VFR yeşil → LIFR mor).
 */

const CATEGORY_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  VFR:  { bg: 'bg-emerald-500/15 border-emerald-500/40', text: 'text-emerald-400', label: 'VFR' },
  MVFR: { bg: 'bg-blue-500/15 border-blue-500/40',       text: 'text-blue-400',    label: 'MVFR' },
  IFR:  { bg: 'bg-red-500/15 border-red-500/40',         text: 'text-red-400',     label: 'IFR' },
  LIFR: { bg: 'bg-purple-500/15 border-purple-500/40',   text: 'text-purple-400',  label: 'LIFR' },
};

function fmt(value: number | null | undefined, unit: string, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value.toFixed(digits)} ${unit}`;
}

export default function WeatherCard({
  data,
  role,
}: {
  data: WeatherCardData | null;
  role: 'KALKIŞ' | 'VARIŞ';
}) {
  if (!data) return null;

  const metar = data.metar;
  const taf = data.taf;
  const category = (metar.flight_category || '').toUpperCase();
  const style = CATEGORY_STYLE[category] ?? {
    bg: 'bg-gray-500/10 border-gray-600/40',
    text: 'text-gray-400',
    label: category || 'BİLİNMİYOR',
  };

  const hasMetar = !!(metar.raw || metar.temperature_c !== undefined);
  const hasTaf = !!taf?.raw;

  return (
    <div className="glass-card rounded-xl p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5 text-[10px] text-cyan-400 font-bold">
          <CloudSun size={12} />
          {role} · {data.icao}
        </div>
        <span className={`px-1.5 py-0.5 rounded border text-[9px] font-bold ${style.bg} ${style.text}`}>
          {style.label}
        </span>
      </div>

      {!hasMetar ? (
        <p className="text-[9px] text-gray-500">
          {metar.error || 'METAR verisi yok'}
        </p>
      ) : (
        <div className="grid grid-cols-2 gap-1.5 text-[10px]">
          <div className="flex items-center gap-1 text-gray-400">
            <Wind size={10} className="text-cyan-500/70" />
            <span className="tabular-nums">
              {metar.wind_direction ?? '—'}° / {fmt(metar.wind_speed_kts, 'kt')}
              {metar.wind_gust_kts ? ` G${metar.wind_gust_kts}` : ''}
            </span>
          </div>
          <div className="flex items-center gap-1 text-gray-400">
            <Thermometer size={10} className="text-amber-500/70" />
            <span className="tabular-nums">{fmt(metar.temperature_c, '°C')}</span>
          </div>
          <div className="flex items-center gap-1 text-gray-400">
            <Eye size={10} className="text-blue-500/70" />
            <span className="tabular-nums">
              {metar.visibility_sm != null
                ? `${metar.visibility_raw || metar.visibility_sm} SM`
                : metar.visibility_m != null
                  ? `${(metar.visibility_m / 1000).toFixed(1)} km`
                  : '—'}
            </span>
          </div>
          <div className="flex items-center gap-1 text-gray-400">
            <Gauge size={10} className="text-emerald-500/70" />
            <span className="tabular-nums">{fmt(metar.altimeter_hpa, 'hPa')}</span>
          </div>
        </div>
      )}

      {hasMetar && metar.raw && (
        <details className="mt-2 group">
          <summary className="text-[9px] text-gray-500 cursor-pointer hover:text-cyan-400 list-none">
            METAR ▾
          </summary>
          <p className="mt-1 text-[9px] font-mono text-cyan-300/80 break-all leading-snug bg-black/40 rounded p-1.5">
            {metar.raw}
          </p>
        </details>
      )}
      {hasTaf && (
        <details className="mt-1">
          <summary className="text-[9px] text-gray-500 cursor-pointer hover:text-cyan-400 list-none">
            TAF ▾
          </summary>
          <p className="mt-1 text-[9px] font-mono text-cyan-300/80 break-all leading-snug bg-black/40 rounded p-1.5">
            {taf.raw}
          </p>
        </details>
      )}
    </div>
  );
}
