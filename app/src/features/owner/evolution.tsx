/**
 * Owner Dashboard → Evolution: MOTH improving its own model.
 *
 * Progressive disclosure: the current state and the few controls that matter first; experiments,
 * comparisons, versions, data, resources, activity and settings one click deeper. Every number comes
 * from the MOTH Cloud API (no estimates are invented: progress bars appear only when the trainer
 * reports progress, and "waiting" is shown as waiting, with the reason).
 */
import { useRef, useState } from "react";
import { Activity, Cpu, Database, FlaskConical, GitBranch, HardDrive, MemoryStick, Pause, Play, RotateCcw, Settings2, Sparkles, Upload } from "lucide-react";
import { serverApi } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { Switch } from "@/components/ui/switch";
import { EmptyState } from "@/components/ui/empty";
import { cn, formatNumber, timeAgo } from "@/lib/utils";
import { formatBytes, useAction, usePoll } from "./ops";

type Any = Record<string, any>;
const post = (path: string, json?: unknown) => serverApi(path, { method: "POST", json });

const CYCLE_LABEL: Record<string, string> = {
  planning: "Planning experiments", waiting_for_compute: "Waiting for compute", training: "Training",
  evaluating: "Evaluating candidates", deploying: "Deploying", monitoring: "Monitoring the new model",
  completed: "Completed", rejected: "No improvement found", failed: "Failed", cancelled: "Cancelled",
  rolled_back: "Rolled back",
};
const VARIANT: Record<string, any> = {
  training: "accent", running: "accent", monitoring: "accent", deploying: "accent", evaluating: "accent",
  completed: "success", passed: "success", deployed: "success", published: "success",
  waiting_for_compute: "warning", waiting: "warning", paused: "warning", rejected: "warning", evaluated: "warning",
  failed: "danger", rolled_back: "danger", cancelled: "default",
};

const pct = (x: number | null | undefined) => (x == null ? "—" : `${(x * 100).toFixed(x > -0.1 && x < 0.1 ? 2 : 1)}%`);
const num = (x: any) => (typeof x === "number" ? (Math.abs(x) >= 100 ? formatNumber(x, 1) : x.toFixed(3)) : "—");
const duration = (s?: number | null) => {
  if (s == null) return "—";
  if (s < 90) return `${Math.round(s)} s`;
  if (s < 5400) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
};
const when = (ts?: number | null) => (ts ? new Date(ts * 1000).toLocaleString() : "—");
/** A future time as "in 3 h" (timeAgo is for the past). */
const until = (ts: number) => {
  const s = ts - Date.now() / 1000;
  return s <= 60 ? "within a minute" : `in ${duration(s)}`;
};

export function EvolutionPanel() {
  const { data: st, load } = usePoll<Any>("/v1/admin/evolution/status", 5000);
  const { run, view } = useAction(load);
  if (!st) return null;
  const s = st.settings;
  const cyc = st.cycle;
  const active = cyc && !["completed", "rejected", "failed", "cancelled", "rolled_back"].includes(cyc.status);
  const headline = !s.enabled ? "Automatic evolution is off" : s.paused ? "Paused"
    : active ? CYCLE_LABEL[cyc.status] : st.state.idle_reason ? "Idle" : "Scheduled";
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardContent className="flex flex-col gap-3 text-xs">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 text-[13px] font-medium">
              <Sparkles className="size-4 text-accent" />{headline}
              {active && <Badge variant={VARIANT[cyc.status]}>cycle #{cyc.id}</Badge>}
            </div>
            <div className="flex items-center gap-2">
              <label className="flex items-center gap-2 text-muted">
                Automatic evolution
                <Switch checked={s.enabled} onCheckedChange={(v) => run(() => serverApi("/v1/admin/evolution/settings", { method: "PUT", json: { changes: { enabled: v } } }), v ? "Automatic evolution is on." : "Automatic evolution is off.")} />
              </label>
              {s.paused
                ? <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/evolution/resume"), "Resumed.")}><Play /> Resume</Button>
                : <Button size="sm" variant="ghost" onClick={() => run(() => post("/v1/admin/evolution/pause"), "Paused. Running training checkpoints and stops.")}><Pause /> Pause</Button>}
              {!active && <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/evolution/run"), "Evolution cycle started.")}>Run a cycle now</Button>}
              {active && !["deploying", "monitoring"].includes(cyc.status) && (
                <Button size="sm" variant="ghost" onClick={() => confirm("Cancel this evolution cycle? Unfinished training is stopped; the active model is not affected.") && run(() => post("/v1/admin/evolution/cancel"), "Cycle cancelled.")}>Cancel cycle</Button>
              )}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Fact label="Active model" value={st.active_model ? `v${st.active_model.version}` : "none"} sub={st.active_model ? `${st.active_model.name}${st.active_model.parent_version ? ` · from v${st.active_model.parent_version}` : ""}` : "deploy a model first"} />
            <Fact label="Latest stable" value={st.stable_model ? `v${st.stable_model.version}` : "—"} sub={st.stable_model?.method ? `${st.stable_model.method}` : undefined} />
            <Fact label="Training data" value={`${st.datasets.approved} approved`} sub={st.datasets.pending ? `${st.datasets.pending} waiting for your approval` : undefined} />
            <Fact label="Next cycle" value={active ? "running now" : s.paused || !s.enabled ? "—" : st.state.next_cycle_at ? until(st.state.next_cycle_at) : "at the next check"} sub={`every ${s.interval_hours} h${s.auto_deploy ? " · deploys automatically" : " · you deploy"}`} />
          </div>
          {!active && st.state.idle_reason && <div className="rounded border border-border bg-surface-2 p-2 text-muted">{st.state.idle_reason}</div>}
          {active && cyc.result?.waiting_reason && <div className="rounded border border-warning/40 bg-warning/10 p-2 text-warning">Waiting: {cyc.result.waiting_reason}</div>}
          {view}
        </CardContent>
      </Card>

      {cyc && <CycleCard cyc={cyc} />}
      {st.comparison && <Comparison c={st.comparison} />}
      <Versions reload={load} />
      <Resources />
      <Data reload={load} />
      <ActivityLog st={st} />
      <SettingsCard s={s} reload={load} />
    </div>
  );
}

function Fact({ label, value, sub }: { label: string; value: React.ReactNode; sub?: string }) {
  return (
    <div className="rounded-lg border border-border bg-bg px-3 py-2.5">
      <div className="text-[10.5px] uppercase tracking-wider text-faint">{label}</div>
      <div className="mt-0.5 font-mono text-base">{value}</div>
      {sub && <div className="truncate text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function CycleCard({ cyc }: { cyc: Any }) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><FlaskConical className="size-4 text-accent" />Cycle #{cyc.id}
          <Badge variant={VARIANT[cyc.status]}>{CYCLE_LABEL[cyc.status] ?? cyc.status}</Badge></CardTitle>
        <CardDescription>
          From model v{cyc.base_version} · started {cyc.started_at ? timeAgo(cyc.started_at) : timeAgo(cyc.created_at)}
          {cyc.finished_at ? ` · finished ${timeAgo(cyc.finished_at)}` : ""}{cyc.candidate_version ? ` · candidate v${cyc.candidate_version}` : ""}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        {cyc.error && <div className="text-danger">{cyc.error}</div>}
        {(cyc.plan?.notes ?? []).map((n: string, i: number) => <div key={i} className="text-muted">{n}</div>)}
        {!cyc.experiments.length && <div className="text-faint">No experiments in this cycle.</div>}
        {cyc.experiments.map((e: Any) => (
          <div key={e.id} className="rounded border border-border px-2.5 py-2">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <span className="font-medium">Experiment #{e.id}</span>
                <span className="text-muted"> · {e.dataset?.name} · lr {e.config.lr?.toExponential(1)} · {e.config.steps} steps{e.backend ? ` · ${e.backend === "worker" ? `MOTH worker${e.worker_id ? ` #${e.worker_id}` : ""}` : "this server"}` : ""}</span>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                {e.primary_improvement != null && <span className={cn(e.primary_improvement > 0 ? "text-success" : "text-danger")}>{e.primary_improvement > 0 ? "+" : ""}{pct(e.primary_improvement)}</span>}
                <Badge variant={VARIANT[e.status]}>{e.status}</Badge>
                <Button size="sm" variant="ghost" onClick={() => setOpen(open === e.id ? null : e.id)}>{open === e.id ? "Hide" : "Details"}</Button>
              </div>
            </div>
            <div className="mt-0.5 text-faint">{e.rationale}</div>
            {e.status === "running" && e.progress?.fraction != null && (
              <div className="mt-1.5 flex items-center gap-2">
                <Progress value={e.progress.fraction * 100} className="flex-1" />
                <span className="shrink-0 font-mono text-muted">step {e.progress.step}/{e.progress.max_steps}{e.progress.eta_seconds != null ? ` · ~${duration(e.progress.eta_seconds)} left` : ""}</span>
              </div>
            )}
            {e.status === "running" && e.progress?.fraction == null && e.backend === "worker" && <div className="mt-1 text-muted">Queued for a MOTH worker{e.job_id ? ` (job ${e.job_id})` : ""}; progress appears once a worker reports it.</div>}
            {e.error && e.status !== "passed" && <div className={cn("mt-1", e.status === "failed" ? "text-danger" : "text-warning")}>{e.error}</div>}
            {open === e.id && <ExperimentDetail id={e.id} />}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ExperimentDetail({ id }: { id: number }) {
  const { data } = usePoll<Any>(`/v1/admin/evolution/experiments/${id}`, 10000);
  const [log, setLog] = useState<string[] | null>(null);
  if (!data) return null;
  const t = data.metrics?.training ?? {};
  return (
    <div className="mt-2 flex flex-col gap-2 border-t border-border pt-2">
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 font-mono text-[11px] md:grid-cols-3">
        {Object.entries(data.config).filter(([k]) => !["architecture_key", "base_sha256", "dataset_sha256"].includes(k)).map(([k, v]) => (
          <span key={k}><span className="text-faint">{k}</span> {String(v)}</span>
        ))}
        <span><span className="text-faint">config hash</span> {data.config_hash.slice(0, 12)}</span>
        <span><span className="text-faint">compute</span> {duration(data.compute_seconds)}</span>
        {t.best_val != null && <span><span className="text-faint">best val loss</span> {num(t.best_val)}</span>}
        {t.peak_memory_bytes != null && <span><span className="text-faint">peak memory</span> {formatBytes(t.peak_memory_bytes)}</span>}
        {t.device && <span><span className="text-faint">device</span> {t.device}{t.resumed ? " (resumed)" : ""}</span>}
      </div>
      {data.metrics?.gates && <GateTable gates={data.metrics.gates} />}
      <div>
        <Button size="sm" variant="ghost" onClick={() => serverApi<Any>(`/v1/admin/evolution/experiments/${id}/log`).then((r) => setLog(r.lines))}>
          {log ? "Refresh training log" : "Show training log"}
        </Button>
        {log && <pre className="selectable mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-surface-2 p-2 text-[10.5px] text-muted">{log.join("\n") || "(empty)"}</pre>}
      </div>
    </div>
  );
}

function GateTable({ gates }: { gates: Any[] }) {
  return (
    <table className="w-full text-[11px]">
      <thead className="text-faint"><tr><th className="py-1 text-left font-normal">Check</th><th className="pl-4 text-right font-normal">Current</th><th className="pl-4 text-right font-normal">Candidate</th><th className="pl-4 text-left font-normal">Result</th></tr></thead>
      <tbody>
        {gates.map((g, i) => (
          <tr key={i} className="border-t border-border/60 align-top">
            <td className="py-1 pr-2">{g.name ?? g.gate.replace(/_/g, " ")}</td>
            <td className="pl-4 text-right font-mono">{num(g.baseline)}</td>
            <td className="pl-4 text-right font-mono">{num(g.candidate)}</td>
            <td className={cn("pl-4", g.passed ? "text-success" : "text-danger")}>{g.passed ? "✓" : "✗"} <span className="text-muted">{g.detail}</span></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Comparison({ c }: { c: Any }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Activity className="size-4 text-accent" />Latest evaluation: v{c.candidate_version} vs v{c.base_version}
          <Badge variant={VARIANT[c.status]}>{c.status === "passed" ? "improved" : c.status}</Badge></CardTitle>
        <CardDescription>The same deterministic benchmarks for both models. A candidate is promoted only if every check passes — lower training loss alone never counts.</CardDescription>
      </CardHeader>
      <CardContent><GateTable gates={c.gates} /></CardContent>
    </Card>
  );
}

function Versions({ reload }: { reload: () => void }) {
  const { data, load } = usePoll<Any>("/v1/admin/evolution/versions", 30000);
  const { run, view } = useAction(() => { load(); reload(); });
  const [all, setAll] = useState(false);
  if (!data) return null;
  const shown = all ? data.versions : data.versions.slice(0, 6);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><GitBranch className="size-4 text-accent" />Model versions</CardTitle>
        <CardDescription>Every version is kept. Roll back to any earlier version that passed evaluation; the switch is health-checked and the current model keeps serving if it fails.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 text-xs">
        {!data.versions.length && <div className="text-faint">No model versions yet.</div>}
        {shown.map((v: Any) => (
          <div key={v.version} className="flex items-center justify-between gap-2 rounded px-2 py-1 hover:bg-surface-2">
            <span className="min-w-0 truncate">
              <span className="font-mono">v{v.version}</span> <span className="text-muted">{v.name}</span>
              <span className="text-faint"> · {v.method ?? "—"}{v.parent_version ? ` from v${v.parent_version}` : ""}{v.score != null ? ` · score ${num(v.score)}` : ""}</span>
            </span>
            <span className="flex shrink-0 items-center gap-1.5">
              <Badge variant={v.version === data.deployed ? "accent" : VARIANT[v.status]}>{v.version === data.deployed ? "serving" : v.status}</Badge>
              {v.can_rollback && <Button size="sm" variant="ghost" onClick={() => confirm(`Switch MOTH Cloud to v${v.version}?`) && run(() => post("/v1/admin/evolution/rollback", { version: v.version }), `v${v.version} is now serving.`)}><RotateCcw /> Use</Button>}
            </span>
          </div>
        ))}
        {data.versions.length > 6 && <Button size="sm" variant="ghost" className="self-start" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${data.versions.length}`}</Button>}
        {view}
      </CardContent>
    </Card>
  );
}

function Meter({ icon, label, used, total, detail }: { icon: React.ReactNode; label: string; used: number | null; total: number | null; detail: string }) {
  const p = used != null && total ? (used / total) * 100 : null;
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-bg p-3">
      <div className="flex items-center gap-2 text-muted [&_svg]:size-4">{icon}{label}</div>
      <div className="font-mono text-base">{p == null ? "—" : `${p.toFixed(0)}%`}</div>
      <Progress value={p ?? 0} className={cn(p != null && p > 90 && "[&>div]:bg-danger")} />
      <div className="text-faint">{detail}</div>
    </div>
  );
}

function Resources() {
  const { data } = usePoll<Any>("/v1/admin/evolution/resources", 15000);
  if (!data) return null;
  const l = data.local;
  const mem = l.memory;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Cpu className="size-4 text-accent" />Compute</CardTitle>
        <CardDescription>Measured now. Training runs only where it fits, prefers quiet periods, and pauses (with a checkpoint) when MOTH Cloud gets busy or resources run low.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-xs">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Meter icon={<Cpu />} label="CPU" used={l.cpu_percent} total={l.cpu_percent == null ? null : 100} detail={`${l.cpu_count} cores${l.load_average ? ` · load ${l.load_average[0]}` : ""}`} />
          <Meter icon={<MemoryStick />} label="Memory" used={mem ? mem.total - mem.available : null} total={mem?.total ?? null} detail={mem ? `${formatBytes(mem.available)} free of ${formatBytes(mem.total)}` : "unavailable"} />
          <Meter icon={<HardDrive />} label="Disk" used={l.disk.used} total={l.disk.total} detail={`${formatBytes(l.disk.free)} free`} />
          <div className="flex flex-col gap-1 rounded-lg border border-border bg-bg p-3">
            <div className="text-muted">GPU</div>
            {l.gpus.length ? l.gpus.map((g: Any, i: number) => <div key={i} className="font-mono">{g.name} · {formatBytes(g.memory_free)} free</div>)
              : <div className="text-faint">No GPU on this server{data.workers.online_gpu ? "" : " — training waits for a GPU worker unless CPU training is enabled"}.</div>}
          </div>
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-muted">
          <span>MOTH workers: {data.workers.online}/{data.workers.total} online{data.workers.online_gpu ? ` · ${data.workers.online_gpu} with GPU` : ""}</span>
          <span>Inference: {data.inference.requests_per_minute} requests/min · {data.inference.active_requests} active</span>
          <span>Training in the last 24 h: {duration(data.training.compute_hours_24h * 3600)}</span>
          <span>Backends: {l.backends.join(", ")}</span>
        </div>
      </CardContent>
    </Card>
  );
}

function Data({ reload }: { reload: () => void }) {
  const { data, load } = usePoll<Any[]>("/v1/admin/evolution/datasets", 30000);
  const { run, view } = useAction(() => { load(); reload(); });
  const file = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [license, setLicense] = useState("");
  const [tags, setTags] = useState("");
  const [userData, setUserData] = useState(false);
  if (!data) return null;
  const upload = (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("name", name || f.name);
    fd.append("license", license);
    fd.append("tags", tags);
    fd.append("contains_user_data", String(userData));
    return run(() => serverApi("/v1/admin/evolution/datasets", { method: "POST", body: fd, timeoutMs: 600000 }),
      "Dataset prepared. Approve it to allow training on it.");
  };
  const approve = (d: Any) => {
    if (d.contains_user_data && !confirm(`“${d.name}” contains user data. Confirm that the users gave explicit permission to train MOTH on it.`)) return;
    run(() => post(`/v1/admin/evolution/datasets/${d.id}/approve`, { user_data_permission: d.contains_user_data }), `${d.name} approved for training.`);
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Database className="size-4 text-accent" />Training data</CardTitle>
        <CardDescription>
          MOTH only trains on data you add and approve here — never on conversations, workspaces or credentials by itself.
          Every source needs a license you are allowed to train under. Only names, licenses, sizes and hashes are shown or stored in history.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        {!data.length && <EmptyState title="No training data yet">Upload code or text (.zip, .tar.gz or a single file) below. It is tokenized for the deployed model.</EmptyState>}
        {data.map((d) => (
          <div key={d.id} className="flex items-center justify-between gap-2 rounded border border-border px-2 py-1.5">
            <span className="min-w-0">
              <span className="font-medium">{d.name}</span>
              <span className="text-faint"> · {formatNumber(d.tokens_train, 1)} tokens · {d.license}{d.tags.length ? ` · ${d.tags.join(", ")}` : ""}{d.contains_user_data ? " · contains user data" : ""}</span>
              {!d.compatible && <div className="text-warning">Made for a different tokenizer than the deployed model: needs an explicit model migration, not used.</div>}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              <Badge variant={d.status === "approved" ? "success" : d.status === "pending" ? "warning" : "default"}>{d.status}</Badge>
              {d.status === "pending" && <Button size="sm" onClick={() => approve(d)}>Approve</Button>}
              {d.status !== "revoked" && <Button size="sm" variant="ghost" onClick={() => confirm(`Stop using “${d.name}” for training? Unfinished experiments on it are cancelled; trained models are kept.`) && run(() => post(`/v1/admin/evolution/datasets/${d.id}/revoke`), "Revoked.")}>Revoke</Button>}
            </span>
          </div>
        ))}
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Input className="h-7 w-44 text-xs" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} />
          <Input className="h-7 w-40 text-xs" placeholder="License (required)" value={license} onChange={(e) => setLicense(e.target.value)} />
          <Input className="h-7 w-32 text-xs" placeholder="Tags (e.g. code)" value={tags} onChange={(e) => setTags(e.target.value)} />
          <label className="flex items-center gap-1.5 text-muted"><input type="checkbox" checked={userData} onChange={(e) => setUserData(e.target.checked)} /> contains user data</label>
          <input ref={file} type="file" accept=".zip,.tar.gz,.tgz,.tar,.txt,.md,.py,.js,.ts,.jsonl,text/*" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
          <Button size="sm" variant="secondary" disabled={!license.trim()} onClick={() => file.current?.click()}><Upload /> Add data</Button>
        </div>
        <TaskSuites />
        {view}
      </CardContent>
    </Card>
  );
}

function TaskSuites() {
  const { data, load } = usePoll<Any[]>("/v1/admin/evolution/suites", 60000);
  const { run, view } = useAction(load);
  const file = useRef<HTMLInputElement>(null);
  const [cap, setCap] = useState("reasoning");
  return (
    <details className="mt-1 text-muted">
      <summary className="cursor-pointer">Benchmark task suites ({data?.length ?? 0})</summary>
      <div className="mt-1.5 flex flex-col gap-1.5">
        <div className="text-faint">Optional JSON Lines files of {"{\"prompt\", \"answer\"}"} for reasoning, instruction following or accuracy. Without one these capabilities are reported as not measured.</div>
        {(data ?? []).map((t) => <div key={t.id}>{t.name} · {t.capability} · {t.items} items</div>)}
        <div className="flex items-center gap-2">
          <select className="h-7 rounded border border-border bg-surface px-1.5" value={cap} onChange={(e) => setCap(e.target.value)}>
            {["reasoning", "instruction_following", "accuracy", "coding"].map((c) => <option key={c} value={c}>{c.replace(/_/g, " ")}</option>)}
          </select>
          <input ref={file} type="file" accept=".jsonl,application/json" className="hidden" onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) {
              const fd = new FormData();
              fd.append("file", f);
              fd.append("name", f.name.replace(/\.jsonl$/, ""));
              fd.append("capability", cap);
              run(() => serverApi("/v1/admin/evolution/suites", { method: "POST", body: fd }), "Task suite added.");
            }
            e.target.value = "";
          }} />
          <Button size="sm" variant="ghost" onClick={() => file.current?.click()}><Upload /> Add suite</Button>
        </div>
        {view}
      </div>
    </details>
  );
}

function ActivityLog({ st }: { st: Any }) {
  const problems = [...st.warnings].sort((a: Any, b: Any) => b.ts - a.ts).slice(0, 8);
  return (
    <Card>
      <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="size-4 text-accent" />Activity</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-1 text-xs">
        {problems.length > 0 && (
          <div className="mb-1 flex flex-col gap-1 rounded border border-warning/30 bg-warning/5 p-2">
            {problems.map((e: Any) => <div key={e.id} className={e.level === "error" ? "text-danger" : "text-warning"}>{when(e.ts)} · {e.message}</div>)}
          </div>
        )}
        {st.recent.map((e: Any) => (
          <div key={e.id} className="flex gap-2"><span className="w-36 shrink-0 text-faint">{when(e.ts)}</span><span className="text-muted">{e.message}</span></div>
        ))}
        {!st.recent.length && <div className="text-faint">Nothing has happened yet.</div>}
      </CardContent>
    </Card>
  );
}

function SettingsCard({ s, reload }: { s: Any; reload: () => void }) {
  const { run, view } = useAction(reload);
  const [d, setD] = useState<Any>({});
  const get = (path: string) => (d[path] !== undefined ? d[path] : path.split(".").reduce((o: Any, k) => o?.[k], s));
  const set = (path: string, value: any) => setD({ ...d, [path]: value });
  const changes = () => {
    const out: Any = {};
    for (const [path, value] of Object.entries(d)) {
      const keys = path.split(".");
      let o = out;
      keys.slice(0, -1).forEach((k) => { o[k] = o[k] ?? {}; o = o[k]; });
      o[keys[keys.length - 1]] = value;
    }
    return out;
  };
  const numField = (path: string, label: string, step = "any") => (
    <label className="flex items-center justify-between gap-2">
      <span className="text-muted">{label}</span>
      <Input className="h-7 w-28 text-xs" type="number" step={step} value={get(path) ?? ""} onChange={(e) => set(path, e.target.value === "" ? null : Number(e.target.value))} />
    </label>
  );
  const sw = (path: string, label: string) => (
    <label className="flex items-center justify-between gap-2"><span className="text-muted">{label}</span>
      <Switch checked={!!get(path)} onCheckedChange={(x) => set(path, x)} /></label>
  );
  const quiet = get("schedule.quiet_hours_utc");
  return (
    <Card>
      <details>
        <summary className="cursor-pointer list-none">
          <CardHeader><CardTitle className="flex items-center gap-2"><Settings2 className="size-4 text-accent" />Settings</CardTitle>
            <CardDescription>Schedule, compute limits, training defaults and safety thresholds.</CardDescription></CardHeader>
        </summary>
        <CardContent className="grid grid-cols-1 gap-x-8 gap-y-2 text-xs md:grid-cols-2">
          <div className="flex flex-col gap-2">
            <div className="font-medium">Schedule</div>
            {numField("interval_hours", "Hours between cycles")}
            {sw("auto_deploy", "Deploy passing candidates automatically")}
            {numField("max_experiments_per_cycle", "Experiments per cycle", "1")}
            {numField("schedule.max_requests_per_minute", "Train only below (requests/min)")}
            <label className="flex items-center justify-between gap-2"><span className="text-muted">Training hours (UTC, optional)</span>
              <Input className="h-7 w-28 text-xs" placeholder="e.g. 1-6" value={Array.isArray(quiet) ? quiet.join("-") : ""}
                onChange={(e) => { const m = e.target.value.match(/^(\d{1,2})-(\d{1,2})$/); set("schedule.quiet_hours_utc", m ? [Number(m[1]), Number(m[2])] : null); }} /></label>
            {numField("budget.max_compute_hours_per_day", "Training budget (hours/day)")}
            {numField("budget.max_cycle_hours", "Max hours per cycle")}
            <div className="mt-2 font-medium">Compute</div>
            {sw("backends.local_gpu", "Use this server's GPU")}
            {sw("backends.workers", "Use MOTH GPU workers")}
            {sw("backends.local_cpu", "Allow CPU training on this server")}
            {numField("limits.cpu_threads", "CPU threads for training", "1")}
            {numField("limits.min_free_memory_gb", "Keep free memory (GB)")}
            {numField("limits.min_free_disk_gb", "Keep free disk (GB)")}
            {numField("limits.gpu_memory_fraction", "GPU memory fraction")}
          </div>
          <div className="flex flex-col gap-2">
            <div className="font-medium">Training defaults</div>
            {numField("training.steps", "Steps", "1")}
            {numField("training.lr", "Learning rate")}
            {numField("training.batch_size", "Batch size", "1")}
            {numField("training.seq_len", "Sequence length", "1")}
            {numField("min_dataset_tokens", "Minimum dataset tokens", "1")}
            <div className="mt-2 font-medium">Promotion gates</div>
            {numField("gates.min_improvement", "Required improvement (0.005 = 0.5%)")}
            {numField("gates.retention_tolerance", "Allowed retention loss")}
            {numField("gates.max_speed_regression", "Allowed speed loss")}
            {numField("monitoring.minutes", "Monitor new models (minutes)")}
            {numField("monitoring.max_error_rate", "Roll back above error rate")}
            {numField("max_consecutive_failures", "Pause after failed cycles", "1")}
            {numField("retention_days", "Keep activity history (days)", "1")}
          </div>
          <div className="col-span-full flex items-center gap-2 pt-1">
            <Button size="sm" disabled={!Object.keys(d).length} onClick={() => run(() => serverApi("/v1/admin/evolution/settings", { method: "PUT", json: { changes: changes() } }).then(() => setD({})), "Settings saved.")}>Save settings</Button>
            {Object.keys(d).length > 0 && <Button size="sm" variant="ghost" onClick={() => setD({})}>Discard</Button>}
            {view}
          </div>
        </CardContent>
      </details>
    </Card>
  );
}
