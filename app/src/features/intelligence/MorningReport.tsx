/**
 * 0.10.0 morning report: what MOTH did while the Owner was away (GET /v1/admin/evolution/morning-report),
 * with the deployed model's answer to the same question then and now. It opens by itself after more
 * than six hours away, and can be opened at any time.
 */
import { useEffect, useState } from "react";
import { Sunrise, X } from "lucide-react";
import { serverApi } from "@/lib/account";
import { Button } from "@/components/ui/button";
import { AnimatedNumber } from "@/components/AnimatedNumber";

type Any = Record<string, any>;
const SEEN = "moth.lastSeen";
const AWAY = 6 * 3600;

function lastSeen(): number | null {
  try { const v = Number(localStorage.getItem(SEEN)); return Number.isFinite(v) && v > 0 ? v : null; } catch { return null; }
}
function markSeen() { try { localStorage.setItem(SEEN, String(Date.now() / 1000)); } catch { /* convenience only */ } }

export function MorningReport() {
  const [report, setReport] = useState<Any | null>(null);
  const [open, setOpen] = useState(false);
  const load = async (since?: number | null) => {
    try { setReport(await serverApi<Any>(`/v1/admin/evolution/morning-report${since ? `?since=${since}` : ""}`)); setOpen(true); }
    catch { setReport(null); }
  };
  useEffect(() => {
    const seen = lastSeen(), now = Date.now() / 1000;
    if (seen && now - seen > AWAY) void load(seen);
    markSeen();
    const t = setInterval(markSeen, 60_000);
    return () => clearInterval(t);
  }, []);
  if (!open || !report) return <div className="flex justify-end">
    <Button size="sm" variant="ghost" onClick={() => void load(lastSeen() && Date.now() / 1000 - lastSeen()! > 3600 ? lastSeen() : null)}><Sunrise /> Morning report</Button></div>;
  const hours = Math.round(report.hours ?? 12);
  return <section aria-label="Morning report" className="glow-border animate-pop rounded-xl border border-accent/40 bg-[linear-gradient(135deg,rgb(193_18_31/0.16),transparent_60%)] p-4">
    <div className="flex items-start gap-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-full bg-accent-soft text-accent [&_svg]:size-5"><Sunrise /></span>
      <div className="min-w-0 flex-1">
        <h2 className="text-sm font-medium">While you were away · the last {hours} hour{hours === 1 ? "" : "s"}</h2>
        <ul className="stagger mt-2 space-y-1 text-xs text-fg">{(report.highlights ?? []).map((h: string, i: number) =>
          <li key={i} className="flex gap-2"><span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent" />{h}</li>)}</ul>
        <dl className="mt-3 grid grid-cols-3 gap-2 text-xs">
          <div className="rounded-lg border border-border bg-bg px-2.5 py-2"><dt className="text-faint">Tokens read</dt><dd className="font-mono text-sm"><AnimatedNumber value={report.tokens ?? 0} /></dd></div>
          <div className="rounded-lg border border-border bg-bg px-2.5 py-2"><dt className="text-faint">Experiments</dt><dd className="font-mono text-sm"><AnimatedNumber value={report.experiments_finished ?? 0} /></dd></div>
          <div className="rounded-lg border border-border bg-bg px-2.5 py-2"><dt className="text-faint">Promotions</dt><dd className="font-mono text-sm"><AnimatedNumber value={report.promotions ?? 0} /></dd></div>
        </dl>
        {report.answer_now && <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
          {report.answer_before && <div className="rounded-lg border border-border bg-bg p-2.5"><p className="text-faint">Before{report.answer_before_at ? ` (${new Date(report.answer_before_at * 1000).toLocaleString()})` : ""}</p>
            <p className="mt-1 font-mono text-[11px] text-muted">{report.answer_before}</p></div>}
          <div className="rounded-lg border border-accent/40 bg-bg p-2.5"><p className="text-faint">Now — “{report.question}”</p>
            <p className="mt-1 font-mono text-[11px] text-fg">{report.answer_now}</p></div>
        </div>}
        {report.problems?.length > 0 && <p className="mt-2 text-[11px] text-warning">Needs a look: {report.problems.join(" · ")}</p>}
      </div>
      <button aria-label="Close the morning report" onClick={() => setOpen(false)} className="text-faint hover:text-fg [&_svg]:size-4"><X /></button>
    </div>
  </section>;
}
