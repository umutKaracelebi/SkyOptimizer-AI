import { useEffect, useState, useRef } from 'react';
import { TrendingUp, Fuel, Clock, Leaf, DollarSign, BarChart3, Server, HardDrive } from 'lucide-react';
import { getSavingsStats } from '../../services/api';

// ─── Types ──────────────────────────────────────────────────────────

export interface SavingsData {
  fuel_saved_kg: number;
  time_saved_min: number;
  co2_saved_kg: number;
  cost_saved_usd: number;
}

interface CumulativeStats {
  total_optimizations: number;
  total_fuel_kg: number;
  total_time_min: number;
  total_co2_kg: number;
  total_cost_usd: number;
  distinct_routes: number;
}

const STORAGE_KEY = 'skyoptimizer_stats';
const EMPTY: CumulativeStats = {
  total_optimizations: 0, total_fuel_kg: 0, total_time_min: 0,
  total_co2_kg: 0, total_cost_usd: 0, distinct_routes: 0,
};

function loadLocalStats(): CumulativeStats {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        ...EMPTY,
        ...parsed,
        distinct_routes: parsed.distinct_routes ?? 0,
      };
    }
  } catch { /* ignore */ }
  return { ...EMPTY };
}

// ─── Animated Counter ───────────────────────────────────────────────

function AnimatedCounter({ value, decimals = 0, duration = 1200 }: { value: number; decimals?: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  const prevRef = useRef(0);

  useEffect(() => {
    const start = prevRef.current;
    // Hedefi hemen kaydet — animasyon yarıda kesilirse sayaç baştan başlamaz
    prevRef.current = value;
    const diff = value - start;
    if (Math.abs(diff) < 0.01) { setDisplay(value); return; }

    const startTime = performance.now();
    let raf: number;

    const tick = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(start + diff * eased);
      if (progress < 1) { raf = requestAnimationFrame(tick); }
    };

    raf = requestAnimationFrame(tick);
    const fallback = setTimeout(() => setDisplay(value), duration + 250);

    return () => {
      cancelAnimationFrame(raf);
      clearTimeout(fallback);
    };
  }, [value, duration]);

  return <>{display.toFixed(decimals)}</>;
}

// ─── StatsPanel Component ───────────────────────────────────────────

interface StatsPanelProps {
  latestSavings: SavingsData | null;
  /** Yeni bir optimizasyon tamamlandığında artırılır → sunucudan tazelenir */
  refreshKey?: number;
}

/**
 * Birikimli tasarruf paneli.
 *
 * Öncelik sunucudaki SQLite toplamlarıdır (ekip ortak istatistiği);
 * sunucuya erişilemezse tarayıcıdaki yerel toplam gösterilir.
 */
export default function StatsPanel({ latestSavings, refreshKey = 0 }: StatsPanelProps) {
  const [stats, setStats] = useState<CumulativeStats>(loadLocalStats);
  const [source, setSource] = useState<'server' | 'local'>('local');
  const [serverError, setServerError] = useState('');
  const lastSavingsRef = useRef<SavingsData | null>(null);

  // Sunucu toplamlarını tazele
  useEffect(() => {
    let cancelled = false;
    getSavingsStats()
      .then(data => {
        if (cancelled) return;
        setStats({
          total_optimizations: data.totals.total_optimizations,
          total_fuel_kg: data.totals.total_fuel_kg,
          total_time_min: data.totals.total_time_min,
          total_co2_kg: data.totals.total_co2_kg,
          total_cost_usd: data.totals.total_cost_usd,
          distinct_routes: data.totals.distinct_routes,
        });
        setSource('server');
        setServerError('');
      })
      .catch(err => {
        if (!cancelled) {
          setServerError(String(err));
          setSource('local');
        }
      });
    return () => { cancelled = true; };
  }, [refreshKey]);

  // Sunucu yoksa yeni tasarrufu yerel birikime ekle
  useEffect(() => {
    if (!latestSavings || source === 'server') return;
    if (lastSavingsRef.current === latestSavings) return;
    lastSavingsRef.current = latestSavings;

    setStats(prev => {
      const updated: CumulativeStats = {
        ...prev,
        total_optimizations: prev.total_optimizations + 1,
        total_fuel_kg: prev.total_fuel_kg + (latestSavings.fuel_saved_kg || 0),
        total_time_min: prev.total_time_min + (latestSavings.time_saved_min || 0),
        total_co2_kg: prev.total_co2_kg + (latestSavings.co2_saved_kg || 0),
        total_cost_usd: prev.total_cost_usd + (latestSavings.cost_saved_usd || 0),
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
      return updated;
    });
  }, [latestSavings, source]);

  const statItems = [
    { icon: <Fuel size={14} />, label: 'TOPLAM YAKIT', value: stats.total_fuel_kg, unit: 'kg', color: 'emerald', decimals: 0 },
    { icon: <Clock size={14} />, label: 'TOPLAM SÜRE', value: stats.total_time_min, unit: 'dk', color: 'blue', decimals: 0 },
    { icon: <Leaf size={14} />, label: 'TOPLAM CO₂', value: stats.total_co2_kg, unit: 'kg', color: 'amber', decimals: 0 },
    { icon: <DollarSign size={14} />, label: 'TOPLAM MALİYET', value: stats.total_cost_usd, unit: '$', color: 'purple', decimals: 0 },
  ];

  const colorMap: Record<string, { bg: string; border: string; text: string }> = {
    emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400' },
    blue:    { bg: 'bg-blue-500/10',    border: 'border-blue-500/30',    text: 'text-blue-400'    },
    amber:   { bg: 'bg-amber-500/10',   border: 'border-amber-500/30',   text: 'text-amber-400'   },
    purple:  { bg: 'bg-purple-500/10',  border: 'border-purple-500/30',  text: 'text-purple-400'  },
  };

  if (stats.total_optimizations === 0) return null;

  return (
    <div className="glass-card rounded-xl p-4">
      <h2 className="text-xs font-bold text-cyan-400 mb-3 flex items-center gap-2">
        <TrendingUp size={14} /> BİRİKİMLİ TASARRUF
        <span className="ml-auto text-[9px] text-gray-500 font-normal flex items-center gap-1">
          <BarChart3 size={10} />
          {stats.total_optimizations} optimizasyon
        </span>
      </h2>

      <div className="grid grid-cols-2 gap-2">
        {statItems.map(item => {
          const c = colorMap[item.color];
          return (
            <div key={item.label} className={`${c.bg} border ${c.border} rounded-lg p-2 text-center transition-all hover:scale-[1.02]`}>
              <div className={`${c.text} text-lg font-bold tabular-nums`}>
                {item.unit === '$' && '$'}
                <AnimatedCounter value={item.value} decimals={item.decimals} />
                {item.unit !== '$' && <span className="text-[10px] ml-0.5 font-normal opacity-70">{item.unit}</span>}
              </div>
              <div className="text-gray-500 text-[8px] flex items-center justify-center gap-1 mt-0.5">
                {item.icon} {item.label}
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-2 pt-2 border-t border-gray-800 flex items-center justify-between text-[8px] text-gray-500">
        <span className="flex items-center gap-1">
          {source === 'server'
            ? <><Server size={9} className="text-emerald-500/70" /> EKİP ORTAK (SQLite)</>
            : <><HardDrive size={9} className="text-amber-500/70" /> YEREL TARAYICI</>}
        </span>
        <span>
          {(stats.total_co2_kg / 1000).toFixed(2)} ton CO₂
          {stats.distinct_routes > 0 && ` · ${stats.distinct_routes} rota`}
        </span>
      </div>
      {serverError && source === 'local' && (
        <p className="mt-1 text-[8px] text-amber-500/60 leading-snug">
          Sunucu istatistiğine ulaşılamadı; yerel toplam gösteriliyor.
        </p>
      )}
    </div>
  );
}
