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
import { paramsLabel } from "@/lib/params";
import { modelLabel } from "@/lib/model-label";
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

  const act = async (what: "start" | "pause" | "resume") => {
    setBusy(true); setNotice(null); setSteps([]);
    try {
      // Resume continues exactly where Evolution was paused; Start (first time or when off) also chooses data.
      const url = what === "resume" ? "/v1/admin/evolution/resume" : `${path}/${what}`;
      const r = await secure(() => serverApi<Any>(url, { method: "POST", timeoutMs: 600000 }));
      if (what === "start") setSteps(r.steps ?? []);
      refreshCloudProgress(true); await reload();
    } catch (e) { setNotice((e as Error).message); }
    finally { setBusy(false); }
  };

  // Everyone sees the stage; only the Owner controls it.
  const stage = data?.stage ?? (progress && !progress.current ? "genesis" : progress?.training?.paused ? "paused" : progress?.training?.cycle?.status ?? (progress ? "idle" : null));
  const running = data ? data.running : !!progress?.current && !progress?.training?.paused && progress?.training?.enabled !== false;
  const doing = data?.doing ?? (stage === "genesis" ? "There is no model yet." : progress?.training?.cycle?.waiting_reason ?? null);
  const name = progress?.current ? modelLabel(progress.current) : "MOTH";
  return <Card className="relative overflow-hidden" aria-label="Evolution">
    <div aria-hidden className="pointer-events-none absolute -right-24 -top-24 size-72 rounded-full bg-accent/10 blur-3xl" />
    <CardContent className="relative space-y-4 p-5">
      <div className="flex flex-wrap items-center gap-4">
        <LivingMoth className="size-12" />
        <div className="min-w-0 flex-1">
          <p className="text-[10px] uppercase tracking-[0.22em] text-accent">Evolution · {stage ? STAGE[stage] ?? stage.replaceAll("_", " ") : "Loading"}</p>
          <h2 className="mt-1 text-lg font-medium">{stage === "genesis" ? "Start MOTH from zero" : running ? `${name} is evolving` : `${name} · Evolution is not running`}</h2>
          <p role="status" className="mt-1 text-xs text-muted">{doing ?? (error ? `Status unavailable: ${error}` : "Reading status…")}</p>
        </div>
        {owner && (running
          ? <Button disabled={busy} variant="secondary" onClick={() => void act("pause")}><Pause className="size-4" />Pause Evolution</Button>
          : stage === "paused"
            ? <Button disabled={busy || !data} onClick={() => void act("resume")}><Play className="size-4" />{busy ? "Resuming…" : "Resume Evolution"}</Button>
            : <Button disabled={busy || !data} onClick={() => void act("start")}><Play className="size-4" />{busy ? "Starting…" : "Start Evolution"}</Button>)}
      </div>
      {stage === "genesis" && owner && <p className="text-xs text-muted">Start Evolution creates a small, untrained model (99,648 parameters), selects trusted, licensed training data — coding first — prepares it and trains continuously within your resource budget. It starts knowing nothing; every improvement is measured on data it never trained on before it is kept.</p>}
      {running && data?.next_cycle_at && data.next_cycle_at * 1000 > Date.now() && !["training", "evaluating", "planning", "deploying", "monitoring", "waiting_for_compute"].includes(stage) && <p className="text-xs text-faint">The last round failed; retrying {when(data.next_cycle_at)}.</p>}
      {data && <CommandStrip data={data} />}
      {data?.intelligence && <IntelligenceCheck intel={data.intelligence} />}
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


const TASK: Record<string, string> = { evolve_train: "training", dist_shard: "training a shard of", eval_loss: "evaluating a candidate", train_round: "community training" };
const STATE: Record<string, string> = { working: "working", idle: "online, idle", unavailable: "unavailable" };
const share = (v: number | null | undefined) => (typeof v === "number" ? `${Math.round(v * 100)}%` : "—");
const tokens = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${(n / 1e3).toFixed(0)}k` : `${n}`);

/** MOTH Cloud and every worker as one computing network: task, load, speed and real contributions. */
const SHARED: Record<string, string> = { running: "joins in", starting: "starting", waiting: "waiting", "re-enrolling": "reconnecting",
  error: "not working", off: "off", revoked: "revoked", disabled: "off" };

function Machines({ server, workers }: { server?: Any; workers: Any[] }) {
  const rows = [...(server ? [server] : []), ...workers.filter((w) => w.online || w.last_error)];
  const offline = workers.filter((w) => !w.online && !w.last_error).length;
  if (!rows.length) return null;
  return <section aria-label="Computing network" className="rounded-lg border border-border bg-bg px-3 py-2">
    <p className="mb-1 text-faint">Computing network{offline ? ` · ${offline} worker(s) offline` : ""}</p>
    <ul className="space-y-1">{rows.map((m) => <li key={m.id} className="grid gap-x-3 border-b border-border py-1 last:border-0 sm:grid-cols-[1.4fr_1.6fr_1fr_1fr]">
      <span className="text-fg">{m.id === "cloud" ? m.name : `Worker #${m.id} · ${m.name}`} <span className={m.state === "working" ? "text-accent" : m.state === "unavailable" ? "text-warning" : "text-faint"}>· {STATE[m.state] ?? m.state}</span> <span className="text-faint">· {m.compute}{m.speed ? ` · ${m.speed.ratio.toFixed(1)}× this server's speed (${m.speed.basis})` : ""}{m.throughput ? ` · ${Math.round(m.throughput).toLocaleString()} tokens/s measured` : ""}</span>
        {m.last_error && <span className="block text-warning">Last problem: {m.last_error}</span>}
        {m.id === "cloud" && m.shared_training && <span className={`block ${["error", "re-enrolling"].includes(m.shared_training.state) ? "text-warning" : "text-faint"}`}>Shared runs with workers: {SHARED[m.shared_training.state] ?? m.shared_training.state}{m.shared_training.detail ? ` — ${m.shared_training.detail}` : ""}</span>}</span>
      <span className="text-muted">{m.paused ? "paused by its owner" : m.task ? `${TASK[m.task.kind] ?? m.task.kind}${m.task.experiment ? ` experiment #${m.task.experiment}` : ""}${typeof m.task.progress === "number" ? ` · ${Math.round(m.task.progress * 100)}%` : ""}` : "idle"}</span>
      <span className="text-faint">CPU {share(m.utilization?.cpu)} · memory {share(m.utilization?.memory)}</span>
      <span className="text-faint">{m.contribution?.runs ? `${m.contribution.runs} run(s) · ${tokens(m.contribution.tokens)} tokens trained` : "no finished runs yet"}</span>
    </li>)}</ul>
  </section>;
}

/** Objective, versions, workers and their tasks, and the current bottleneck — all from the server. */
function CommandStrip({ data }: { data: Any }) {
  const workers: Any[] = data.workers ?? [];
  const online = workers.filter((w) => w.online);
  return <div className="space-y-2 text-xs">
    {data.objective && <p className="text-muted"><span className="text-faint">Current objective · </span>{data.objective}</p>}
    <dl className="grid gap-2 sm:grid-cols-3">
      <div className="rounded-lg border border-border bg-bg px-3 py-2"><dt className="text-faint">Models</dt>
        <dd className="mt-0.5 text-fg">{data.versions?.active ? `Active ${data.versions.active_name ?? `v${data.versions.active}`}` : "None yet"}{data.versions?.previous ? ` · previous ${data.versions.previous_name ?? `v${data.versions.previous}`} kept for rollback` : ""}</dd></div>
      <div className="rounded-lg border border-border bg-bg px-3 py-2"><dt className="text-faint">Experiments in parallel</dt>
        <dd className="mt-0.5 text-fg">{data.parallel ?? 0} running{data.queued_jobs ? ` · ${data.queued_jobs} waiting for a worker` : ""}</dd></div>
      <div className="rounded-lg border border-border bg-bg px-3 py-2"><dt className="text-faint">Workers</dt>
        <dd className="mt-0.5 text-fg">{workers.length ? `${online.length} of ${workers.length} online · ${online.filter((w) => w.task).length} busy` : "None enrolled — MOTH Cloud trains alone"}</dd></div>
    </dl>
    <Machines server={data.server} workers={workers} />
    {data.bottleneck && <p role="status" className="rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-warning">Holding back progress: {data.bottleneck}</p>}
  </div>;
}


const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const ATTEMPT: Record<string, string> = {
  rejected: "Larger model did not improve performance enough. Kept the current version.",
  failed: "The larger candidate could not be trained. Kept the current version.",
  passed: "The larger model passed every check and competes for promotion.",
  cancelled: "Cancelled. Kept the current version.",
};

/** Capability-based growth: what limits MOTH now, measured capabilities, real size, growth outcomes. */
function IntelligenceCheck({ intel }: { intel: Any }) {
  const a: Any | null = intel.assessment ?? null;
  const caps: Any[] = a?.capabilities ?? [];
  const est: Any | null = a?.action === "grow" ? a?.estimate ?? null : null;
  return <section aria-label="Intelligence check" className="space-y-2 rounded-lg border border-border bg-bg px-3 py-2 text-xs">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="font-medium text-fg">Intelligence check</p>
      <p className="text-faint">Model v{intel.version}: {paramsLabel(intel.params, intel.params_verified)}</p>
    </div>
    {a ? <>
      {a.investigating && <p className="text-muted">{a.investigating}</p>}
      <p className="text-fg">{a.headline}</p>
      <p className="text-faint">Why: {a.reason}.</p>
      {est && <p className="text-faint">Estimated training memory {(est.memory_bytes / 2 ** 30).toFixed(1)} GB
        {est.fits_server ? " · fits this server" : ""}{est.workers_that_fit ? ` · fits ${est.workers_that_fit} MOTH worker(s)` : ""}
        {est.training_seconds ? ` · about ${Math.round(est.training_seconds / 60)} min of training` : " · training time not measured yet"}</p>}
    </> : <p className="text-muted">The next cycle measures what limits MOTH: capabilities, training progress, data and compute.</p>}
    {caps.length > 0 && <ul className="grid gap-1 sm:grid-cols-2">{caps.map((c) => <li key={c.capability} className="flex justify-between gap-2 border-b border-border py-0.5">
      <span className="text-muted">{c.name}</span>
      <span className={c.limited || c.stalled ? "text-warning" : "text-fg"}>
        {c.higher_is_better ? pct(c.value) : `loss ${Number(c.value).toFixed(3)}`}
        {c.target != null ? ` / target ${pct(c.target)}` : ""}
        {c.stalled ? " · not improving" : c.change != null ? " · improving" : ""}
      </span></li>)}</ul>}
    {a?.coherence && <details><summary className="cursor-pointer text-muted hover:text-fg">Replies: {a.coherence.explanation}</summary>
      <ul className="mt-1 space-y-0.5">{a.coherence.samples.map((x: Any) => <li key={x.prompt} className="text-faint"><span className="text-muted">{x.prompt}</span> → <span className="font-mono">{x.reply.trim() || "(empty)"}</span></li>)}</ul></details>}
    {(a?.causes?.length ?? 0) > 0 && <details><summary className="cursor-pointer text-muted hover:text-fg">Causes checked</summary>
      <ul className="mt-1 space-y-0.5">{a!.causes.map((c: Any) => <li key={c.cause} className="text-faint">
        <span className="text-muted">{c.cause.replaceAll("_", " ")}</span>: {c.found === true ? "yes" : c.found === false ? "no" : "not determined"} — {c.detail}</li>)}</ul></details>}
    {(intel.growth_attempts?.length ?? 0) > 0 && <div><p className="text-faint">Growth experiments</p>
      <ul className="space-y-0.5">{intel.growth_attempts.map((g: Any) => <li key={g.experiment} className="text-muted">
        Experiment #{g.experiment}: {g.params_before?.toLocaleString()} → {g.params_after?.toLocaleString()} parameters{g.measured ? " (counted from weights)" : " (planned)"} · {ATTEMPT[g.status] ?? `${g.status.replaceAll("_", " ")}…`}</li>)}</ul></div>}
  </section>;
}
