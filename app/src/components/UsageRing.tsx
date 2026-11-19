/**
 * 1.0.12 usage ring next to the chat box: how much of the plan's 5-hour and weekly usage is gone, in percent
 * (never tokens). Click for both numbers and when each frees up. The Owner is unlimited.
 */
import { useEffect, useRef, useState } from "react";
import { serverApi, useAccount } from "@/lib/account";
import { navigate } from "@/lib/navigation";
import { cn, whenVisible } from "@/lib/utils";

type Window = { percent: number; resets_at: number | null };
export type Limits = { plan: string; unlimited: boolean; session: Window; weekly: Window };

export function resetIn(ts: number | null, now = Date.now() / 1000): string {
  if (!ts) return "not in use";
  const s = Math.max(0, ts - now);
  if (s < 3600) return `frees up in ${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `frees up in ${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
  return `frees up in ${Math.floor(s / 86400)} d ${Math.round((s % 86400) / 3600)} h`;
}

export function UsageRing({ refreshKey }: { refreshKey?: unknown }) {
  const user = useAccount((s) => s.user);
  const [lim, setLim] = useState<Limits | null>(null);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!user) return;
    let alive = true;
    const load = () => serverApi<Limits>("/v1/billing/limits", { retries: 0 }).then((l) => alive && setLim(l)).catch(() => {});
    void load();
    const t = setInterval(whenVisible(load), 60_000);
    return () => { alive = false; clearInterval(t); };
  }, [user?.id, refreshKey]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  if (!user || !lim) return null;
  const pct = lim.unlimited ? 0 : Math.max(lim.session.percent, lim.weekly.percent);
  const r = 7, c = 2 * Math.PI * r;
  const tone = pct >= 90 ? "text-danger" : pct >= 70 ? "text-warning" : "text-accent";
  return <div ref={box} className="relative">
    <button aria-label={lim.unlimited ? "Usage: unlimited" : `Usage: ${Math.round(pct)}% used`} title="Plan usage"
      onClick={() => setOpen(!open)} className="flex size-8 items-center justify-center rounded-md hover:bg-surface">
      <svg viewBox="0 0 18 18" className={cn("size-[18px] -rotate-90", tone)}>
        <circle cx="9" cy="9" r={r} fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2.2" />
        {!lim.unlimited && <circle cx="9" cy="9" r={r} fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - Math.min(100, pct) / 100)} className="transition-[stroke-dashoffset] duration-500" />}
      </svg>
    </button>
    {open && <div role="dialog" aria-label="Plan usage"
      className="absolute bottom-10 right-0 z-30 w-64 rounded-lg border border-border bg-surface p-3 text-xs shadow-xl">
      <div className="mb-2 flex items-center justify-between"><span className="font-medium text-fg">Plan usage</span>
        <span className="capitalize text-muted">{lim.unlimited ? "Owner · unlimited" : lim.plan}</span></div>
      {lim.unlimited ? <p className="text-muted">No limits on this account.</p> : <>
        <Bar label="5-hour window" w={lim.session} />
        <Bar label="This week" w={lim.weekly} />
        {pct >= 100 && <p className="mt-2 text-danger">Limit reached: chat continues with credits, or when it frees up.</p>}
        <button className="mt-2 text-accent hover:underline" onClick={() => { setOpen(false); navigate("settings"); }}>Plans & usage →</button>
      </>}
    </div>}
  </div>;
}

function Bar({ label, w }: { label: string; w: Window }) {
  return <div className="mb-2">
    <div className="flex justify-between"><span className="text-muted">{label}</span><span className="font-mono text-fg">{Math.round(w.percent)}%</span></div>
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-border">
      <div className={cn("h-full rounded-full", w.percent >= 90 ? "bg-danger" : "bg-accent")} style={{ width: `${Math.min(100, w.percent)}%` }} />
    </div>
    <div className="mt-0.5 text-[0.65625rem] text-faint">{resetIn(w.resets_at)}</div>
  </div>;
}
