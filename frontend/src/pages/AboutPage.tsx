import { useEffect, useRef } from 'react';
import { ArrowLeft, Globe, Database, Cloud, Plane, Brain, Leaf, Wind, BarChart3, Zap, Target, Layers, ShieldCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

/* ── Parçacık arka plan efekti ──────────────────────────────────── */
function ParticleBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = document.documentElement.scrollHeight;
    };
    resize();
    window.addEventListener('resize', resize);

    const particles: { x: number; y: number; vx: number; vy: number; r: number; o: number }[] = [];
    for (let i = 0; i < 80; i++) {
      particles.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.3,
        vy: (Math.random() - 0.5) * 0.3,
        r: Math.random() * 1.5 + 0.5,
        o: Math.random() * 0.4 + 0.1,
      });
    }

    let animId: number;
    const draw = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const p of particles) {
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = canvas.width;
        if (p.x > canvas.width) p.x = 0;
        if (p.y < 0) p.y = canvas.height;
        if (p.y > canvas.height) p.y = 0;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0, 212, 255, ${p.o})`;
        ctx.fill();
      }
      // Bağlantı çizgileri
      for (let i = 0; i < particles.length; i++) {
        for (let j = i + 1; j < particles.length; j++) {
          const dx = particles[i].x - particles[j].x;
          const dy = particles[i].y - particles[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(particles[i].x, particles[i].y);
            ctx.lineTo(particles[j].x, particles[j].y);
            ctx.strokeStyle = `rgba(0, 212, 255, ${0.06 * (1 - dist / 120)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }
      animId = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', resize);
    };
  }, []);

  return <canvas ref={canvasRef} className="fixed inset-0 pointer-events-none z-0" />;
}

export default function AboutPage() {
  const navigate = useNavigate();

  const features = [
    { icon: <Plane size={22} />, title: 'ADS-B Canlı Takip', desc: 'OpenSky Network üzerinden gerçek zamanlı uçuş verilerini takip eder.' },
    { icon: <Cloud size={22} />, title: 'Meteoroloji Entegrasyonu', desc: 'METAR, TAF ve üst seviye rüzgâr verileriyle rota koşullarını analiz eder.' },
    { icon: <Brain size={22} />, title: 'Yapay Zekâ Optimizasyonu', desc: 'A* graf arama ve Gradient Boosting ile segment bazlı rüzgâr optimizasyonu.' },
    { icon: <Database size={22} />, title: 'OpenAP Performans Modeli', desc: 'Gerçek uçak performans verileriyle yakıt tüketimi ve CO₂ emisyonu hesaplar.' },
    { icon: <Leaf size={22} />, title: 'Sürdürülebilirlik', desc: 'Net Sıfır Emisyon hedeflerine katkı sunan çevreye duyarlı optimizasyon.' },
    { icon: <Globe size={22} />, title: 'Global Kapsam', desc: '5.200+ havalimanı, 7 uçak tipi, her kıtada çalışan global optimizasyon.' },
  ];

  const pipeline = [
    { icon: <Target size={20} />, step: '01', title: 'Rota Seçimi', desc: 'Kalkış ve varış havalimanlarını ICAO koduyla belirleyin.' },
    { icon: <Wind size={20} />, step: '02', title: 'Rüzgâr Analizi', desc: 'Rota boyunca 7+ noktada gerçek zamanlı üst seviye rüzgâr verisi alınır.' },
    { icon: <Layers size={20} />, step: '03', title: 'Graf Oluşturma', desc: 'Great-circle waypoint\'ler ve koridor havalimanlarıyla dinamik graf oluşturulur.' },
    { icon: <Zap size={20} />, step: '04', title: 'A* Optimizasyon', desc: 'Composite maliyet fonksiyonu (yakıt + süre + CO₂) ile en düşük maliyetli yol bulunur.' },
    { icon: <BarChart3 size={20} />, step: '05', title: 'AI Tahmin', desc: 'Gradient Boosting modeli fizik tabanlı sonucu doğrular ve karşılaştırır.' },
    { icon: <ShieldCheck size={20} />, step: '06', title: 'Tasarruf Raporu', desc: 'Standart vs optimize rota karşılaştırması, yakıt/CO₂/maliyet tasarrufu raporlanır.' },
  ];

  const stats = [
    { value: '915M', label: 'Ton CO₂/yıl', sub: 'Küresel havacılık emisyonu' },
    { value: '%2-5', label: 'Tasarruf Potansiyeli', sub: 'Rüzgâr optimizasyonu ile' },
    { value: '4.5B', label: 'Yolcu/yıl', sub: 'Küresel hava trafiği' },
    { value: '$180B', label: 'Yakıt Maliyeti/yıl', sub: 'Havayolu sektörü toplam' },
  ];

  return (
    <div className="dark min-h-screen bg-[hsl(224,71%,4%)] text-white relative">
      <ParticleBackground />

      {/* Header */}
      <header className="border-b border-cyan-500/20 bg-black/40 backdrop-blur-sm sticky top-0 z-50">
        <div className="container mx-auto px-4 lg:px-8 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <button onClick={() => navigate('/')} className="text-cyan-500/60 hover:text-cyan-400 transition-colors">
              <ArrowLeft size={18} />
            </button>
            <div className="font-mono text-cyan-400 text-lg font-bold tracking-widest">
              SKYOPTIMIZER
              <span className="text-cyan-600 text-xs ml-1 font-normal">AI</span>
            </div>
          </div>
        </div>
      </header>

      {/* İçerik */}
      <div className="relative z-10 container mx-auto px-4 lg:px-16 py-12 lg:py-20">

        {/* ── Hero Başlık ───────────────────────────────────── */}
        <div className="max-w-3xl mb-20">
          <div className="flex items-center gap-2 mb-4 opacity-60">
            <div className="w-8 h-px bg-cyan-500"></div>
            <span className="text-cyan-500 text-[10px] font-mono tracking-wider">HAKKINDA</span>
            <div className="flex-1 h-px bg-cyan-500/30"></div>
          </div>
          <h1 className="text-3xl lg:text-5xl font-bold font-mono mb-6">
            <span className="text-white">Uçuş Rotalarını </span>
            <span className="text-cyan-400 glow-text">Akıllıca</span>
            <span className="text-white"> Optimize Edin</span>
          </h1>
          <p className="text-gray-400 text-base lg:text-lg leading-relaxed font-mono">
            SkyOptimizer AI, sivil havacılıkta geleneksel ve sabit hava koridorlarının yarattığı
            zaman ve yakıt kayıplarını minimize etmek amacıyla geliştirilmiş, yapay zekâ destekli
            bir uçuş rota optimizasyon sistemidir.
          </p>
        </div>

        {/* ── Küresel Havacılık İstatistikleri ──────────────── */}
        <div className="mb-20">
          <h2 className="text-xl font-bold text-white font-mono mb-8 flex items-center gap-2">
            <div className="w-6 h-px bg-cyan-500"></div>
            KÜRESEL HAVACILIK VERİLERİ
          </h2>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {stats.map((s, i) => (
              <div key={i} className="glass-card rounded-xl p-5 text-center group hover:border-cyan-500/30 transition-all">
                <div className="text-2xl lg:text-3xl font-bold text-cyan-400 font-mono mb-1 group-hover:scale-110 transition-transform">{s.value}</div>
                <div className="text-xs text-white font-medium mb-1">{s.label}</div>
                <div className="text-[10px] text-gray-500">{s.sub}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Problem & Çözüm ──────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-20">
          <div className="glass-card rounded-xl p-6 lg:p-8">
            <h2 className="text-lg font-bold text-red-400 font-mono mb-4">⚠ PROBLEM</h2>
            <p className="text-gray-400 text-sm leading-relaxed mb-4">
              Günümüzde uçak rotaları büyük oranda statik kurallara ve sabit güzergâhlara
              bağımlıdır. Rüzgâr avantajları ve hava durumu değişiklikleri anlık olarak
              rotaya yansıtılamamakta, bu da gereksiz yakıt tüketimi ve atmosfere tonlarca
              ekstra CO₂ salınımına neden olmaktadır.
            </p>
            <ul className="text-xs text-gray-500 space-y-2">
              <li className="flex items-start gap-2"><span className="text-red-400 mt-0.5">•</span> Sabit ATS rotaları rüzgâr değişimlerine tepki veremez</li>
              <li className="flex items-start gap-2"><span className="text-red-400 mt-0.5">•</span> Jet stream kaymaları yılda milyonlarca ton ekstra yakıt yakar</li>
              <li className="flex items-start gap-2"><span className="text-red-400 mt-0.5">•</span> Havayolları yılda $180B+ yakıt harcaması yapar</li>
            </ul>
          </div>
          <div className="glass-card rounded-xl p-6 lg:p-8">
            <h2 className="text-lg font-bold text-cyan-400 font-mono mb-4">✓ ÇÖZÜM</h2>
            <p className="text-gray-400 text-sm leading-relaxed mb-4">
              SkyOptimizer AI, canlı meteoroloji verileri ve makine öğrenim algoritmaları ile
              gerçek zamanlı optimum uçuş rotaları hesaplar. Rota boyunca değişen rüzgâr
              koşullarını analiz ederek kuyruk rüzgârı avantajı sağlayan koridorları seçer.
            </p>
            <ul className="text-xs text-gray-500 space-y-2">
              <li className="flex items-start gap-2"><span className="text-cyan-400 mt-0.5">•</span> 7+ noktada segment bazlı rüzgâr analizi</li>
              <li className="flex items-start gap-2"><span className="text-cyan-400 mt-0.5">•</span> A* graf arama + composite maliyet fonksiyonu</li>
              <li className="flex items-start gap-2"><span className="text-cyan-400 mt-0.5">•</span> Yapay zekâ doğrulaması ile güvenilir sonuçlar</li>
            </ul>
          </div>
        </div>

        {/* ── Nasıl Çalışır Pipeline ───────────────────────── */}
        <div className="mb-20">
          <h2 className="text-xl font-bold text-white font-mono mb-8 flex items-center gap-2">
            <div className="w-6 h-px bg-cyan-500"></div>
            NASIL ÇALIŞIR?
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pipeline.map((p, i) => (
              <div key={i} className="glass-card rounded-xl p-5 group hover:border-cyan-500/30 transition-all relative overflow-hidden">
                <div className="absolute top-3 right-3 text-cyan-500/10 text-4xl font-bold font-mono">{p.step}</div>
                <div className="text-cyan-500 mb-3 group-hover:text-cyan-400 transition-colors">{p.icon}</div>
                <h3 className="text-sm font-bold text-white font-mono mb-2">{p.title}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">{p.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ── Teknolojiler ─────────────────────────────────── */}
        <div className="mb-20">
          <h2 className="text-xl font-bold text-white font-mono mb-8 flex items-center gap-2">
            <div className="w-6 h-px bg-cyan-500"></div>
            TEKNOLOJİLER
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {features.map((f, i) => (
              <div key={i} className="glass-card rounded-xl p-5 hover:border-cyan-500/30 transition-all group">
                <div className="text-cyan-500 mb-3 group-hover:text-cyan-400 transition-colors">{f.icon}</div>
                <h3 className="text-sm font-bold text-white font-mono mb-2">{f.title}</h3>
                <p className="text-xs text-gray-500 leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ── Çevresel Etki ────────────────────────────────── */}
        <div className="mb-20">
          <h2 className="text-xl font-bold text-white font-mono mb-8 flex items-center gap-2">
            <div className="w-6 h-px bg-emerald-500"></div>
            ÇEVRESEL ETKİ
          </h2>
          <div className="glass-card rounded-xl p-6 lg:p-8 border-emerald-500/20">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
              <div>
                <h3 className="text-lg font-bold text-emerald-400 font-mono mb-4">🌍 Neden Önemli?</h3>
                <p className="text-gray-400 text-sm leading-relaxed mb-4">
                  Sivil havacılık küresel CO₂ emisyonlarının yaklaşık %2.5'ini oluşturur. ICAO'nun
                  CORSIA programı ve 2050 Net Sıfır hedefi kapsamında, her %1'lik yakıt tasarrufu
                  milyonlarca ton CO₂ azalması anlamına gelir.
                </p>
                <p className="text-gray-400 text-sm leading-relaxed">
                  Rüzgâr optimizasyonu, mevcut uçak filosuyla ve ek donanım maliyeti olmadan
                  uygulanabilecek en etkili emisyon azaltma yöntemlerinden biridir. Her uçuş için
                  %1-5 arasında yakıt tasarrufu gerçekçi bir hedeftir.
                </p>
              </div>
              <div className="space-y-4">
                <div className="flex items-center gap-4 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10">
                  <div className="text-emerald-400 text-2xl font-bold font-mono min-w-[60px]">%2.5</div>
                  <div className="text-xs text-gray-400">Havacılığın küresel karbon ayak izi</div>
                </div>
                <div className="flex items-center gap-4 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10">
                  <div className="text-emerald-400 text-2xl font-bold font-mono min-w-[60px]">3.16</div>
                  <div className="text-xs text-gray-400">kg CO₂ / 1 kg Jet-A1 yakıt oranı</div>
                </div>
                <div className="flex items-center gap-4 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10">
                  <div className="text-emerald-400 text-2xl font-bold font-mono min-w-[60px]">2050</div>
                  <div className="text-xs text-gray-400">ICAO Net Sıfır Emisyon hedef yılı</div>
                </div>
                <div className="flex items-center gap-4 p-3 bg-emerald-500/5 rounded-lg border border-emerald-500/10">
                  <div className="text-emerald-400 text-2xl font-bold font-mono min-w-[60px]">7</div>
                  <div className="text-xs text-gray-400">Farklı uçak tipi desteği (B738, A320, B789...)</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── Proje Bilgisi ────────────────────────────────── */}
        <div className="glass-card rounded-xl p-6 lg:p-8 max-w-2xl mb-20">
          <h2 className="text-lg font-bold text-cyan-400 font-mono mb-4">📋 PROJE BİLGİSİ</h2>
          <div className="space-y-2 text-sm font-mono">
            <div className="flex justify-between text-gray-400 border-b border-gray-800 pb-2">
              <span>Program</span>
              <span className="text-white">Deneyap Takımlaşma Projesi 2026</span>
            </div>
            <div className="flex justify-between text-gray-400 border-b border-gray-800 pb-2">
              <span>Kapsam</span>
              <span className="text-white">Global — 5.200+ Havalimanı</span>
            </div>
            <div className="flex justify-between text-gray-400 border-b border-gray-800 pb-2">
              <span>Veri Kaynakları</span>
              <span className="text-white">OpenSky, NOAA, OWM, OurAirports</span>
            </div>
            <div className="flex justify-between text-gray-400 border-b border-gray-800 pb-2">
              <span>Backend</span>
              <span className="text-white">Python FastAPI + NetworkX</span>
            </div>
            <div className="flex justify-between text-gray-400 border-b border-gray-800 pb-2">
              <span>Frontend</span>
              <span className="text-white">React + TypeScript + Leaflet</span>
            </div>
            <div className="flex justify-between text-gray-400 border-b border-gray-800 pb-2">
              <span>ML/AI</span>
              <span className="text-white">A* + Gradient Boosting (178K param)</span>
            </div>
            <div className="flex justify-between text-gray-400">
              <span>Rüzgâr Motoru</span>
              <span className="text-white">Segment bazlı, 7+ nokta analiz</span>
            </div>
          </div>
        </div>

        {/* ── Teknik Detaylar ──────────────────────────────── */}
        <div className="mb-16">
          <h2 className="text-xl font-bold text-white font-mono mb-8 flex items-center gap-2">
            <div className="w-6 h-px bg-cyan-500"></div>
            TEKNİK DETAYLAR
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="glass-card rounded-xl p-5">
              <h3 className="text-sm font-bold text-cyan-400 font-mono mb-3">🧠 Yapay Zekâ Modeli</h3>
              <ul className="text-xs text-gray-500 space-y-2">
                <li>• Gradient Boosting Regressor — 178.000 parametre</li>
                <li>• Eğitim verisi: OpenAP fizik modeli simülasyonları</li>
                <li>• Özellikler: mesafe, rüzgâr hızı/yön, uçak tipi</li>
                <li>• Fizik modeli ile %0.1-0.7 sapma</li>
                <li>• 150+ NM mesafelerde yüksek doğruluk</li>
              </ul>
            </div>
            <div className="glass-card rounded-xl p-5">
              <h3 className="text-sm font-bold text-cyan-400 font-mono mb-3">🗺️ Graf Motoru</h3>
              <ul className="text-xs text-gray-500 space-y-2">
                <li>• Great-circle waypoint interpolasyonu</li>
                <li>• ±40-100 NM koridor kaymaları (rüzgâr avantajı)</li>
                <li>• Dinamik havalimanı entegrasyonu (koridor bazlı)</li>
                <li>• NetworkX DiGraph — kenar ağırlıklı A* arama</li>
                <li>• Composite cost: yakıt × α + süre × β + CO₂ × γ</li>
              </ul>
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
