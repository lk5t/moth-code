/**
 * 0.10.0: the live sample is the model's own answer to the same question at each evaluation.
 * 2.5: live measurements (speed, held-out loss, the training computers' load) replace the guessed stage meter.
 */
import { useEffect, useRef, useState } from "react";
import { AnimatedNumber } from "@/components/AnimatedNumber";

type Any = Record<string, any>;

/** How the held-out loss moved over the last few measurements (negative = better). */
export function recentTrend(history: Any[] | undefined, window = 5): number | null {
  const val = (history ?? []).filter((p) => p.split === "val" && Number.isFinite(p.loss)).map((p) => Number(p.loss));
  if (val.length < 2) return null;
  const a = val[Math.max(0, val.length - 1 - window)], b = val[val.length - 1];
  return a ? (b - a) / a : null;
}

function Meter({ label, value, warn }: { label: string; value: number | null | undefined; warn?: boolean }) {
  const v = typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : null;
  return <div className="flex items-center gap-1.5">
    <span className="w-8 text-faint">{label}</span>
    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-3">
      {v != null && <div className={`h-full rounded-full transition-[width] duration-700 ease-out ${warn ? "bg-warning" : "bg-accent"}`} style={{ width: `${Math.max(2, v * 100)}%` }} />}
    </div>
    <span className="w-9 text-right font-mono text-muted">{v != null ? `${Math.round(v * 100)}%` : "—"}</span>
  </div>;
}

/**
 * 2.5: what is happening right now, measured — no estimates. Speed and held-out loss come from the run's own
 * reports, the load bars from each training computer's last check-in, and the data reads from MOTH Cloud.
 * (Replaces the "learning stage" meter, which was a guess drawn from the loss.)
 */
export function LiveVitals({ report, compute, passes }: { report: Any; compute?: Any[]; passes?: number | null }) {
  const trend = recentTrend(report.history);
  const val = report.val_loss ?? report.best_val;
  return <div aria-label="Live measurements" className="rounded-lg border border-border bg-bg p-3 text-xs">
    <div className="mb-2 flex items-center gap-1.5 text-faint"><span className="live-dot" />Live · measured</div>
    <dl className="grid grid-cols-2 gap-2">
      <div><dt className="text-faint">Speed</dt><dd className="font-mono text-fg">{typeof report.tokens_per_sec === "number"
        ? <><AnimatedNumber value={report.tokens_per_sec} /> tok/s</> : <span className="text-muted">measuring…</span>}</dd></div>
      <div><dt className="text-faint">Held-out loss</dt><dd className="font-mono text-fg">{typeof val === "number" ? <AnimatedNumber value={val} digits={3} /> : "—"}
        {trend != null && <span className={`ml-1 ${trend <= 0 ? "text-success" : "text-warning"}`}>{trend <= 0 ? "▼" : "▲"}{Math.abs(trend * 100).toFixed(1)}%</span>}</dd></div>
      {typeof report.rounds === "number" && <div><dt className="text-faint">Shared round</dt>
        <dd className="font-mono text-fg">{Math.min(Number(report.round ?? 0) + 1, report.rounds)} / {report.rounds}</dd></div>}
      {typeof passes === "number" && <div><dt className="text-faint">Data read</dt>
        <dd className={`font-mono ${passes > 2 ? "text-warning" : "text-fg"}`}>{passes.toFixed(1)}×</dd></div>}
    </dl>
    {(compute ?? []).length > 0 && <ul className="mt-2 space-y-1.5 border-t border-border pt-2">{(compute ?? []).map((c, i) =>
      <li key={i} className="space-y-1 animate-fade-in">
        <div className="flex items-center gap-1.5"><span className={c.seen_seconds_ago < 90 ? "live-dot" : "size-1.5 rounded-full bg-faint"} />
          <span className="truncate text-fg">{c.cloud ? "MOTH Cloud" : c.name}</span>
          <span className="text-faint">{c.kind.toUpperCase()}{typeof c.gpu_temp_c === "number" ? ` · ${Math.round(c.gpu_temp_c)}°C` : ""}</span>
          {typeof c.part_progress === "number" && <span className="ml-auto font-mono text-muted">{Math.round(c.part_progress * 100)}% of part</span>}</div>
        {c.kind === "gpu" ? <Meter label="GPU" value={c.gpu} warn={typeof c.gpu === "number" && c.gpu < 0.5} />
          : <Meter label="CPU" value={c.cpu} />}
      </li>)}</ul>}
  </div>;
}

function Typewriter({ text }: { text: string }) {
  const [n, setN] = useState(text.length);
  const prev = useRef(text);
  useEffect(() => {
    if (text === prev.current) return;
    prev.current = text;
    const still = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (still) { setN(text.length); return; }
    setN(0);
    const t = setInterval(() => setN((k) => (k >= text.length ? (clearInterval(t), k) : k + 1)), 28);
    return () => clearInterval(t);
  }, [text]);
  return <>{text.slice(0, n)}{n < text.length && <span className="ml-px inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse bg-accent" />}</>;
}

export function WritingNow({ samples, prompt }: { samples: { step: number; text: string }[]; prompt?: string }) {
  if (!samples?.length) return null;
  const last = samples[samples.length - 1], earlier = samples.slice(0, -1).reverse().slice(0, 2);
  return <section aria-label="What MOTH writes right now" className="rounded-lg border border-border bg-bg p-3 text-xs">
    <div className="mb-1.5 flex items-center gap-2"><span className="live-dot" /><span className="text-faint">MOTH is writing (step {last.step?.toLocaleString()})</span></div>
    {prompt && <p className="mb-1 text-muted">You: {prompt}</p>}
    <p className="min-h-8 whitespace-pre-wrap break-words font-mono text-[0.75rem] leading-relaxed text-fg">
      MOTH: <Typewriter text={last.text || "…"} /></p>
    {earlier.length > 0 && <ul className="mt-2 space-y-0.5 border-t border-border pt-2 text-[0.6875rem] text-faint">
      {earlier.map((s) => <li key={s.step} className="truncate">step {s.step?.toLocaleString()}: {s.text || "…"}</li>)}</ul>}
  </section>;
}
