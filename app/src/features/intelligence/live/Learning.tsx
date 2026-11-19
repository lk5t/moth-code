/**
 * 0.10.0: how far MOTH has come, in words people understand. The stage comes from the measured validation
 * loss per byte of text (a per-token loss is converted with a typical 3.6 bytes per BPE token), and the
 * live sample is the model's own answer to the same question at each evaluation.
 */
import { useEffect, useRef, useState } from "react";

export const STAGES = [
  { name: "Babbling", hint: "random letters", max: Infinity },
  { name: "Letters", hint: "spacing and common letters", max: 3.0 },
  { name: "Words", hint: "real words appear", max: 2.2 },
  { name: "Phrases", hint: "words fit together", max: 1.6 },
  { name: "Sentences", hint: "understandable sentences", max: 1.2 },
  { name: "Chat", hint: "answers that make sense", max: 0.95 },
];

export function stageOf(loss: number | null | undefined, per: "byte" | "token" = "byte") {
  if (loss == null || !Number.isFinite(loss)) return null;
  const perByte = per === "token" ? loss / 3.6 : loss;
  let i = 0;
  for (let k = 1; k < STAGES.length; k++) if (perByte <= STAGES[k].max) i = k;
  const next = STAGES[i + 1];
  const lo = next ? next.max : 0, hi = STAGES[i].max === Infinity ? 4.5 : STAGES[i].max;
  const within = next ? Math.max(0, Math.min(1, (hi - perByte) / Math.max(1e-6, hi - lo))) : 1;
  return { index: i, within, perByte };
}

export function StageMeter({ loss, per }: { loss: number | null | undefined; per: "byte" | "token" }) {
  const st = stageOf(loss, per);
  if (!st) return null;
  const total = (st.index + st.within) / (STAGES.length - 1);
  return <div aria-label={`Learning stage: ${STAGES[st.index].name}`} className="rounded-lg border border-border bg-bg p-3">
    <div className="mb-2 flex items-baseline justify-between gap-2 text-xs">
      <span className="text-faint">Learning stage</span>
      <span className="font-medium text-fg">{STAGES[st.index].name} <span className="font-normal text-muted">· {STAGES[st.index].hint}</span></span>
    </div>
    <div className="relative h-2 rounded-full bg-surface-3">
      <div className="progress-live absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-[#5a0a10] via-accent to-[#ff6b75] shadow-[0_0_12px_var(--color-accent)] transition-[width] duration-1000 ease-out"
        style={{ width: `${Math.max(3, total * 100)}%` }} />
      {STAGES.map((s, i) => <span key={s.name} title={s.name}
        className={`absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg ${i <= st.index ? "bg-accent" : "bg-surface-3"}`}
        style={{ left: `${(i / (STAGES.length - 1)) * 100}%` }} />)}
    </div>
    <ol className="mt-2 grid grid-cols-6 text-center text-[0.59375rem] leading-tight text-faint [&>li]:truncate">{STAGES.map((s, i) =>
      <li key={s.name} className={i === st.index ? "font-medium text-fg" : i < st.index ? "text-muted" : ""}>{s.name}</li>)}</ol>
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
