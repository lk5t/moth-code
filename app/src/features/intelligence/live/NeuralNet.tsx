/**
 * 0.10.0: MOTH's network, drawn live. One column per layer (from the real architecture, capped so it fits),
 * signals flow through it as fast as tokens are being trained, and the connections brighten as the loss
 * falls. Reduced-motion users and hidden tabs get a still picture.
 */
import { useEffect, useRef } from "react";

const reduced = () => typeof window !== "undefined" && !!window.matchMedia
  && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type Props = { layers: number; width: number; active: boolean; speed: number | null; learned: number; className?: string };

export function NeuralNet({ layers, width, active, speed, learned, className }: Props) {
  const ref = useRef<HTMLCanvasElement>(null);
  const state = useRef({ active, speed, learned });
  state.current = { active, speed, learned };
  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext?.("2d");
    if (!canvas || !ctx) return;
    const cols = Math.max(3, Math.min(10, layers + 2));          // input, layers…, output
    const rows = Math.max(4, Math.min(9, Math.round(Math.log2(Math.max(16, width)) + 1)));
    let w = 0, h = 0, raf = 0, last = performance.now();
    const nodes: { x: number; y: number; glow: number }[][] = [];
    const sparks: { c: number; a: number; b: number; t: number; v: number }[] = [];
    const layout = () => {
      const r = canvas.getBoundingClientRect();
      const dpr = Math.min(2, window.devicePixelRatio || 1);
      w = Math.max(200, r.width); h = Math.max(120, r.height);
      canvas.width = w * dpr; canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      nodes.length = 0;
      for (let c = 0; c < cols; c++) {
        const n = c === 0 || c === cols - 1 ? Math.max(3, rows - 2) : rows;
        nodes.push(Array.from({ length: n }, (_, i) => ({
          x: 18 + (c / (cols - 1)) * (w - 36), y: h / 2 + (i - (n - 1) / 2) * Math.min(22, (h - 24) / n), glow: 0 })));
      }
    };
    const draw = (dt: number) => {
      const { active: on, speed: sp, learned: lr } = state.current;
      ctx.clearRect(0, 0, w, h);
      const base = 0.05 + 0.25 * Math.max(0, Math.min(1, lr));
      for (let c = 0; c < cols - 1; c++) for (const a of nodes[c]) for (const b of nodes[c + 1]) {
        ctx.strokeStyle = `rgba(193,18,31,${base})`;
        ctx.lineWidth = 0.6;
        ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      }
      if (on) {  // new signals, as many as the measured training speed suggests
        const rate = Math.min(18, 1.5 + Math.log10(Math.max(10, sp ?? 100)) * 3);
        if (Math.random() < rate * dt) {
          sparks.push({ c: 0, a: Math.floor(Math.random() * nodes[0].length), b: Math.floor(Math.random() * nodes[1].length), t: 0,
            v: 1.6 + Math.random() * 1.4 });
        }
      }
      for (let i = sparks.length - 1; i >= 0; i--) {
        const s = sparks[i];
        s.t += dt * s.v;
        const A = nodes[s.c][s.a], B = nodes[s.c + 1][s.b];
        if (s.t >= 1) {
          B.glow = 1;
          if (s.c + 2 < cols) { s.c += 1; s.a = s.b; s.b = Math.floor(Math.random() * nodes[s.c + 1].length); s.t = 0; }
          else { sparks.splice(i, 1); continue; }
        }
        const x = A.x + (B.x - A.x) * s.t, y = A.y + (B.y - A.y) * s.t;
        const g = ctx.createRadialGradient(x, y, 0, x, y, 5);
        g.addColorStop(0, "rgba(255,120,120,0.95)"); g.addColorStop(1, "rgba(193,18,31,0)");
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
      }
      for (const col of nodes) for (const n of col) {
        n.glow = Math.max(0, n.glow - dt * 2.4);
        ctx.fillStyle = `rgba(${Math.round(60 + 195 * n.glow)},${Math.round(30 + 60 * n.glow)},${Math.round(34 + 60 * n.glow)},1)`;
        ctx.beginPath(); ctx.arc(n.x, n.y, 2.6 + n.glow * 1.6, 0, Math.PI * 2); ctx.fill();
        if (n.glow > 0.05) {
          ctx.strokeStyle = `rgba(255,90,90,${n.glow * 0.6})`;
          ctx.beginPath(); ctx.arc(n.x, n.y, 4 + n.glow * 4, 0, Math.PI * 2); ctx.stroke();
        }
      }
    };
    layout();
    const still = reduced();
    const loop = (t: number) => {
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      if (!document.hidden) draw(dt);
      raf = requestAnimationFrame(loop);
    };
    if (still) draw(0); else raf = requestAnimationFrame(loop);
    const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(() => { layout(); if (still) draw(0); }) : null;
    ro?.observe(canvas);
    return () => { cancelAnimationFrame(raf); ro?.disconnect(); };
  }, [layers, width]);
  return <canvas ref={ref} className={className} role="img"
    aria-label={`MOTH's network: ${layers} layers, ${width} wide${active ? ", training now" : ""}`} />;
}
