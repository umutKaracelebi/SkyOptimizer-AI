'use client';
import { cn } from '@/lib/utils';
import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

type DottedSurfaceProps = Omit<React.ComponentProps<'div'>, 'ref'> & {
  /** Yerçekimi çukurunun ekran üzerindeki X pozisyonu (0-1, default 0.5 = merkez) */
  gravityX?: number;
  /** Yerçekimi çukurunun ekran üzerindeki Y pozisyonu (0-1, default 0.55 = biraz aşağı) */
  gravityY?: number;
};

export function DottedSurface({ className, gravityX = 0.5, gravityY = 0.55, ...props }: DottedSurfaceProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    animationId: number;
  } | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;

    const SEPARATION = 80;
    const AMOUNTX = 75;
    const AMOUNTY = 55;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / container.clientHeight,
      1,
      10000,
    );
    camera.position.set(0, 300, 2200);
    camera.lookAt(0, -100, 0);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(container.clientWidth, container.clientHeight);
    renderer.setClearColor(0x000000, 0);

    container.appendChild(renderer.domElement);

    // Grid merkezi
    const gridCenterX = 0;
    const gridCenterZ = 0;

    // Yerçekimi kuyusu — dünyanın olduğu yere denk gelen 3D koordinat
    // gravityX/Y ekran koordinatları → 3D grid koordinatlarına dönüştürülüyor
    const gravityWorldX = (gravityX - 0.5) * AMOUNTX * SEPARATION;
    const gravityWorldZ = (gravityY - 0.5) * AMOUNTY * SEPARATION * 0.6; // perspektif düzeltmesi

    const GRAVITY_RADIUS = 1600;   // etki alanı — daha geniş
    const GRAVITY_DEPTH = 1250;    // çukur derinliği — 950'den 1250'ye çıkarıldı (muazzam derin)
    const GRAVITY_SHARPNESS = 2.2; // çukurun keskinliği

    const positions: number[] = [];
    const colors: number[] = [];
    const sizes: number[] = [];
    const geometry = new THREE.BufferGeometry();

    for (let ix = 0; ix < AMOUNTX; ix++) {
      for (let iy = 0; iy < AMOUNTY; iy++) {
        const x = ix * SEPARATION - (AMOUNTX * SEPARATION) / 2;
        const z = iy * SEPARATION - (AMOUNTY * SEPARATION) / 2;
        positions.push(x, 0, z);

        // Merkeze yakın noktalar daha parlak + büyük
        const dist = Math.sqrt((x - gravityWorldX) ** 2 + (z - gravityWorldZ) ** 2);
        const closeness = Math.max(0, 1 - dist / (GRAVITY_RADIUS * 1.5));

        // Renk: dışta koyu cyan, merkeze yakın parlak beyaz-cyan
        const r = 0.0 + closeness * 0.6;
        const g = 0.65 + closeness * 0.35;
        const b = 0.85 + closeness * 0.15;
        colors.push(r, g, b);

        // Boyut: merkeze yakınsa çok daha belirgin
        sizes.push(20 + closeness * 20);
      }
    }

    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));

    // Custom shader — noktaların boyutunu vertex bazlı kontrol etmek için
    const shaderMaterial = new THREE.ShaderMaterial({
      uniforms: {
        uPixelRatio: { value: Math.min(window.devicePixelRatio, 2) },
      },
      vertexShader: `
        attribute float aSize;
        varying vec3 vColor;
        uniform float uPixelRatio;
        void main() {
          vColor = color;
          vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
          gl_PointSize = aSize * uPixelRatio * (450.0 / -mvPosition.z);
          gl_Position = projectionMatrix * mvPosition;
        }
      `,
      fragmentShader: `
        varying vec3 vColor;
        void main() {
          float d = length(gl_PointCoord - vec2(0.5));
          if (d > 0.5) discard;
          // Soft glow — kenarları fade
          float alpha = smoothstep(0.5, 0.1, d);
          gl_FragColor = vec4(vColor, alpha * 0.8);
        }
      `,
      transparent: true,
      vertexColors: true,
      depthWrite: false,
    });

    geometry.setAttribute('aSize', new THREE.Float32BufferAttribute(sizes, 1));

    const points = new THREE.Points(geometry, shaderMaterial);
    scene.add(points);

    let count = 0;
    let animationId: number;

    const animate = () => {
      animationId = requestAnimationFrame(animate);

      const posAttr = geometry.attributes.position;
      const pos = posAttr.array as Float32Array;

      let i = 0;
      for (let ix = 0; ix < AMOUNTX; ix++) {
        for (let iy = 0; iy < AMOUNTY; iy++) {
          const index = i * 3;
          // Orijinal (bükülmemiş) grid koordinatları
          const origX = ix * SEPARATION - (AMOUNTX * SEPARATION) / 2;
          const origZ = iy * SEPARATION - (AMOUNTY * SEPARATION) / 2;

          // Yerçekimi merkezine olan orijinal mesafe
          const dx = origX - gravityWorldX;
          // Perspektif düzeltmesi: Kamera yatay bakış açısına sahip olduğu için Z ekseni sıkışık görünür.
          // Z mesafesini 0.6 ile çarparak çukuru ön-arka doğrultusunda genişletiyoruz (enlemesine tam bir daire görünümü sağlar).
          const dz = (origZ - gravityWorldZ) * 0.6;
          const dist = Math.sqrt(dx * dx + dz * dz);
          const normalDist = Math.min(dist / GRAVITY_RADIUS, 1);
          
          // 1. Dikey Bükülme (Y Derinliği) - Merkezde maksimum çöküş
          const gravityFactor = Math.pow(1 - Math.pow(1 - normalDist, GRAVITY_SHARPNESS), 0.5);
          const gravityY = -GRAVITY_DEPTH * (1 - gravityFactor);

          // 2. Yatay Bükülme (X/Z İçe Çekilme - Einsteinian pinching)
          // Enlemesine (yatayda) bükülme etkisini en üst düzeye çıkarmak için güç 450'ye çıkarıldı
          const pinchStrength = 450; 
          const pinchFactor = Math.pow(1 - normalDist, 2.5); // Merkez yakınında çok daha güçlü
          const pull = pinchStrength * pinchFactor;

          const warpedX = dist > 0 ? origX - (dx / dist) * pull : origX;
          // Z bükülmesi için orijinal (sıkıştırılmamış) dz değerini kullanıyoruz
          const origDz = origZ - gravityWorldZ;
          const warpedZ = dist > 0 ? origZ - (origDz / (dist / 0.6)) * pull : origZ;

          // 3. Dalga Hareketi — yerçekimi kuyusuna yaklaştıkça dalga fazı bükülür (Gravitational Wave Lensing)
          // Düz gelen dalgalar dünyaya yaklaştıkça kütleçekim etkisiyle hızlanır ve dünyanın etrafında kıvrılır.
          const wavePhaseWarp = (1 - normalDist) * 4.5; // Dalga cephesinin dairesel bükülme şiddeti
          const waveStrength = 0.45 + 0.55 * normalDist; // Merkez yakınında dalgaların tamamen sönümlenmesini engelleyip bükülmeyi görünür kılıyoruz
          
          const wave = (
            Math.sin((ix + count) * 0.3 - wavePhaseWarp) * 35 +
            Math.sin((iy + count) * 0.5 - wavePhaseWarp) * 35
          ) * waveStrength;

          pos[index] = warpedX;
          pos[index + 1] = gravityY + wave;
          pos[index + 2] = warpedZ;
          i++;
        }
      }

      posAttr.needsUpdate = true;

      // Hafif kamera sallanması
      camera.position.x = Math.sin(count * 0.02) * 40;
      camera.lookAt(0, -100, 0);

      renderer.render(scene, camera);
      count += 0.06;
    };

    const handleResize = () => {
      camera.aspect = container.clientWidth / container.clientHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(container.clientWidth, container.clientHeight);
    };

    window.addEventListener('resize', handleResize);
    animate();

    sceneRef.current = { scene, camera, renderer, animationId };

    return () => {
      window.removeEventListener('resize', handleResize);
      if (sceneRef.current) {
        cancelAnimationFrame(sceneRef.current.animationId);
        sceneRef.current.scene.traverse((object) => {
          if (object instanceof THREE.Points) {
            object.geometry.dispose();
            if (Array.isArray(object.material)) {
              object.material.forEach((m) => m.dispose());
            } else {
              object.material.dispose();
            }
          }
        });
        sceneRef.current.renderer.dispose();
        if (container && sceneRef.current.renderer.domElement) {
          container.removeChild(sceneRef.current.renderer.domElement);
        }
      }
    };
  }, [gravityX, gravityY]);

  return (
    <div
      ref={containerRef}
      className={cn('pointer-events-none absolute inset-0', className)}
      {...props}
    />
  );
}
