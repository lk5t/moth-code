/**
 * AI → Evolution: the one-click control. Start Evolution creates a first model when there is none,
 * selects trusted data and keeps MOTH improving within the Owner's limits; Pause stops at the next
 * checkpoint. Shows what MOTH is doing now and why it changed its plan, from the server's records only.
 */
import { useEffect, useState } from "react";
import { Pause, Play, Sparkles } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { refreshCloudProgress } from "@/lib/cloud-progress";
import { secure } from "@/features/owner/ops";
import { LivingMoth } from "@/components/LivingMoth";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

type Any = Record<string, any>;
const path = "/v1/admin/evolution/autopilot";
const load = (url: string) => serverApi<Any>(url);
const STAGE: Record<string, string> = {
  genesis: "Ready for Genesis", off: "Off", paused: "Paused", idle: "Waiting", preparing_data: "Preparing data",
  planning: "Planning", waiting_for_compute: "Waiting for compute", training: "Training", evaluating: "Evaluating",
  deploying: "Deploying", monitoring: "Monitoring the new version",
};
const when = (t: number) => {
  const s = Math.round(t - Date.now() / 1000);
  if (s <= 60) return "within a minute";
  if (s < 3600) return `in about ${Math.round(s / 60)} min`;
  return `at ${new Date(t * 1000).toLocaleString()}`;
};

export function EvolutionControl({ progress }: { progress: Any | null }) {
  const owner = useAccount((s) => s.user?.role === "owner");
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data, error, reload } = useResource<Any>(owner ? path : null, [], undefined, server + "\0" + token, load);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState<string | null>(null), [steps, setSteps] = useState<string[]>([]);
  useEffect(() => { if (!owner) return; const t = setInterval(() => { if (!document.hidden) void reload(); }, 5000); return () => clearInterval(t); }, [owner, reload]);

  const act = async (what: "start" | "pause") => {
    setBusy(true); setNotice(null); setSteps([]);
    try {
      const r = await secure(() => serverApi<Any>(`${path}/${what}`, { method: "POST", timeoutMs: 600000 }));
      if (what === "start") setSteps(r.steps ?? []);
      refreshCloudProgress(true); await reload();
    } catch (e) { setNotice((e as Error).message); }
    finally { setBusy(false); }
  };

  // Everyone sees the stage; only the Owner controls it.
  const stage = data?.stage ?? (progress && !progress.current ? "genesis" : progress?.training?.paused ? "paused" : progress?.training?.cycle?.status ?? (progress ? "idle" : null));
  const running = data ? data.running : !!progress?.current && !progress?.training?.paused && progress?.training?.enabled !== false;
  const doing = data?.doing ?? (stage === "genesis" ? "There is no model yet." : progress?.training?.cycle?.waiting_reason ?? null);
  return <Card className="relative overflow-hidden" aria-label="Evolution">
    <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-accent/10 blur-3xl" />
    <CardContent className="relative space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-4">
        <LivingMoth className="size-12" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.22em] text-accent">Evolution · {stage ? STAGE[stage] ?? stage.replaceAll("_", " ") : "Loading"}</p>
          <h2 className="mt-1 text-lg font-medium">{stage === "genesis" ? "Start MOTH from zero" : running ? "MOTH is evolving" : "Evolution is not running"}</h2>
          <p role="status" className="mt-1 text-xs text-muted">{doing ?? (error ? `Status unavailable: ${error}` : "Reading status…")}</p>
        </div>
        {owner && (running
          ? <Button disabled={busy} variant="secondary" onClick={() => void act("pause")}><Pause className="size-4" />Pause Evolution</Button>
          : <Button disabled={busy || !data} onClick={() => void act("start")}><Play className="size-4" />{busy ? "Starting…" : "Start Evolution"}</Button>)}
      </div>
      {stage === "genesis" && owner && <p className="text-xs text-muted">Start Evolution creates a small, untrained model (99,648 parameters), selects trusted, licensed training data — coding first — prepares it and trains continuously within your resource budget. It starts knowing nothing; every improvement is measured on data it never trained on before it is kept.</p>}
      {running && data?.next_cycle_at && !["training", "evaluating", "planning", "deploying", "monitoring", "waiting_for_compute"].includes(stage) && <p className="text-xs text-faint">Next cycle {when(data.next_cycle_at)}.</p>}
      {steps.length > 0 && <ul className="space-y-1 rounded-lg border border-border bg-bg p-3 text-xs">{steps.map((s) => <li key={s} className="flex gap-2"><Sparkles className="mt-0.5 size-3 shrink-0 text-accent" />{s}</li>)}</ul>}
      {(data?.decisions?.length ?? 0) > 0 && <div className="text-xs">
        <p className="mb-1 text-faint">Why MOTH changed its plan</p>
        <ul className="space-y-1">{data!.decisions.slice(-4).reverse().map((d: Any, i: number) => <li key={i} className="border-l-2 border-accent/60 pl-2 text-muted">{d.message}</li>)}</ul>
      </div>}
      {data?.plan?.steps && <p className="text-[11px] text-faint">Current plan: {Number(data.plan.steps).toLocaleString()} steps per experiment · learning rate {Number(data.plan.lr).toExponential(1)} · batch {data.plan.batch_size}{data.autopilot ? "" : " (fixed — automatic planning is off in AI Settings)"}</p>}
      {data?.data?.error && <p className="text-xs text-warning">Data preparation: {data.data.error}</p>}
      {notice && <p role="alert" className="text-xs text-danger">{notice}</p>}
    </CardContent>
  </Card>;
}
