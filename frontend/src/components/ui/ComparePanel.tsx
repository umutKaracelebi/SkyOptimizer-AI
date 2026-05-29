import { useEffect, useState } from 'react';
import { Brain, Zap, Fuel, Clock, Leaf, ArrowRight, Loader2 } from 'lucide-react';
import { mlPredict } from '../../services/api';
import type { PredictResult } from '../../services/api';

// ─── Types ──────────────────────────────────────────────────────────

interface ComparePanelProps {
  /** Optimize sonucu varsa, mesafe ve rüzgar bilgisi */
  routeData: {
    distance_nm: number;
    wind_speed_kts: number;
    wind_direction: number;
    heading: number;
    altitude_ft?: number;
  } | null;
}

// ─── Helpers ────────────────────────────────────────────────────────

function pctDiff(ai: number, physics: number): string {
  if (physics === 0) return '0';
  const diff = ((ai - physics) / physics) * 100;
  return diff.toFixed(1);
}

function DiffBadge({ ai, physics }: { ai: number; physics: number }) {
  const diff = parseFloat(pctDiff(ai, physics));
  if (Math.abs(diff) < 0.5) {
    return <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-gray-500/20 text-gray-400">≈ eşit</span>;
  }
  const isLess = diff < 0;
  return (
    <span className={`text-[9px] px-1.5 py-0.5 rounded-full ${
      isLess ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
    }`}>
      {isLess ? '▼' : '▲'} %{Math.abs(diff).toFixed(1)}
    </span>
  );
}

// ─── Component ──────────────────────────────────────────────────────

export default function ComparePanel({ routeData }: ComparePanelProps) {
  const [result, setResult] = useState<PredictResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!routeData) { setResult(null); return; }

    let cancelled = false;
    setLoading(true);
    setError('');

    mlPredict({
      distance_nm: routeData.distance_nm,
      wind_speed_kts: routeData.wind_speed_kts,
      wind_direction: routeData.wind_direction,
      heading: routeData.heading,
      altitude_ft: routeData.altitude_ft || 35000,
    })
      .then(data => { if (!cancelled) setResult(data); })
      .catch(e => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [routeData]);

  if (!routeData) return null;

  if (loading) {
    return (
      <div className="glass-card rounded-xl p-4">
        <h2 className="text-xs font-bold text-cyan-400 mb-3 flex items-center gap-2">
          <Brain size={14} /> AI vs FİZİK KARŞILAŞTIRMA
        </h2>
        <div className="flex items-center justify-center py-4 text-gray-500 text-xs gap-2">
          <Loader2 size={14} className="animate-spin" /> Tahmin hesaplanıyor...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="glass-card rounded-xl p-4">
        <h2 className="text-xs font-bold text-cyan-400 mb-3 flex items-center gap-2">
          <Brain size={14} /> AI vs FİZİK KARŞILAŞTIRMA
        </h2>
        <p className="text-red-400/70 text-[10px]">Backend'e bağlanılamadı</p>
      </div>
    );
  }

  if (!result) return null;

  const ai = result.ai_prediction;
  const phys = result.physics_prediction;

  const rows = [
    { icon: <Fuel size={12} />, label: 'Yakıt', unit: 'kg', aiVal: ai?.fuel_kg, physVal: phys.fuel_kg },
    { icon: <Clock size={12} />, label: 'Süre', unit: 'dk', aiVal: ai?.time_min, physVal: phys.time_min },
    { icon: <Leaf size={12} />, label: 'CO₂', unit: 'kg', aiVal: ai?.co2_kg, physVal: phys.co2_kg },
  ];

  return (
    <div className="glass-card rounded-xl p-4">
      <h2 className="text-xs font-bold text-cyan-400 mb-3 flex items-center gap-2">
        <Brain size={14} /> AI vs FİZİK KARŞILAŞTIRMA
      </h2>

      {/* Model durumu badge */}
      <div className="mb-3">
        {result.model_available ? (
          <span className="inline-flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
            <Brain size={10} /> AI Model Aktif
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
            <Zap size={10} /> Fizik Modeli (AI eğitilmedi)
          </span>
        )}
      </div>

      {/* Karşılaştırma tablosu */}
      <div className="space-y-2">
        {/* Başlık satırı */}
        <div className="grid grid-cols-3 gap-1 text-[9px] text-gray-500 uppercase tracking-wider px-1">
          <span></span>
          <span className="text-center">🤖 AI</span>
          <span className="text-center">⚡ Fizik</span>
        </div>

        {rows.map(row => (
          <div key={row.label} className="grid grid-cols-3 gap-1 items-center">
            {/* Label */}
            <div className="flex items-center gap-1.5 text-gray-400 text-[10px]">
              {row.icon} {row.label}
            </div>

            {/* AI değeri */}
            <div className="text-center">
              {ai ? (
                <span className="text-cyan-400 text-xs font-bold tabular-nums">
                  {row.aiVal?.toFixed(1)}
                  <span className="text-[8px] text-gray-500 ml-0.5">{row.unit}</span>
                </span>
              ) : (
                <span className="text-gray-600 text-[10px]">—</span>
              )}
            </div>

            {/* Fizik değeri */}
            <div className="text-center">
              <span className="text-amber-400 text-xs font-bold tabular-nums">
                {row.physVal.toFixed(1)}
                <span className="text-[8px] text-gray-500 ml-0.5">{row.unit}</span>
              </span>
            </div>
          </div>
        ))}

        {/* Fark satırı */}
        {ai && (
          <div className="pt-2 mt-1 border-t border-gray-800">
            <div className="flex items-center justify-between text-[10px]">
              <span className="text-gray-500 flex items-center gap-1">
                <ArrowRight size={10} /> Fark
              </span>
              <div className="flex gap-2">
                <DiffBadge ai={ai.fuel_kg} physics={phys.fuel_kg} />
                <DiffBadge ai={ai.time_min} physics={phys.time_min} />
                <DiffBadge ai={ai.co2_kg} physics={phys.co2_kg} />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
