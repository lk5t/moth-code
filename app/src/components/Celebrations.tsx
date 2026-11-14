/**
 * 0.10.0: in-app toasts for MOTH's news and a confetti burst when MOTH is promoted (lib/alerts.ts).
 */
import { useEffect, useState } from "react";
import { AlertTriangle, PartyPopper, Sparkles, X } from "lucide-react";
import { dismissAlert, useAlerts } from "@/lib/alerts";

const COLORS = ["#c1121f", "#ff5a64", "#f5f5f5", "#e0a63a", "#3fb27f", "#8a0b14"];

export function Confetti({ burst }: { burst: number }) {
  const [pieces, setPieces] = useState<number>(0);
  useEffect(() => {
    if (!burst) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    setPieces(burst);
    const t = setTimeout(() => setPieces(0), 3600);
    return () => clearTimeout(t);
  }, [burst]);
  if (!pieces) return null;
  return <div className="confetti" aria-hidden="true">{Array.from({ length: 90 }, (_, i) => {
    const left = (i * 37) % 100, x = ((i * 53) % 60) - 30, d = 1.8 + ((i * 7) % 12) / 10, delay = ((i * 13) % 10) / 20;
    return <i key={`${pieces}-${i}`} style={{ left: `${left}%`, background: COLORS[i % COLORS.length],
      ["--x" as string]: `${x}vw`, ["--d" as string]: `${d}s`, ["--delay" as string]: `${delay}s`, ["--r" as string]: `${(i % 2 ? 1 : -1) * (360 + i * 9)}deg` }} />;
  })}</div>;
}

export function Celebrations() {
  const toasts = useAlerts((s) => s.toasts), burst = useAlerts((s) => s.celebrate);
  useEffect(() => {
    if (!toasts.length) return;
    const t = setTimeout(() => dismissAlert(toasts[0].id), 12_000);
    return () => clearTimeout(t);
  }, [toasts]);
  return <>
    <Confetti burst={burst} />
    <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(360px,calc(100vw-32px))] flex-col gap-2">
      {toasts.map((t) => <div key={t.id} role="status"
        className={`toast-in pointer-events-auto flex items-start gap-2 rounded-xl border bg-surface-2/95 p-3 text-xs shadow-2xl backdrop-blur ${t.tone === "promoted" ? "glow-border border-accent/60" : t.tone === "problem" ? "border-warning/50" : "border-border"}`}>
        <span className={`mt-0.5 shrink-0 [&_svg]:size-4 ${t.tone === "problem" ? "text-warning" : "text-accent"}`}>
          {t.tone === "promoted" ? <PartyPopper /> : t.tone === "problem" ? <AlertTriangle /> : <Sparkles />}</span>
        <div className="min-w-0 flex-1"><p className="font-medium text-fg">{t.tone === "promoted" ? "MOTH got smarter" : t.tone === "problem" ? "Needs a look" : "MOTH"}</p>
          <p className="mt-0.5 text-muted">{t.message}</p></div>
        <button aria-label="Dismiss" onClick={() => dismissAlert(t.id)} className="shrink-0 text-faint hover:text-fg [&_svg]:size-3.5"><X /></button>
      </div>)}
    </div>
  </>;
}
