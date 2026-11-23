import { useEffect, useState } from 'react';
import {
  X, Plane, Navigation, ArrowUp, ArrowDown, Minus, Radio, Building2,
  Route as RouteIcon, Loader2, Tag,
} from 'lucide-react';
import { getAircraft } from '../../services/api';
import type { AircraftMetadata, Flight } from '../../services/api';
import { AIRCRAFT_CLASS_COLORS, AIRCRAFT_CLASS_LABELS } from '../../lib/aircraftIcons';

/**
 * Canlı trafikte bir uçağa tıklanınca açılan kısa detay paneli.
 *
 * ADS-B'den gelen anlık değerler + hexdb.io'dan uçak kimliği (tip, kayıt,
 * operatör) ve çağrı işaretinden rota. Rota biliniyorsa tek tıkla o
 * rotayı optimize etmeye izin verir.
 */

function altFt(m: number | null | undefined): string {
  if (m == null) return '—';
  return `${Math.round(m * 3.28084).toLocaleString('tr-TR')} ft`;
}

function speedKts(ms: number | null | undefined): string {
  if (ms == null) return '—';
  return `${Math.round(ms * 1.943844)} kt`;
}

function verticalRate(fpm: number | null | undefined) {
  if (fpm == null || Math.abs(fpm) < 50) {
    return { icon: <Minus size={12} />, text: 'Düz uçuş', color: 'text-gray-400' };
  }
  if (fpm > 0) {
    return {
      icon: <ArrowUp size={12} />,
      text: `Tırmanıyor ${Math.round(fpm).toLocaleString('tr-TR')} ft/dk`,
      color: 'text-emerald-400',
    };
  }
  return {
    icon: <ArrowDown size={12} />,
    text: `Alçalıyor ${Math.round(Math.abs(fpm)).toLocaleString('tr-TR')} ft/dk`,
    color: 'text-amber-400',
  };
}

export default function AircraftDetailPanel({
  flight,
  onClose,
  onOptimizeRoute,
}: {
  flight: Flight;
  onClose: () => void;
  onOptimizeRoute: (origin: string, destination: string) => void;
}) {
  const [meta, setMeta] = useState<AircraftMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setMeta(null);

    getAircraft(flight.icao24, flight.callsign || undefined)
      .then(data => {
        if (!cancelled) setMeta(data);
      })
      .catch(err => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [flight.icao24, flight.callsign]);

  const cls = meta?.category || flight.aircraft_class || 'unknown';
  const color = AIRCRAFT_CLASS_COLORS[cls] ?? '#eab308';
  const clsLabel = AIRCRAFT_CLASS_LABELS[cls] ?? cls;
  const vr = verticalRate(flight.vertical_rate);
  const route = meta?.route;
  const canOptimize = !!(route?.origin && route?.destination);

  return (
    <div className="absolute top-0 right-0 h-full w-full sm:w-[320px] z-[1001] bg-[hsl(224,71%,5%)]/95 backdrop-blur-md border-l border-amber-500/30 shadow-2xl flex flex-col animate-in">
      {/* Başlık */}
      <div className="p-3 border-b border-cyan-500/15 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Radio size={12} className="text-amber-400 animate-pulse shrink-0" />
            <span className="text-sm font-bold text-white truncate">
              {flight.callsign || flight.icao24.toUpperCase()}
            </span>
          </div>
          <div className="text-[9px] text-gray-500 mt-0.5">
            {flight.icao24.toUpperCase()} · {flight.origin_country}
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-white transition-colors shrink-0"
          aria-label="Detayı kapat"
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-3 custom-scrollbar">
        {/* Sınıf rozeti */}
        <div className="flex items-center gap-2">
          <span
            className="px-2 py-0.5 rounded-full border text-[9px] font-bold"
            style={{ color, borderColor: `${color}66`, backgroundColor: `${color}18` }}
          >
            {clsLabel}
          </span>
          {flight.type_code && (
            <span className="px-2 py-0.5 rounded-full bg-cyan-500/10 border border-cyan-500/30 text-cyan-300 text-[9px] font-bold">
              {flight.type_code}
            </span>
          )}
        </div>

        {/* Anlık değerler */}
        <div className="grid grid-cols-2 gap-1.5">
          {[
            { label: 'İRTİFA', value: altFt(flight.altitude_m) },
            { label: 'YER HIZI', value: speedKts(flight.velocity_ms) },
            { label: 'YÖN', value: flight.true_track != null ? `${Math.round(flight.true_track)}°` : '—' },
            { label: 'SQUAWK', value: flight.squawk || '—' },
          ].map(item => (
            <div key={item.label} className="bg-black/40 border border-gray-800 rounded-lg p-2">
              <div className="text-[8px] text-gray-500">{item.label}</div>
              <div className="text-[11px] text-cyan-300 font-bold tabular-nums">{item.value}</div>
            </div>
          ))}
        </div>

        <div className={`flex items-center gap-1.5 text-[10px] ${vr.color}`}>
          {vr.icon}
          {vr.text}
        </div>

        {/* Uçak kimliği */}
        <div className="glass-card rounded-lg p-2.5 space-y-1.5">
          <div className="flex items-center gap-1.5 text-[9px] text-cyan-400 font-bold">
            <Plane size={11} /> UÇAK KİMLİĞİ
          </div>
          {loading && (
            <div className="flex items-center gap-2 text-[10px] text-gray-500">
              <Loader2 size={11} className="animate-spin" /> hexdb.io sorgulanıyor...
            </div>
          )}
          {!loading && meta?.available && (
            <div className="space-y-1 text-[10px]">
              <Row label="Tip" value={meta.type_code || '—'} />
              <Row label="Model" value={meta.model || '—'} />
              <Row label="Kayıt" value={meta.registration || '—'} />
              <Row
                label="Operatör"
                value={meta.operator || '—'}
                icon={<Building2 size={9} className="text-gray-600" />}
              />
            </div>
          )}
          {!loading && !meta?.available && (
            <p className="text-[9px] text-gray-500 leading-snug">
              {meta?.reason || error || 'Uçak kaydı bulunamadı.'} Gösterilen
              sınıf ADS-B hız/irtifasından tahmin edilmiştir.
            </p>
          )}
        </div>

        {/* Rota */}
        <div className="glass-card rounded-lg p-2.5 space-y-2">
          <div className="flex items-center gap-1.5 text-[9px] text-cyan-400 font-bold">
            <RouteIcon size={11} /> ROTA
          </div>
          {loading ? (
            <div className="text-[10px] text-gray-500">—</div>
          ) : route ? (
            <>
              <div className="flex items-center gap-2 text-xs font-bold">
                <span className="text-cyan-300">{route.origin}</span>
                <Navigation size={10} className="text-gray-500" />
                <span className="text-amber-300">{route.destination}</span>
              </div>
              <div className="text-[9px] text-gray-500">
                Kaynak: {route.source}
                {route.updated_at ? ' · kayıt eski olabilir' : ''}
              </div>
              <button
                onClick={() => onOptimizeRoute(route.origin, route.destination)}
                disabled={!canOptimize}
                className="w-full mt-1 px-3 py-1.5 rounded-md text-[10px] font-bold bg-cyan-500/10 text-cyan-300 border border-cyan-500/40 hover:bg-cyan-500/20 transition-colors flex items-center justify-center gap-1.5"
              >
                <Plane size={11} /> BU ROTAYI OPTİMİZE ET
              </button>
            </>
          ) : (
            <p className="text-[9px] text-gray-500 leading-snug">
              Bu çağrı işareti için kayıtlı rota yok. Rota yalnızca hexdb.io
              veritabanında varsa gösterilir.
            </p>
          )}
        </div>

        <div className="flex items-center gap-1 text-[8px] text-gray-600">
          <Tag size={9} />
          Konum: {flight.latitude.toFixed(3)}, {flight.longitude.toFixed(3)}
        </div>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-2">
      <span className="text-gray-500 flex items-center gap-1 shrink-0">
        {icon}{label}
      </span>
      <span className="text-gray-300 text-right truncate">{value}</span>
    </div>
  );
}
