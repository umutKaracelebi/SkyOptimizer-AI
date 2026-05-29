import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import RotatingEarth from '@/components/ui/wireframe-dotted-globe';
import { DottedSurface } from '@/components/ui/dotted-surface';
import { Plane, Wind, Brain, Database, Leaf, Globe, BarChart3, Zap, Shield, ArrowDown, ChevronRight } from 'lucide-react';

/* DottedSurface Three.js bileşeni import edildi */

/* ── Sayı animasyonu (count-up) ─────────────────────────────────── */
function AnimatedCounter({ target, suffix = '', duration = 2000 }: { target: string; suffix?: string; duration?: number }) {
  const [display, setDisplay] = useState('0');
  const ref = useRef<HTMLDivElement>(null);
  const animated = useRef(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !animated.current) {
          animated.current = true;
          const numMatch = target.match(/[\d.]+/);
          if (!numMatch) { setDisplay(target); return; }
          const num = parseFloat(numMatch[0]);
          const prefix = target.slice(0, target.indexOf(numMatch[0]));
          const postfix = target.slice(target.indexOf(numMatch[0]) + numMatch[0].length);
          const isDecimal = numMatch[0].includes('.');
          const start = performance.now();

          const tick = (now: number) => {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3); // easeOutCubic
            const val = num * eased;
            setDisplay(prefix + (isDecimal ? val.toFixed(1) : Math.round(val).toString()) + postfix);
            if (progress < 1) requestAnimationFrame(tick);
            else setDisplay(target);
          };
          requestAnimationFrame(tick);
        }
      },
      { threshold: 0.3 }
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [target, duration]);

  return <div ref={ref}>{display}{suffix}</div>;
}

/* ── FadeInUp — scroll'da görünür olunca animasyon ──────────────── */
function FadeInUp({ children, delay = 0, className = '' }: { children: React.ReactNode; delay?: number; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => { if (entry.isIntersecting) setVisible(true); },
      { threshold: 0.15 }
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      style={{
        opacity: visible ? 1 : 0,
        transform: visible ? 'translateY(0)' : 'translateY(30px)',
        transition: `opacity 0.7s ease ${delay}s, transform 0.7s ease ${delay}s`,
      }}
    >
      {children}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════ */

export default function HeroGlobe() {
  const navigate = useNavigate();

  useEffect(() => {
    const style = document.createElement('style');
    style.textContent = `
      @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0.3; } }
      .blink-slow { animation: blink 3s ease-in-out infinite; }
      @keyframes scanline { 0% { transform: translateY(-100%); } 100% { transform: translateY(100vh); } }
      .scanline { animation: scanline 8s linear infinite; }
      @keyframes float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-10px); } }
      .float-anim { animation: float 3s ease-in-out infinite; }
      @keyframes glow-pulse { 0%, 100% { text-shadow: 0 0 8px rgba(0,212,255,0.3); } 50% { text-shadow: 0 0 20px rgba(0,212,255,0.6), 0 0 40px rgba(0,212,255,0.2); } }
      .glow-pulse { animation: glow-pulse 3s ease-in-out infinite; }
      @keyframes slide-in-right { 0% { transform: translateX(-20px); opacity: 0; } 100% { transform: translateX(0); opacity: 1; } }
      .slide-in { animation: slide-in-right 0.8s ease-out forwards; }
      @keyframes border-glow { 0%, 100% { border-color: rgba(0,212,255,0.1); } 50% { border-color: rgba(0,212,255,0.3); } }
      .border-glow { animation: border-glow 4s ease-in-out infinite; }
    `;
    document.head.appendChild(style);
    return () => { document.head.removeChild(style); };
  }, []);

  const pipeline = [
    { icon: <Globe size={20} />, step: '01', title: 'Havalimanı Seçimi', desc: 'Kalkış ve varış noktalarını 5.200+ havalimanı arasından belirleyin.' },
    { icon: <Wind size={20} />, step: '02', title: 'Rüzgâr Taraması', desc: 'Rota boyunca 7+ noktada gerçek zamanlı üst seviye rüzgâr verisi toplanır.' },
    { icon: <Zap size={20} />, step: '03', title: 'Graf Oluşturma', desc: 'Great-circle waypoint\'ler ve ±100 NM koridor havalimanlarıyla graf oluşturulur.' },
    { icon: <Brain size={20} />, step: '04', title: 'A* Optimizasyon', desc: 'Composite maliyet (yakıt + süre + CO₂) ile en verimli rota hesaplanır.' },
    { icon: <BarChart3 size={20} />, step: '05', title: 'AI Doğrulama', desc: 'Gradient Boosting modeli (178K parametre) fizik sonucunu doğrular.' },
    { icon: <Shield size={20} />, step: '06', title: 'Tasarruf Raporu', desc: 'Standart vs optimize karşılaştırma, yakıt/CO₂/maliyet tasarrufu raporlanır.' },
  ];

  return (
    <div className="relative bg-black text-white overflow-x-hidden">

      {/* ═══ BÖLÜM 1 — HERO ══════════════════════════════════════ */}
      <section className="relative min-h-screen overflow-hidden">
        {/* DottedSurface — alt katman, yerçekimi çukuru dünyanın altında (biraz daha arkaya çekildi) */}
        <DottedSurface className="z-[1] opacity-80" gravityX={0.5} gravityY={0.46} />

        {/* Siyah maske — noktaları dünya arkasında gizle (boyutu 52vmin yapılarak saydamlık giderildi) */}
        <div className="absolute inset-0 w-full h-full z-[2] flex items-center justify-center pointer-events-none">
          <div className="rounded-full bg-black filter blur-md" style={{ width: '52vmin', height: '52vmin', marginTop: '-3.5vh' }} />
        </div>

        {/* Dönen Dünya — üst katman (büyütüldü ve arkadaki çukura hizalandı) */}
        <div className="absolute inset-0 w-full h-full z-[3] flex items-center justify-center pointer-events-none">
          <div className="relative opacity-60 md:opacity-80" style={{ width: '65vmin', height: '65vmin', marginTop: '-3.5vh' }}>
            <RotatingEarth width={1100} height={1100} className="w-full h-full" />
          </div>
        </div>

        {/* Scanline */}
        <div className="absolute inset-0 pointer-events-none z-[5]">
          <div className="scanline w-full h-px bg-gradient-to-r from-transparent via-cyan-500/20 to-transparent" />
        </div>

        {/* Header */}
        <div className="absolute top-0 left-0 right-0 z-20 border-b border-cyan-500/20 bg-black/20 backdrop-blur-sm">
          <div className="container mx-auto px-4 lg:px-8 py-3 lg:py-4 flex items-center justify-between">
            <div className="flex items-center gap-2 lg:gap-4">
              <div className="font-mono text-cyan-400 text-lg lg:text-2xl font-bold tracking-widest">
                SKYOPTIMIZER<span className="text-cyan-600 text-xs lg:text-sm ml-1 font-normal">AI</span>
              </div>
              <div className="h-3 lg:h-4 w-px bg-cyan-500/40"></div>
              <span className="text-cyan-500/60 text-[8px] lg:text-[10px] font-mono">v0.1.0</span>
            </div>
            <div className="hidden lg:flex items-center gap-3 text-[10px] font-mono text-cyan-500/60">
              <span className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-green-500 rounded-full blink-slow"></span>
                SİSTEM AKTİF
              </span>
              <div className="w-1 h-1 bg-cyan-500/40 rounded-full"></div>
              <span>GLOBAL HAVA SAHASI</span>
            </div>
          </div>
        </div>

        {/* Köşe çerçeveleri */}
        <div className="absolute top-0 left-0 w-8 h-8 lg:w-12 lg:h-12 border-t-2 border-l-2 border-cyan-500/30 z-20"></div>
        <div className="absolute top-0 right-0 w-8 h-8 lg:w-12 lg:h-12 border-t-2 border-r-2 border-cyan-500/30 z-20"></div>
        <div className="absolute bottom-0 left-0 w-8 h-8 lg:w-12 lg:h-12 border-b-2 border-l-2 border-cyan-500/30 z-20"></div>
        <div className="absolute bottom-0 right-0 w-8 h-8 lg:w-12 lg:h-12 border-b-2 border-r-2 border-cyan-500/30 z-20"></div>

        {/* Hero İçerik */}
        <div className="relative z-10 flex min-h-screen items-center pt-16 lg:pt-0">
          <div className="container mx-auto px-6 lg:px-16 lg:ml-[8%]">
            <div className="max-w-xl relative">
              <div className="flex items-center gap-2 mb-3 opacity-60 slide-in" style={{ animationDelay: '0.2s' }}>
                <div className="w-8 h-px bg-cyan-500"></div>
                <span className="text-cyan-500 text-[10px] font-mono tracking-wider">✈ İnoTürk</span>
                <div className="flex-1 h-px bg-cyan-500/50"></div>
              </div>

              <div className="relative slide-in" style={{ animationDelay: '0.4s' }}>
                <div className="hidden lg:block absolute -left-3 top-0 bottom-0 w-1 dither-pattern opacity-30"></div>
                <h1 className="text-3xl lg:text-6xl font-bold text-white mb-3 lg:mb-4 font-mono tracking-wider" style={{ lineHeight: '1.35' }}>
                  UÇUŞ
                  <span className="block text-cyan-400 mt-1 lg:mt-2 glow-pulse">OPTİMİZASYONU</span>
                </h1>
              </div>

              {/* Dekoratif nokta deseni */}
              <div className="flex gap-1 mb-3 opacity-30">
                {Array.from({ length: 40 }).map((_, i) => (
                  <div key={i} className="w-0.5 h-0.5 bg-cyan-400 rounded-full" style={{ animationDelay: `${i * 0.02}s` }}></div>
                ))}
              </div>

              <div className="slide-in" style={{ animationDelay: '0.6s' }}>
                <p className="text-sm lg:text-lg text-gray-300 mb-6 lg:mb-8 leading-relaxed font-mono opacity-80 max-w-md">
                  Yapay zekâ ile gerçek zamanlı hava durumu ve trafik verilerini analiz ederek{' '}
                  <span className="text-cyan-400">optimum uçuş rotaları</span> hesaplayan akıllı sistem.
                </p>
              </div>

              <div className="grid grid-cols-3 gap-3 mb-6 lg:mb-8 slide-in" style={{ animationDelay: '0.8s' }}>
                <div className="glass-card rounded-lg p-2 lg:p-3 text-center border-glow hover:scale-105 transition-transform">
                  <div className="text-cyan-400 text-lg lg:text-2xl font-bold font-mono">%3-8</div>
                  <div className="text-gray-500 text-[9px] lg:text-[10px] font-mono">YAKIT TASARRUFU</div>
                </div>
                <div className="glass-card rounded-lg p-2 lg:p-3 text-center border-glow hover:scale-105 transition-transform" style={{ animationDelay: '1s' }}>
                  <div className="text-cyan-400 text-lg lg:text-2xl font-bold font-mono">↓$</div>
                  <div className="text-gray-500 text-[9px] lg:text-[10px] font-mono">MALİYET DÜŞÜRME</div>
                </div>
                <div className="glass-card rounded-lg p-2 lg:p-3 text-center border-glow hover:scale-105 transition-transform" style={{ animationDelay: '2s' }}>
                  <div className="text-cyan-400 text-lg lg:text-2xl font-bold font-mono">↓CO₂</div>
                  <div className="text-gray-500 text-[9px] lg:text-[10px] font-mono">EMİSYON AZALTMA</div>
                </div>
              </div>

              <div className="flex flex-col sm:flex-row gap-3 lg:gap-4 slide-in" style={{ animationDelay: '1s' }}>
                <button
                  onClick={() => navigate('/optimizer')}
                  className="relative px-6 lg:px-8 py-2.5 lg:py-3 bg-cyan-500/10 text-cyan-400 font-mono text-xs lg:text-sm border border-cyan-500/50 hover:bg-cyan-500/20 hover:border-cyan-400 hover:shadow-[0_0_20px_rgba(0,212,255,0.2)] transition-all duration-300 group glow-primary"
                >
                  <span className="absolute -top-1 -left-1 w-2 h-2 border-t border-l border-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity"></span>
                  <span className="absolute -bottom-1 -right-1 w-2 h-2 border-b border-r border-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity"></span>
                  ✈ ROTANI OPTİMİZE ET
                </button>
                <button
                  onClick={() => navigate('/about')}
                  className="relative px-6 lg:px-8 py-2.5 lg:py-3 bg-transparent border border-white/20 text-white/80 font-mono text-xs lg:text-sm hover:border-white/40 hover:text-white transition-all duration-300 group"
                >
                  DAHA FAZLA BİLGİ
                  <ChevronRight size={12} className="inline ml-1 group-hover:translate-x-1 transition-transform" />
                </button>
              </div>

              <div className="flex items-center gap-2 mt-6 lg:mt-8 opacity-30">
                <span className="text-cyan-500 text-[9px] font-mono">◈</span>
                <div className="flex-1 h-px bg-cyan-500/30"></div>
                <span className="text-cyan-500 text-[9px] font-mono">ADS-B • METAR • GFS • A* • ML</span>
              </div>
            </div>
          </div>
        </div>

        {/* Scroll İndikatörü */}
        <div className="absolute bottom-12 left-1/2 -translate-x-1/2 z-20 flex flex-col items-center gap-1 opacity-40 float-anim">
          <span className="text-cyan-500 text-[8px] font-mono tracking-widest">KEŞFET</span>
          <ArrowDown size={14} className="text-cyan-500" />
        </div>
      </section>

      {/* ═══ BÖLÜM 2 — İSTATİSTİKLER ════════════════════════════ */}
      <section className="relative z-10 py-20 lg:py-28 border-t border-cyan-500/10">
        <div className="container mx-auto px-6 lg:px-16">
          <FadeInUp>
            <div className="flex items-center gap-3 mb-10">
              <div className="w-10 h-px bg-cyan-500"></div>
              <span className="text-cyan-500 text-[10px] font-mono tracking-widest">KÜRESEL HAVACILIK</span>
              <div className="flex-1 h-px bg-cyan-500/20"></div>
            </div>
          </FadeInUp>

          <FadeInUp delay={0.1}>
            <h2 className="text-2xl lg:text-4xl font-bold font-mono mb-4">
              Neden <span className="text-cyan-400 glow-text">Rota Optimizasyonu?</span>
            </h2>
            <p className="text-gray-400 text-sm lg:text-base font-mono max-w-2xl mb-12 leading-relaxed">
              Sivil havacılık her yıl 4.5 milyardan fazla yolcu taşır ve küresel karbon emisyonlarının
              %2.5'ini oluşturur. Mevcut sabit rota sistemleri, değişen rüzgâr koşullarına uyum
              sağlayamadığı için milyarlarca dolarlık yakıt israfına neden olur.
            </p>
          </FadeInUp>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 lg:gap-6">
            {[
              { value: '915M', label: 'Yıllık CO₂ Emisyonu', desc: 'Küresel havacılık sektörü' },
              { value: '$180B', label: 'Yıllık Yakıt Maliyeti', desc: 'Tüm havayolları toplam' },
              { value: '4.5B', label: 'Yolcu / Yıl', desc: 'Küresel hava trafiği' },
              { value: '%2-5', label: 'Tasarruf Potansiyeli', desc: 'Rüzgâr optimizasyonu ile' },
            ].map((s, i) => (
              <FadeInUp key={i} delay={0.15 * i}>
                <div className="glass-card rounded-xl p-5 lg:p-6 group hover:border-cyan-500/30 hover:shadow-[0_0_15px_rgba(0,212,255,0.05)] transition-all duration-500">
                  <div className="text-2xl lg:text-3xl font-bold text-cyan-400 font-mono mb-2 group-hover:scale-105 transition-transform">
                    <AnimatedCounter target={s.value} />
                  </div>
                  <div className="text-xs text-white font-medium font-mono mb-1">{s.label}</div>
                  <div className="text-[10px] text-gray-500">{s.desc}</div>
                </div>
              </FadeInUp>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ BÖLÜM 3 — PROBLEM & ÇÖZÜM ═════════════════════════ */}
      <section className="relative z-10 py-20 lg:py-28 border-t border-cyan-500/10">
        <div className="container mx-auto px-6 lg:px-16">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
            <FadeInUp delay={0}>
              <div className="glass-card rounded-xl p-6 lg:p-8 border-red-500/10 hover:border-red-500/20 transition-all duration-500 h-full">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-2 h-2 bg-red-500 rounded-full blink-slow"></div>
                  <h2 className="text-lg font-bold text-red-400 font-mono">⚠ PROBLEM</h2>
                </div>
                <p className="text-gray-400 text-sm leading-relaxed mb-5">
                  Günümüzde uçak rotaları büyük oranda statik kurallara ve sabit güzergâhlara
                  bağımlıdır. Rüzgâr avantajları anlık olarak rotaya yansıtılamamaktadır.
                </p>
                <ul className="text-xs text-gray-500 space-y-3">
                  <li className="flex items-start gap-2"><span className="text-red-400 mt-0.5">▸</span> Sabit ATS rotaları rüzgâr değişimlerine tepki veremez</li>
                  <li className="flex items-start gap-2"><span className="text-red-400 mt-0.5">▸</span> Jet stream kaymaları yılda milyonlarca ton ekstra yakıt</li>
                  <li className="flex items-start gap-2"><span className="text-red-400 mt-0.5">▸</span> Her %1 fazla yakıt ≈ 10M ton ekstra CO₂</li>
                </ul>
              </div>
            </FadeInUp>

            <FadeInUp delay={0.2}>
              <div className="glass-card rounded-xl p-6 lg:p-8 border-cyan-500/10 hover:border-cyan-500/20 transition-all duration-500 h-full">
                <div className="flex items-center gap-2 mb-4">
                  <div className="w-2 h-2 bg-cyan-400 rounded-full blink-slow"></div>
                  <h2 className="text-lg font-bold text-cyan-400 font-mono">✓ ÇÖZÜM</h2>
                </div>
                <p className="text-gray-400 text-sm leading-relaxed mb-5">
                  SkyOptimizer AI, segment bazlı rüzgâr analizi ile kuyruk rüzgârı
                  avantajı sağlayan koridorları seçer. Fizik + AI hibrit doğrulama.
                </p>
                <ul className="text-xs text-gray-500 space-y-3">
                  <li className="flex items-start gap-2"><span className="text-cyan-400 mt-0.5">▸</span> 7+ noktada segment bazlı rüzgâr analizi</li>
                  <li className="flex items-start gap-2"><span className="text-cyan-400 mt-0.5">▸</span> A* graf arama + composite maliyet fonksiyonu</li>
                  <li className="flex items-start gap-2"><span className="text-cyan-400 mt-0.5">▸</span> Ek donanım maliyeti olmadan uygulanabilir</li>
                </ul>
              </div>
            </FadeInUp>
          </div>
        </div>
      </section>

      {/* ═══ BÖLÜM 4 — NASIL ÇALIŞIR ═══════════════════════════ */}
      <section className="relative z-10 py-20 lg:py-28 border-t border-cyan-500/10">
        <div className="container mx-auto px-6 lg:px-16">
          <FadeInUp>
            <div className="flex items-center gap-3 mb-10">
              <div className="w-10 h-px bg-cyan-500"></div>
              <span className="text-cyan-500 text-[10px] font-mono tracking-widest">ÇALIŞMA PRENSİBİ</span>
              <div className="flex-1 h-px bg-cyan-500/20"></div>
            </div>
            <h2 className="text-2xl lg:text-4xl font-bold font-mono mb-12">
              Nasıl <span className="text-cyan-400 glow-text">Çalışır?</span>
            </h2>
          </FadeInUp>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {pipeline.map((p, i) => (
              <FadeInUp key={i} delay={0.1 * i}>
                <div className="glass-card rounded-xl p-5 lg:p-6 group hover:border-cyan-500/30 hover:shadow-[0_0_15px_rgba(0,212,255,0.05)] transition-all duration-500 relative overflow-hidden h-full">
                  <div className="absolute top-3 right-4 text-cyan-500/8 text-5xl font-bold font-mono select-none">{p.step}</div>
                  <div className="relative">
                    <div className="text-cyan-500 mb-3 group-hover:text-cyan-400 group-hover:scale-110 transition-all duration-300 inline-block">{p.icon}</div>
                    <h3 className="text-sm font-bold text-white font-mono mb-2">{p.title}</h3>
                    <p className="text-xs text-gray-500 leading-relaxed">{p.desc}</p>
                  </div>
                </div>
              </FadeInUp>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ BÖLÜM 5 — TEKNOLOJİLER ════════════════════════════ */}
      <section className="relative z-10 py-20 lg:py-28 border-t border-cyan-500/10">
        <div className="container mx-auto px-6 lg:px-16">
          <FadeInUp>
            <div className="flex items-center gap-3 mb-10">
              <div className="w-10 h-px bg-cyan-500"></div>
              <span className="text-cyan-500 text-[10px] font-mono tracking-widest">TEKNOLOJİ</span>
              <div className="flex-1 h-px bg-cyan-500/20"></div>
            </div>
            <h2 className="text-2xl lg:text-4xl font-bold font-mono mb-12">
              Teknoloji <span className="text-cyan-400 glow-text">Altyapısı</span>
            </h2>
          </FadeInUp>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            {[
              { icon: <Plane size={20} />, title: 'ADS-B Canlı Takip', desc: 'OpenSky Network üzerinden rota koridorundaki uçuşları gerçek zamanlı takip eder.' },
              { icon: <Wind size={20} />, title: 'Üst Seviye Rüzgâr', desc: 'FL300-FL390 seviyelerinde segment bazlı rüzgâr hızı ve yön analizi.' },
              { icon: <Brain size={20} />, title: 'ML Doğrulama', desc: 'Gradient Boosting (178K param) ile fizik tabanlı sonuçların AI doğrulaması.' },
              { icon: <Database size={20} />, title: 'OpenAP Fizik', desc: 'Gerçek uçak performans verileriyle yakıt tüketimi ve emisyon hesaplama.' },
              { icon: <Leaf size={20} />, title: 'Çevre Dostu', desc: 'Net Sıfır 2050 hedefine katkı sunan emisyon odaklı optimizasyon.' },
              { icon: <Globe size={20} />, title: 'Global Kapsam', desc: 'Tüm kıtalarda, antimeridian-aware çalışan global rota sistemi.' },
            ].map((f, i) => (
              <FadeInUp key={i} delay={0.1 * i}>
                <div className="glass-card rounded-xl p-5 group hover:border-cyan-500/30 hover:shadow-[0_0_15px_rgba(0,212,255,0.05)] transition-all duration-500 h-full">
                  <div className="text-cyan-500 mb-3 group-hover:text-cyan-400 group-hover:scale-110 transition-all duration-300 inline-block">{f.icon}</div>
                  <h3 className="text-sm font-bold text-white font-mono mb-2">{f.title}</h3>
                  <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
                </div>
              </FadeInUp>
            ))}
          </div>
        </div>
      </section>

      {/* ═══ BÖLÜM 6 — ÇEVRESEL ETKİ ══════════════════════════ */}
      <section className="relative z-10 py-20 lg:py-28 border-t border-emerald-500/10">
        <div className="container mx-auto px-6 lg:px-16">
          <FadeInUp>
            <div className="flex items-center gap-3 mb-10">
              <div className="w-10 h-px bg-emerald-500"></div>
              <span className="text-emerald-500 text-[10px] font-mono tracking-widest">SÜRDÜRÜLEBİLİRLİK</span>
              <div className="flex-1 h-px bg-emerald-500/20"></div>
            </div>
            <h2 className="text-2xl lg:text-4xl font-bold font-mono mb-12">
              Çevresel <span className="text-emerald-400">Etki</span>
            </h2>
          </FadeInUp>

          <FadeInUp delay={0.2}>
            <div className="glass-card rounded-xl p-6 lg:p-8 border-emerald-500/10 hover:border-emerald-500/20 transition-all duration-500">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
                <div>
                  <h3 className="text-base font-bold text-emerald-400 font-mono mb-4">🌍 Neden Önemli?</h3>
                  <p className="text-gray-400 text-sm leading-relaxed mb-4">
                    ICAO'nun CORSIA programı ve 2050 Net Sıfır hedefi kapsamında, her %1'lik
                    yakıt tasarrufu milyonlarca ton CO₂ azalması anlamına gelir.
                  </p>
                  <p className="text-gray-400 text-sm leading-relaxed">
                    Rüzgâr optimizasyonu, mevcut uçak filosuyla ve ek donanım maliyeti olmadan
                    uygulanabilecek en etkili emisyon azaltma yöntemlerinden biridir.
                  </p>
                </div>
                <div className="space-y-3">
                  {[
                    { val: '%2.5', lbl: 'Havacılığın küresel karbon ayak izi' },
                    { val: '3.16', lbl: 'kg CO₂ / 1 kg Jet-A1 yakıt oranı' },
                    { val: '2050', lbl: 'ICAO Net Sıfır Emisyon hedef yılı' },
                  ].map((item, i) => (
                    <div key={i} className="flex items-center gap-4 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10 hover:border-emerald-500/20 transition-colors">
                      <div className="text-emerald-400 text-xl lg:text-2xl font-bold font-mono min-w-[60px]">
                        <AnimatedCounter target={item.val} />
                      </div>
                      <div className="text-xs text-gray-400">{item.lbl}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* ═══ BÖLÜM 7 — PROJE + CTA ═════════════════════════════ */}
      <section className="relative z-10 py-20 lg:py-28 border-t border-cyan-500/10">
        <div className="container mx-auto px-6 lg:px-16">
          <FadeInUp>
            <div className="glass-card rounded-xl p-6 lg:p-8 max-w-2xl mx-auto mb-12">
              <h2 className="text-lg font-bold text-cyan-400 font-mono mb-4">📋 PROJE BİLGİSİ</h2>
              <div className="space-y-2 text-sm font-mono">
                {[
                  ['Takım', 'İnoTürk'],
                  ['Program', 'Deneyap Takımlaşma Projesi 2026'],
                  ['Kapsam', 'Global — 5.200+ Havalimanı'],
                  ['Veri', 'OpenSky, NOAA, OWM, OurAirports'],
                  ['Backend', 'Python FastAPI + NetworkX'],
                  ['Frontend', 'React + TypeScript + Leaflet'],
                  ['ML/AI', 'A* + Gradient Boosting (178K param)'],
                ].map(([k, v], i) => (
                  <div key={i} className={`flex justify-between text-gray-400 ${i < 6 ? 'border-b border-gray-800 pb-2' : ''}`}>
                    <span>{k}</span>
                    <span className={i === 0 ? 'text-cyan-400 font-bold' : 'text-white'}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </FadeInUp>

          <FadeInUp delay={0.2}>
            <div className="text-center">
              <button
                onClick={() => navigate('/optimizer')}
                className="relative px-10 py-4 bg-cyan-500/10 text-cyan-400 font-mono text-sm border border-cyan-500/50 hover:bg-cyan-500/20 hover:border-cyan-400 hover:shadow-[0_0_30px_rgba(0,212,255,0.15)] transition-all duration-500 group glow-primary"
              >
                <span className="absolute -top-1 -left-1 w-2 h-2 border-t border-l border-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity"></span>
                <span className="absolute -bottom-1 -right-1 w-2 h-2 border-b border-r border-cyan-400 opacity-0 group-hover:opacity-100 transition-opacity"></span>
                ✈ ŞİMDİ OPTİMİZE ET
              </button>
              <p className="text-gray-600 text-[10px] font-mono mt-4">Geliştiren: İnoTürk — Deneyap Takımlaşma Projesi 2026</p>
            </div>
          </FadeInUp>
        </div>
      </section>

      {/* Footer */}
      <footer className="relative z-10 border-t border-cyan-500/20 bg-black/80 backdrop-blur-sm">
        <div className="container mx-auto px-4 lg:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3 lg:gap-6 text-[8px] lg:text-[9px] font-mono text-cyan-500/50">
            <span className="flex items-center gap-1">
              <span className="w-1 h-1 bg-green-500 rounded-full"></span>
              AKTİF
            </span>
            <span>OPENSKY • NOAA • OWM</span>
          </div>
          <div className="text-[8px] lg:text-[9px] font-mono text-cyan-500/50">
            İnoTürk — DENEYAP 2026
          </div>
        </div>
      </footer>
    </div>
  );
}
