import { useMemo, useState } from "react";

export interface MetricPoint {
  step: number;
  split: string;
  loss: number;
}

/** Train/validation loss curves (log-free, auto-scaled). Real logged values only. */
export function LossChart({ points, height = 220 }: { points: MetricPoint[]; height?: number }) {
  const [hover, setHover] = useState<{ x: number; step: number } | null>(null);
  const width = 640;
  const pad = { l: 44, r: 12, t: 12, b: 26 };
  const train = points.filter((p) => p.split === "train");
  const val = points.filter((p) => p.split === "val");
  const { xs, ys, maxStep, minL, maxL } = useMemo(() => {
    const all = points.length ? points : [{ step: 0, split: "train", loss: 1 }];
    const maxStep = Math.max(1, ...all.map((p) => p.step));
    let minL = Math.min(...all.map((p) => p.loss));
    let maxL = Math.max(...all.map((p) => p.loss));
    if (maxL - minL < 1e-6) {
      maxL += 0.5;
      minL -= 0.5;
    }
    const xs = (s: number) => pad.l + (s / maxStep) * (width - pad.l - pad.r);
    const ys = (l: number) => pad.t + (1 - (l - minL) / (maxL - minL)) * (height - pad.t - pad.b);
    return { xs, ys, maxStep, minL, maxL };
  }, [points, height]);

  const path = (pts: MetricPoint[]) => pts.map((p, i) => `${i ? "L" : "M"}${xs(p.step).toFixed(1)},${ys(p.loss).toFixed(1)}`).join("");
  const ticks = 4;
  const nearest = (arr: MetricPoint[], step: number) =>
    arr.reduce<MetricPoint | null>((b, p) => (!b || Math.abs(p.step - step) < Math.abs(b.step - step) ? p : b), null);

  if (!points.length) {
    return <div className="flex items-center justify-center text-xs text-muted" style={{ height }}>No metrics logged yet</div>;
  }
  const ht = hover ? nearest(train, hover.step) : null;
  const hv = hover ? nearest(val, hover.step) : null;
  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
          const x = ((e.clientX - r.left) / r.width) * width;
          const step = Math.round(((x - pad.l) / (width - pad.l - pad.r)) * maxStep);
          setHover(step >= 0 && step <= maxStep ? { x, step } : null);
        }}
        onMouseLeave={() => setHover(null)}
      >
        {Array.from({ length: ticks + 1 }, (_, i) => {
          const l = minL + ((maxL - minL) * i) / ticks;
          return (
            <g key={i}>
              <line x1={pad.l} x2={width - pad.r} y1={ys(l)} y2={ys(l)} stroke="#1f1f1f" />
              <text x={pad.l - 6} y={ys(l) + 3} textAnchor="end" fontSize="10" fill="#6b6b6b">{l.toFixed(2)}</text>
            </g>
          );
        })}
        <text x={width - pad.r} y={height - 6} textAnchor="end" fontSize="10" fill="#6b6b6b">step {maxStep}</text>
        <text x={pad.l} y={height - 6} fontSize="10" fill="#6b6b6b">0</text>
        <path d={path(train)} fill="none" stroke="#C1121F" strokeWidth="1.6" style={{ filter: "drop-shadow(0 0 4px rgba(193,18,31,0.6))" }} />
        <path d={path(val)} fill="none" stroke="#e6e6e6" strokeWidth="1.4" strokeDasharray="4 3" />
        {val.map((p) => <circle key={p.step} cx={xs(p.step)} cy={ys(p.loss)} r="2.2" fill="#e6e6e6" />)}
        {hover && <line x1={hover.x} x2={hover.x} y1={pad.t} y2={height - pad.b} stroke="#444" />}
      </svg>
      <div className="mt-1 flex gap-4 text-[11px] text-muted">
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-accent" />train loss</span>
        <span className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-fg" />validation loss</span>
        {hover && (
          <span className="ml-auto text-fg">
            step {hover.step}
            {ht && ` · train ${ht.loss.toFixed(3)}`}
            {hv && ` · val ${hv.loss.toFixed(3)}`}
          </span>
        )}
      </div>
    </div>
  );
}
