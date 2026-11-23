import { CheckCircle2, AlertTriangle, Loader2, Radar, Plane } from 'lucide-react';
import type { ValidationResult } from '../../services/api';

/**
 * Gerçek uçuş doğrulama kartı.
 *
 * Son 12 saatte aynı rotayı uçmuş bir ADS-B uçuşunun izi, aynı fizik
 * motoruyla değerlendirilir ve optimizasyonla karşılaştırılır. Amaç
 * "model kendi içinde tutarlı" iddiasını "gerçek uçuşla karşılaştırıldı"
 * seviyesine taşımak.
 */
export default function ValidationCard({
  result,
  loading,
  error,
  onRun,
}: {
  result: ValidationResult | null;
  loading: boolean;
  error: string;
  onRun: () => void;
}) {
  return (
    <div className="glass-card rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-xs font-bold text-cyan-400 flex items-center gap-2">
          <Radar size={14} /> GERÇEK UÇUŞLA DOĞRULAMA
        </h2>
        <button
          onClick={onRun}
          disabled={loading}
          className="text-[9px] px-2 py-1 rounded-md bg-cyan-500/10 border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/20 transition-colors disabled:opacity-50 flex items-center gap-1"
        >
          {loading ? <Loader2 size={10} className="animate-spin" /> : <Radar size={10} />}
          {loading ? 'ARANIYOR' : 'ÇALIŞTIR'}
        </button>
      </div>

      {!result && !loading && !error && (
        <p className="text-[9px] text-gray-500 leading-snug">
          Son 12 saatte aynı rotayı uçmuş gerçek bir uçuşun ADS-B iziyle
          modeli karşılaştırır. OpenSky anonim erişimi 12 saatle sınırlıdır.
        </p>
      )}

      {loading && (
        <p className="text-[9px] text-amber-400/80 leading-snug">
          OpenSky'de uçuş aranıyor, iz ve uçak tipi çekiliyor. Bu işlem
          birkaç saniye sürebilir.
        </p>
      )}

      {error && (
        <p className="text-[9px] text-red-400/80 leading-snug">
          <AlertTriangle size={9} className="inline mr-1" />
          {error}
        </p>
      )}

      {result && !result.available && (
        <p className="text-[9px] text-amber-400/80 leading-snug">
          <AlertTriangle size={9} className="inline mr-1" />
          {result.reason}
        </p>
      )}

      {result?.available && result.flight && result.actual && (
        <div className="space-y-2">
          <div className="bg-black/40 border border-cyan-500/20 rounded-lg p-2 space-y-0.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold text-white">
                {result.flight.callsign || result.flight.icao24}
              </span>
              <span className="text-[9px] text-cyan-400">
                {result.flight.aircraft_type}
                {result.flight.performance_proxy && result.flight.performance_type
                  ? ` → ${result.flight.performance_type} vekil`
                  : ''}
              </span>
            </div>
            <div className="text-[9px] text-gray-500">
              {result.flight.operator || '—'}
              {result.flight.registration ? ` · ${result.flight.registration}` : ''}
            </div>
            <div className="text-[9px] text-gray-400 flex items-center gap-1">
              <Plane size={9} />
              {result.flight.departure} → {result.flight.destination}
              <span className="text-gray-600 ml-auto">
                {result.actual.track_points} iz noktası
              </span>
            </div>
          </div>

          {result.reliable === false ? (
            <div className="flex items-start gap-1.5 text-[9px] leading-snug bg-amber-500/5 border border-amber-500/30 rounded-lg p-2">
              <AlertTriangle size={11} className="text-amber-400 shrink-0 mt-0.5" />
              <span className="text-amber-300/90">
                {result.reliability_note ||
                  'İz verisi eksik; yakıt karşılaştırması güvenilir değil.'}
              </span>
            </div>
          ) : result.comparison ? (
            <>
              <div className="grid grid-cols-3 gap-1.5 text-center">
                <MiniStat label="GERÇEK" value={result.actual.fuel_kg} unit="kg" color="text-amber-400" />
                <MiniStat label="OPTİMİZE" value={result.optimized?.fuel_kg ?? 0} unit="kg" color="text-emerald-400" />
                <MiniStat
                  label={result.comparison.fuel_saved_vs_actual_kg >= 0 ? 'FARK' : 'FARK (AŞIM)'}
                  value={Math.abs(result.comparison.fuel_saved_vs_actual_kg)}
                  unit="kg"
                  color={result.comparison.fuel_saved_vs_actual_kg >= 0 ? 'text-cyan-400' : 'text-red-400'}
                />
              </div>

              <div className="flex items-start gap-1.5 text-[9px] leading-snug">
                {Math.abs(result.comparison.fuel_saved_vs_actual_percent) < 1.5 ? (
                  <>
                    <AlertTriangle size={11} className="text-gray-400 shrink-0 mt-0.5" />
                    <span className="text-gray-400">
                      Fark (%{Math.abs(result.comparison.fuel_saved_vs_actual_percent).toFixed(1)})
                      modelin ±%5 belirsizliği içinde; bu uçuş için pratikte eşdeğer.
                      Yine de gerçek iz, modelin aynı fizikle değerlendirildiğini gösterir.
                    </span>
                  </>
                ) : result.comparison.optimized_is_better ? (
                  <>
                    <CheckCircle2 size={11} className="text-emerald-400 shrink-0 mt-0.5" />
                    <span className="text-emerald-300/90">
                      Gerçek uçuşa göre %{Math.abs(result.comparison.fuel_saved_vs_actual_percent).toFixed(1)} yakıt,
                      %{Math.abs(result.comparison.time_saved_vs_actual_percent).toFixed(1)} süre tasarrufu
                      ({Math.abs(result.comparison.distance_delta_vs_actual_nm).toFixed(0)} NM daha kısa).
                    </span>
                  </>
                ) : (
                  <>
                    <AlertTriangle size={11} className="text-amber-400 shrink-0 mt-0.5" />
                    <span className="text-amber-300/90">
                      Gerçek uçuş bu modelde daha verimli çıktı. Nedeni ATC
                      yönlendirmesi, farklı cruise seviyesi veya model
                      varsayımları olabilir — sonuç dürüstçe gösterilir.
                    </span>
                  </>
                )}
              </div>
            </>
          ) : null}

          {result.caveats && result.caveats.length > 0 && (
            <details>
              <summary className="text-[8px] text-gray-500 cursor-pointer hover:text-cyan-400 list-none">
                Varsayımlar ▾
              </summary>
              <ul className="mt-1 space-y-0.5 text-[8px] text-gray-500 leading-snug list-disc pl-3">
                {result.caveats.map((caveat, i) => (
                  <li key={i}>{caveat}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

function MiniStat({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: number;
  unit: string;
  color: string;
}) {
  return (
    <div className="bg-black/40 border border-gray-800 rounded-lg p-1.5">
      <div className={`text-[11px] font-bold tabular-nums ${color}`}>
        {Math.round(value).toLocaleString('tr-TR')}
        <span className="text-[8px] font-normal ml-0.5 opacity-70">{unit}</span>
      </div>
      <div className="text-[7px] text-gray-500">{label}</div>
    </div>
  );
}
