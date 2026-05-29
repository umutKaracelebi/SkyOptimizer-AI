import { useEffect, useState, useRef } from 'react';
import { TrendingUp, Fuel, Clock, Leaf, DollarSign, BarChart3 } from 'lucide-react';

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
}

const STORAGE_KEY = 'skyoptimizer_stats';

function loadStats(): CumulativeStats {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch { /* ignore */ }
  return { total_optimizations: 0, total_fuel_kg: 0, total_time_min: 0, total_co2_kg: 0, total_cost_usd: 0 };
}

function saveStats(stats: CumulativeStats) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(stats));
}

// ─── Animated Counter ───────────────────────────────────────────────

function AnimatedCounter({ value, decimals = 0, duration = 1200 }: { value: number; decimals?: number; duration?: number }) {
  const [display, setDisplay] = useState(0);
  const prevRef = useRef(0);

  useEffect(() => {
    const start = prevRef.current;
    const diff = value - start;
    if (Math.abs(diff) < 0.01) { setDisplay(value); return; }

    const startTime = performance.now();
    let raf: number;

    const tick = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = start + diff * eased;
      setDisplay(current);
      if (progress < 1) { raf = requestAnimationFrame(tick); }
      else { prevRef.current = value; }
    };

    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, duration]);

  return <>{display.toFixed(decimals)}</>;
}

// ─── StatsPanel Component ───────────────────────────────────────────

interface StatsPanelProps {
  latestSavings: SavingsData | null;
}

export default function StatsPanel({ latestSavings }: StatsPanelProps) {
  const [stats, setStats] = useState<CumulativeStats>(loadStats);
  const lastSavingsRef = useRef<SavingsData | null>(null);

  // Yeni tasarruf geldiğinde birikime ekle
  useEffect(() => {
    if (!latestSavings) return;
    // Aynı savings'i tekrar eklememek için referans kontrolü
    if (lastSavingsRef.current === latestSavings) return;
    lastSavingsRef.current = latestSavings;

    setStats(prev => {
      const updated: CumulativeStats = {
        total_optimizations: prev.total_optimizations + 1,
        total_fuel_kg: prev.total_fuel_kg + (latestSavings.fuel_saved_kg || 0),
        total_time_min: prev.total_time_min + (latestSavings.time_saved_min || 0),
        total_co2_kg: prev.total_co2_kg + (latestSavings.co2_saved_kg || 0),
        total_cost_usd: prev.total_cost_usd + (latestSavings.cost_saved_usd || 0),
      };
      saveStats(updated);
      return updated;
    });
  }, [latestSavings]);

  const statItems = [
    {
      icon: <Fuel size={14} />,
      label: 'TOPLAM YAKIT',
      value: stats.total_fuel_kg,
      unit: 'kg',
      color: 'emerald',
      decimals: 1,
    },
    {
      icon: <Clock size={14} />,
      label: 'TOPLAM SÜRE',
      value: stats.total_time_min,
      unit: 'dk',
      color: 'blue',
      decimals: 1,
    },
    {
      icon: <Leaf size={14} />,
      label: 'TOPLAM CO₂',
      value: stats.total_co2_kg,
      unit: 'kg',
      color: 'amber',
      decimals: 1,
    },
    {
      icon: <DollarSign size={14} />,
      label: 'TOPLAM MALİYET',
      value: stats.total_cost_usd,
      unit: '$',
      color: 'purple',
      decimals: 0,
    },
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
    </div>
  );
}
