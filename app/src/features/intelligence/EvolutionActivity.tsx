/**
 * AI → Evolution: the live stream of what MOTH's Evolution Engine actually did — data prepared,
 * training started, checkpoints, workers, evaluations, plan changes, promotions and rejections.
 * Messages are written by the engine when the event happens; technical details expand on demand.
 */
import { useEffect } from "react";
import { AlertTriangle, CircleDot, XCircle } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { CloudActivity } from "@/features/activity/CloudActivity";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type Event = { id: number; ts: number; kind: string; level: string; message: string; cycle_id: number | null; experiment_id: number | null; data: Record<string, unknown> | null };
const load = (url: string) => serverApi<Event[]>(url);

const TITLE: [RegExp, string][] = [
  [/^genesis\./, "Genesis"], [/^data\.(selected|approved)/, "Data selected"], [/^data\.prepared/, "Dataset prepared"],
  [/^data\.failed/, "Data preparation failed"], [/^data\./, "Data"], [/^cycle\.created/, "Cycle started"],
  [/^experiment\.planned/, "Experiment planned"], [/^experiment\.started/, "Training started"],
  [/^checkpoint\./, "Checkpoint saved"], [/^experiment\.trained/, "Training finished"], [/^experiment\.passed/, "Improvement detected"],
  [/^experiment\.rejected/, "Candidate rejected"], [/^experiment\.early_stopped/, "Stopped early"],
  [/^experiment\.(paused|interrupted)/, "Training paused"], [/^experiment\.resumed|^engine\.recovered/, "Recovered"],
  [/^experiment\.(failed|retry)/, "Training problem"], [/^plan\.adjusted/, "Plan adjusted"], [/^plan\.parallel/, "Running in parallel"],
  [/^data\.scaled/, "Library grown"], [/^storage\.retention/, "Old versions cleaned up"], [/^storage\./, "Storage"], [/^worker\.connected/, "Worker connected"],
  [/^worker\.disconnected/, "Worker disconnected"], [/^deploy\.done/, "New model promoted"], [/^deploy\.verified/, "Health verified"], [/^deploy\.rollback/, "Rolled back"],
  [/^cycle\.rejected/, "Kept the current model"], [/^cycle\./, "Cycle"], [/^engine\.started|^engine\.resumed/, "Evolution started"],
  [/^engine\.paused/, "Evolution paused"], [/^engine\.idle/, "Waiting"], [/^evaluation\./, "Evaluation"], [/^growth\./, "Growth"],
];
const title = (kind: string) => TITLE.find(([rx]) => rx.test(kind))?.[1] ?? kind.replace(/[._]/g, " ");
const time = (ts: number) => {
  const d = new Date(ts * 1000);
  return d.toDateString() === new Date().toDateString() ? d.toLocaleTimeString() : d.toLocaleString();
};

export function EvolutionActivity() {
  const owner = useAccount((s) => s.user?.role === "owner");
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data, error, reload } = useResource<Event[]>(owner ? "/v1/admin/evolution/events?limit=40" : null, [], undefined, server + "\0" + token, load);
  useEffect(() => { if (!owner) return; const t = setInterval(() => { if (!document.hidden) void reload(); }, 5000); return () => clearInterval(t); }, [owner, reload]);
  return <Card aria-label="Evolution activity"><CardContent className="p-3 sm:p-4">
    <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-medium">Live activity</h2><span className="text-[11px] text-faint">Recorded by the Evolution Engine</span></div>
    {!owner ? <CloudActivity /> : error ? <p role="alert" className="text-xs text-danger">Activity unavailable: {error}</p>
      : !data ? <p className="text-xs text-muted">Loading…</p>
      : !data.length ? <p className="text-xs text-muted">Nothing has happened yet. Start Evolution and every step appears here.</p>
      : <ol className="max-h-96 space-y-1 overflow-y-auto pr-1">{data.map((e) => {
          const Icon = e.level === "error" ? XCircle : e.level === "warning" ? AlertTriangle : CircleDot;
          const details = { kind: e.kind, ...(e.cycle_id ? { cycle: e.cycle_id } : {}), ...(e.experiment_id ? { experiment: e.experiment_id } : {}), ...(e.data ?? {}) };
          return <li key={e.id}><details className="group rounded-md px-2 py-1.5 hover:bg-surface-2">
            <summary className="flex cursor-pointer list-none items-start gap-2 text-xs">
              <Icon className={cn("mt-0.5 size-3.5 shrink-0", e.level === "error" ? "text-danger" : e.level === "warning" ? "text-warning" : "text-accent")} />
              <span className="min-w-0 flex-1"><span className="font-medium text-fg">{title(e.kind)}</span> <span className="text-muted">— {e.message}</span></span>
              <time className="shrink-0 text-[10px] text-faint" dateTime={new Date(e.ts * 1000).toISOString()}>{time(e.ts)}</time>
            </summary>
            <pre className="mt-1 overflow-x-auto rounded bg-bg p-2 text-[10px] text-muted">{JSON.stringify(details, null, 2)}</pre>
          </details></li>;
        })}</ol>}
  </CardContent></Card>;
}
