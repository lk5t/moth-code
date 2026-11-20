/**
 * 0.10.0: the measured loss as a smooth, glowing curve: training (red, filled) and validation (white
 * dashed), a pulsing head at the newest point, the best value marked, and a readout on hover.
 */
import { useId, useMemo, useState } from "react";

type Point = { step: number; loss: number; split?: string };
const W = 600, H = 170, PAD = { l: 34, r: 12, t: 12, b: 22 };

function smooth(pts: [number, number][]): string {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {  // Catmull-Rom → cubic Bézier
    const p0 = pts[i - 1] ?? pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] ?? p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C${c1[0].toFixed(1)},${c1[1].toFixed(1)} ${c2[0].toFixed(1)},${c2[1].toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}

export function LossChart({ points, live }: { points: Point[]; live: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const uid = useId().replace(/:/g, "");
  const data = useMemo(() => points.filter((p) => Number.isFinite(p.step) && Number.isFinite(p.loss)), [points]);
  if (data.length < 2) return <div className="grid h-40 place-items-center rounded-lg border border-dashed border-border text-[0.6875rem] text-faint">
    The loss curve appears after the first measurements.</div>;
  const lo = Math.min(...data.map((p) => p.loss)), hi = Math.max(...data.map((p) => p.loss));
  const s0 = Math.min(...data.map((p) => p.step)), s1 = Math.max(...data.map((p) => p.step));
  const x = (s: number) => PAD.l + (s - s0) / Math.max(1, s1 - s0) * (W - PAD.l - PAD.r);
  const y = (l: number) => PAD.t + (hi - l) / Math.max(1e-6, hi - lo) * (H - PAD.t - PAD.b);
  const series = (split: string) => data.filter((p) => (p.split ?? "train") === split).sort((a, b) => a.step - b.step);
  const train = series("train"), val = series("val");
  const tPts = train.map((p) => [x(p.step), y(p.loss)] as [number, number]);
  const vPts = val.map((p) => [x(p.step), y(p.loss)] as [number, number]);
  const head = tPts[tPts.length - 1] ?? vPts[vPts.length - 1];
  const best = (val.length ? val : train).reduce((a, b) => (b.loss < a.loss ? b : a));
  const area = tPts.length > 1 ? `${smooth(tPts)} L${tPts[tPts.length - 1][0]},${H - PAD.b} L${tPts[0][0]},${H - PAD.b} Z` : "";
  const ticks = [hi, (hi + lo) / 2, lo];
  const near = hover == null ? null : data.reduce((a, b) => (Math.abs(x(b.step) - hover) < Math.abs(x(a.step) - hover) ? b : a));
  const drop = train.length > 1 ? (train[0].loss - train[train.length - 1].loss) / train[0].loss : null;
  return <figure className="relative">
    <figcaption className="mb-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem] text-muted">
      <span className="flex items-center gap-1"><i className="inline-block h-0.5 w-3 rounded bg-accent" /> training loss</span>
      <span className="flex items-center gap-1"><i className="inline-block h-0.5 w-3 rounded border-t border-dashed border-fg" /> validation loss</span>
      {drop != null && drop > 0 && <span className="ml-auto text-success">▼ {(drop * 100).toFixed(1)}% lower than at the start of this run</span>}
    </figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Loss from step ${s0} to ${s1}: ${hi.toFixed(3)} to ${lo.toFixed(3)}`}
      className="h-44 w-full touch-none select-none" onPointerLeave={() => setHover(null)}
      onPointerMove={(e) => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); setHover((e.clientX - r.left) / r.width * W); }}>
      <defs>
        <linearGradient id={`fill-${uid}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.45" /><stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" /></linearGradient>
        <filter id={`glow-${uid}`} x="-10%" y="-30%" width="120%" height="160%"><feGaussianBlur stdDeviation="2.5" result="b" /><feMerge><feMergeNode in="b" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
      </defs>
      {ticks.map((t, i) => <g key={i}><line x1={PAD.l} x2={W - PAD.r} y1={y(t)} y2={y(t)} stroke="currentColor" strokeOpacity="0.08" />
        <text x={PAD.l - 4} y={y(t) + 3} fontSize="9" textAnchor="end" fill="currentColor" fillOpacity="0.45">{t.toFixed(2)}</text></g>)}
      <text x={PAD.l} y={H - 6} fontSize="9" fill="currentColor" fillOpacity="0.45">step {s0.toLocaleString()}</text>
      <text x={W - PAD.r} y={H - 6} fontSize="9" textAnchor="end" fill="currentColor" fillOpacity="0.45">step {s1.toLocaleString()}</text>
      {area && <path d={area} fill={`url(#fill-${uid})`} className="animate-fade-in" />}
      {tPts.length > 1 && <path d={smooth(tPts)} fill="none" stroke="#e0313d" strokeWidth="2.2" filter={`url(#glow-${uid})`} className="loss-draw" pathLength={1} />}
      {vPts.length > 1 && <path d={smooth(vPts)} fill="none" stroke="#f5f5f5" strokeOpacity="0.8" strokeWidth="1.4" strokeDasharray="5 4" />}
      {vPts.length === 1 && <circle cx={vPts[0][0]} cy={vPts[0][1]} r="3" fill="#f5f5f5" />}
      <g transform={`translate(${x(best.step)},${y(best.loss)})`}><path d="M0,-6 L1.8,-1.8 L6,0 L1.8,1.8 L0,6 L-1.8,1.8 L-6,0 L-1.8,-1.8 Z" fill="#e0a63a" />
        <title>Best so far: {best.loss.toFixed(4)} at step {best.step}</title></g>
      {head && <g transform={`translate(${head[0]},${head[1]})`}>
        {live && <circle r="9" fill="#e0313d" opacity="0.35" className="chart-ping" />}
        <circle r="3.5" fill="#ff5a64" stroke="#080808" strokeWidth="1" /></g>}
      {near && <g><line x1={x(near.step)} x2={x(near.step)} y1={PAD.t} y2={H - PAD.b} stroke="currentColor" strokeOpacity="0.25" />
        <circle cx={x(near.step)} cy={y(near.loss)} r="3" fill="currentColor" /></g>}
    </svg>
    {near && <div className="pointer-events-none absolute right-2 top-6 rounded-md border border-border bg-surface-2 px-2 py-1 font-mono text-[0.6875rem] shadow-lg">
      step {near.step.toLocaleString()} · {near.split ?? "train"} {near.loss.toFixed(4)}</div>}
  </figure>;
}
