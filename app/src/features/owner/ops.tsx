/**
 * Owner Dashboard operations panels: Server, Updates, Models (with evaluation data) and Workers.
 * Every action goes through the authenticated MOTH Cloud API; sensitive ones ask for the
 * password again. There is no shell access from here.
 */
import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Cpu, Database, HardDrive, MemoryStick, RefreshCw, Server, Upload } from "lucide-react";
import { serverApi, withReauth } from "@/lib/account";
import { askPassword } from "@/features/account/reauth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { EmptyState } from "@/components/ui/empty";
import { formatNumber, timeAgo } from "@/lib/utils";
import { cn } from "@/lib/utils";

type Any = Record<string, any>;
export const secure = <T,>(fn: () => Promise<T>) => withReauth(fn, askPassword);

export function formatBytes(n?: number | null): string {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(v < 10 && i ? 1 : 0)} ${u[i]}`;
}

export function usePoll<T>(path: string, ms = 15000) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => serverApi<T>(path).then((d) => { setData(d); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, ms);
    return () => clearInterval(t);
  }, [path]);
  return { data, error, load };
}

export function useAction(after?: () => void) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await secure(fn);
      setMsg({ ok: true, text: ok });
      after?.();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };
  const view = msg ? <div className={cn("text-xs", msg.ok ? "text-success" : "text-danger")}>{msg.text}</div> : null;
  return { run, view };
}

const post = (path: string, json?: unknown) => serverApi(path, { method: "POST", json });

function Meter({ icon, label, pct, detail }: { icon: React.ReactNode; label: string; pct: number | null; detail: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 text-xs">
        <div className="flex items-center gap-2 text-muted [&_svg]:size-4">{icon}{label}</div>
        <div className="text-lg font-semibold">{pct == null ? "—" : `${pct.toFixed(0)}%`}</div>
        <Progress value={pct ?? 0} className={cn(pct != null && pct > 90 && "[&>div]:bg-danger")} />
        <div className="text-faint">{detail}</div>
      </CardContent>
    </Card>
  );
}

// ---- Server ------------------------------------------------------------------------------------
export function ServerPanel() {
  const { data: s, error } = usePoll<Any>("/v1/admin/system", 10000);
  if (error) return <EmptyState title="Server status unavailable">{error}</EmptyState>;
  if (!s) return null;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Badge variant="success"><CheckCircle2 className="size-3" /> API healthy</Badge>
        <span className="text-muted">MOTH Cloud {s.version} · {s.environment}</span>
        <span className="text-muted">· {s.active_users_15m} active user{s.active_users_15m === 1 ? "" : "s"} (15 min)</span>
        <span className="text-muted">· inference {s.inference.loaded ? `serving model v${s.inference.model_version}` : "no model loaded"}</span>
        <span className="text-muted">· {s.hardware.cuda ? s.hardware.gpus.map((g: Any) => g.name).join(", ") : `CPU only (${s.hardware.cpu_count} threads)`}</span>
      </div>
      <PublicAddress />
      <div className="grid grid-cols-3 gap-3">
        <Meter icon={<Cpu />} label="CPU" pct={s.cpu_percent} detail={s.load ? `load ${s.load.map((l: number) => l.toFixed(2)).join(" / ")}` : ""} />
        <Meter icon={<MemoryStick />} label="Memory" pct={s.memory?.percent ?? null}
          detail={s.memory ? `${formatBytes(s.memory.used)} of ${formatBytes(s.memory.total)} · server ${formatBytes(s.process_rss)}` : ""} />
        <Meter icon={<HardDrive />} label="Disk" pct={s.disk.percent} detail={`${formatBytes(s.disk.free)} free of ${formatBytes(s.disk.total)}`} />
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><AlertTriangle className="size-4 text-accent" />Recent errors</CardTitle>
          <CardDescription>{s.errors_24h} in the last 24 hours.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1 text-xs">
          {!s.recent_errors.length && <span className="text-muted">No errors recorded.</span>}
          {s.recent_errors.map((e: Any) => (
            <div key={e.id} className="flex gap-2 border-b border-border py-1 last:border-0">
              <span className="w-20 shrink-0 text-faint">{timeAgo(e.ts)}</span>
              <span className="selectable min-w-0 break-words">{e.message}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/** The address used in emails, referral links and worker install commands (no restart needed). */
function PublicAddress() {
  const { data, load } = usePoll<Any>("/v1/admin/overview", 60000);
  const [value, setValue] = useState("");
  const { run, view } = useAction(load);
  const current = data?.system?.public_url ?? "";
  useEffect(() => setValue(current), [current]);
  if (!data) return null;
  return (
    <Card>
      <CardContent className="flex flex-col gap-2 text-xs">
        <div className="text-muted">
          Public address — used in verification emails, referral links and worker install commands. Desktop updates
          always use the address the app is connected through.
          {data.system.public_url_env && data.system.public_url_env !== current ? ` (server setting: ${data.system.public_url_env})` : ""}
        </div>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(() => serverApi("/v1/admin/config/public-url", { method: "PUT", json: { url: value.trim() } }), "Public address saved."); }}>
          <Input className="h-8 flex-1 text-xs" value={value} onChange={(e) => setValue(e.target.value)} placeholder="https://moth.example.com" />
          <Button size="sm" variant="secondary" type="submit">Save</Button>
        </form>
        {view}
      </CardContent>
    </Card>
  );
}

// ---- Updates -----------------------------------------------------------------------------------
const depBadge = (s: string) => (s === "succeeded" ? "success" : s === "started" ? "accent" : s === "needs_approval" ? "warning" : "danger") as any;

export function UpdatesPanel() {
  const { data: u, load } = usePoll<Any>("/v1/admin/updates", 10000);
  const { run, view } = useAction(load);
  const [open, setOpen] = useState<number | null>(null);
  if (!u) return null;
  const agent = u.agent;
  const server = u.releases.filter((r: Any) => r.component === "server");
  const clients = u.releases.filter((r: Any) => r.component !== "server");
  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Server className="size-4 text-accent" />MOTH Cloud</CardTitle>
          <CardDescription>
            Version {u.server.version} · database schema {u.server.schema_version} · API {u.server.api_version}
            {!u.signing_configured && " · ⚠ no release signing key configured: updates are refused"}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            {agent ? (
              <>
                <Badge variant={agent.online ? "success" : "danger"}>{agent.online ? "update agent online" : "update agent not reporting"}</Badge>
                <span className="text-muted">{agent.message} · checked {timeAgo(agent.last_check)}{agent.previous ? ` · previous ${agent.previous}` : ""}</span>
              </>
            ) : <Badge variant="warning">update agent not installed (see docs/SERVER.md)</Badge>}
            {u.control.paused && <Badge variant="warning">updates paused</Badge>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/updates/server/check-now"), "The agent will check within a few seconds.")}><RefreshCw /> Check now</Button>
            {u.control.paused
              ? <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/updates/server/resume"), "Updates resumed.")}>Resume updates</Button>
              : <Button size="sm" variant="ghost" onClick={() => run(() => post("/v1/admin/updates/server/pause"), "Updates paused.")}>Pause updates</Button>}
            <Button size="sm" variant="ghost" disabled={!agent?.previous}
              onClick={() => confirm(`Roll MOTH Cloud back to ${agent?.previous}? The database is kept.`) && run(() => post("/v1/admin/updates/server/rollback"), "Rollback requested; the agent performs it within a minute.")}>
              Roll back to {agent?.previous ?? "previous"}
            </Button>
          </div>
          {u.pending_migrations.some((m: Any) => m.destructive) && (
            <div className="rounded border border-warning/40 bg-warning/10 p-2">
              {u.pending_migrations.filter((m: Any) => m.destructive).map((m: Any) => (
                <div key={m.version} className="flex items-center justify-between gap-2">
                  <span>Migration #{m.version}: {m.description} changes data irreversibly and needs your approval (a verified backup is taken first).</span>
                  <Button size="sm" onClick={() => run(() => post(`/v1/admin/updates/migrations/${m.version}/approve`), "Approved.")}>Approve</Button>
                </div>
              ))}
            </div>
          )}
          {view}
        </CardContent>
      </Card>
      <div className="grid grid-cols-2 gap-3">
        <Card>
          <CardHeader><CardTitle>Desktop and worker releases</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-xs">
            {!clients.length && <span className="text-muted">No releases published yet.</span>}
            {clients.map((r: Any) => (
              <div key={`${r.component}-${r.version}`} className="rounded border border-border p-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{r.component === "desktop" ? "MOTH Code" : "MOTH Worker"} {r.version}</span>
                  <Badge variant={r.status === "complete" ? "success" : r.status === "rolling_out" ? "accent" : r.status === "halted" ? "danger" : "default"}>
                    {r.status.replace("_", " ")}{r.status === "rolling_out" ? ` · ${r.rollout_percent}%` : ""}
                  </Badge>
                </div>
                <div className="mt-1 text-muted">{r.reports.succeeded} installed · {r.reports.failed} failed</div>
                <div className="mt-1 flex gap-1">
                  {["rolling_out", "complete"].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/admin/updates/releases/${r.component}/${r.version}/pause`), "Rollout paused.")}>Pause</Button>}
                  {["paused", "halted"].includes(r.status) && <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/admin/updates/releases/${r.component}/${r.version}/resume`), "Rollout resumed.")}>Resume</Button>}
                  {r.rollout_percent < 100 && r.status !== "withdrawn" && <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/admin/updates/releases/${r.component}/${r.version}/promote`), "Released to everyone.")}>Release to all</Button>}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Server releases</CardTitle></CardHeader>
          <CardContent className="space-y-1 text-xs">
            {!server.length && <span className="text-muted">None discovered yet.</span>}
            {server.map((r: Any) => (
              <div key={r.version} className="flex items-center justify-between border-b border-border py-1 last:border-0">
                <span>{r.version} <span className="text-faint">· {r.channel} · {timeAgo(r.created_at)}</span></span>
                <span className="flex items-center gap-1">
                  {r.version === u.server.version ? <Badge variant="success">running</Badge> : <Badge>{r.status}</Badge>}
                  {u.deployments.some((d: Any) => d.to_version === r.version && ["failed", "rolled_back"].includes(d.status)) && (
                    <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/admin/updates/server/retry/${r.version}`), "The agent will try again.")}>Retry</Button>
                  )}
                </span>
              </div>
            ))}
            <div className="pt-2 text-faint">Worker versions: {u.worker_versions.map((w: Any) => `${w.version ?? "unknown"} × ${w.n}`).join(", ") || "no workers"}</div>
          </CardContent>
        </Card>
      </div>
      <Card>
        <CardHeader><CardTitle>Deployment history</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-xs">
          {!u.deployments.length && <span className="text-muted">No deployments yet.</span>}
          {u.deployments.map((d: Any) => (
            <div key={d.id} className="border-b border-border py-1 last:border-0">
              <button className="flex w-full cursor-pointer items-center justify-between text-left" onClick={() => setOpen(open === d.id ? null : d.id)}>
                <span>{d.from_version ?? "?"} → {d.to_version} <span className="text-faint">· {timeAgo(d.started_at)}{d.step ? ` · ${d.step}` : ""}</span></span>
                <Badge variant={depBadge(d.status)}>{d.status.replace("_", " ")}</Badge>
              </button>
              {d.error && <div className="text-danger">{d.error}</div>}
              {open === d.id && <pre className="selectable mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-surface-2 p-2 text-[11px] text-muted">{d.log || "No log."}</pre>}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ---- Models --------------------------------------------------------------------------------------
const STATE_VARIANT: Record<string, any> = {
  deployed: "accent", published: "success", evaluated: "warning", failed: "danger", uploading: "default",
  uploaded: "default", evaluating: "default", deploying: "default",
};

function score(ev: Any | null): string {
  if (!ev?.score) return "";
  const s = ev.score;
  return s.metric === "bits_per_byte" ? `${s.value.toFixed(3)} bits/byte` : `loss ${s.value.toFixed(3)}`;
}

function EvalDatasets({ data, reload }: { data: Any; reload: () => void }) {
  const file = useRef<HTMLInputElement>(null);
  const [name, setName] = useState("");
  const [license, setLicense] = useState("");
  const { run, view } = useAction(reload);
  const upload = (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    fd.append("name", name || f.name);
    fd.append("license", license);
    fd.append("kind", "text");
    return run(() => serverApi("/v1/admin/eval-datasets", { method: "POST", body: fd, timeoutMs: 300000 }),
      "Dataset added. Releases waiting for evaluation data continue automatically.");
  };
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Database className="size-4 text-accent" />Evaluation data</CardTitle>
        <CardDescription>
          Every model is scored on held-out data before it can be published. Text datasets work for any MOTH model
          (scored in bits per byte with the model's own tokenizer). Upload text the models were <em>not</em> trained on.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        {!data.eval_ready && (
          <div className="rounded border border-warning/40 bg-warning/10 p-2 text-warning">
            No usable evaluation dataset yet — releases wait in "failed: no evaluation data" until you add one below.
          </div>
        )}
        {data.eval_datasets.map((d: Any) => (
          <div key={d.id} className="flex items-center justify-between gap-2 rounded border border-border px-2 py-1.5">
            <span className="min-w-0">
              <span className="font-medium">{d.name}</span>
              <span className="text-faint"> · {d.kind} · {d.source}{d.bytes ? ` · ${formatBytes(d.bytes)}` : d.tokens ? ` · ${formatNumber(d.tokens, 1)} tokens` : ""}{d.license ? ` · ${d.license}` : ""}</span>
              {!d.valid && <div className="text-danger">{d.problems.join("; ")}</div>}
              {d.note && <div className="text-faint">{d.note}</div>}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              {d.valid && (d.pinned
                ? <Button size="sm" variant="ghost" onClick={() => run(() => serverApi("/v1/admin/eval-datasets/pinned", { method: "PUT", json: { id: null } }), "Automatic selection restored.")}>Unpin</Button>
                : <Button size="sm" variant="ghost" onClick={() => run(() => serverApi("/v1/admin/eval-datasets/pinned", { method: "PUT", json: { id: d.id } }), `${d.name} will be used when compatible.`)}>Use</Button>)}
              {d.pinned && <Badge variant="accent">pinned</Badge>}
              {d.source === "uploaded" && <Button size="sm" variant="ghost" onClick={() => confirm(`Remove ${d.name}?`) && run(() => serverApi(`/v1/admin/eval-datasets/${d.id}`, { method: "DELETE" }), "Removed.")}>Remove</Button>}
            </span>
          </div>
        ))}
        <div className="flex items-center gap-2 pt-1">
          <Input className="h-7 text-xs" placeholder="Name (optional)" value={name} onChange={(e) => setName(e.target.value)} />
          <Input className="h-7 w-40 text-xs" placeholder="License (e.g. CC0-1.0)" value={license} onChange={(e) => setLicense(e.target.value)} />
          <input ref={file} type="file" accept=".txt,.md,.py,.js,.ts,.json,.jsonl,.rs,.go,.java,.c,.cpp,text/*" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
          <Button size="sm" variant="secondary" onClick={() => file.current?.click()}><Upload /> Upload text</Button>
        </div>
        {view}
      </CardContent>
    </Card>
  );
}

export function ModelsPanel() {
  const { data, load } = usePoll<Any>("/v1/admin/models", 5000);
  const { run, view } = useAction(load);
  if (!data) return null;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Button size="sm" variant="secondary" onClick={() => run(() => post("/v1/admin/models/sync"), "Checked for new network checkpoints and pending evaluations.")}>Check for new checkpoints</Button>
        <Button size="sm" variant="ghost" onClick={() => confirm("Roll back MOTH Cloud to the previously deployed model?") && run(() => post("/v1/admin/models/rollback"), "Rolled back.")}>Roll back model</Button>
        <span className="text-muted">Active model: {data.deployed ? `v${data.deployed}` : "none"} · inference on {data.hardware.cuda ? "GPU" : "CPU"}</span>
      </div>
      <div className="text-[11px] text-faint">Workflow: upload (Owner · model packages) → evaluate (automatic) → publish (automatic when every check passes) → deploy (you) → serving.</div>
      {!data.releases.length && <EmptyState title="No models yet">Publish one from Owner · model packages, or let the training network produce checkpoints.</EmptyState>}
      {data.releases.map((r: Any) => {
        const ev = r.evaluation;
        const failed = r.status === "failed";
        const regressed = r.status === "evaluated" && ev?.reason === "regression";
        return (
          <Card key={r.version} className={r.status === "deployed" ? "border-accent/50 shadow-glow" : ""}>
            <CardContent className="flex flex-col gap-1.5 text-xs">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2 text-[13px] font-medium">
                  v{r.version} · {r.name}
                  <Badge variant={STATE_VARIANT[r.status] ?? "default"}>{r.status}</Badge>
                  {r.previously_deployed && r.status !== "deployed" && <Badge>previously deployed</Badge>}
                </div>
                <div className="flex shrink-0 gap-1">
                  {(failed || ["uploaded", "evaluated", "published"].includes(r.status)) && r.path && ev?.reason !== "package_invalid" && (
                    <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/admin/models/${r.version}/evaluate`), `Evaluating v${r.version}…`)}>
                      {failed ? "Retry evaluation" : "Re-evaluate"}
                    </Button>
                  )}
                  {regressed && (
                    <Button size="sm" variant="secondary" onClick={() => confirm(`v${r.version} scored worse than the active model. Publish it anyway?`) && run(() => post(`/v1/admin/models/${r.version}/publish`, { override_regression: true }), `v${r.version} published.`)}>Publish anyway</Button>
                  )}
                  {r.status === "published" && (
                    <Button size="sm" onClick={() => confirm(`Deploy v${r.version} to MOTH Cloud for all users? The current model keeps serving if anything fails.`) && run(() => post(`/v1/admin/models/${r.version}/deploy`), `v${r.version} is now serving.`)}>Deploy</Button>
                  )}
                </div>
              </div>
              <div className="text-muted">
                {formatNumber(r.info.params, 1)} params · {formatBytes(r.size)} · {r.info.source?.type}
                {r.info.source?.checkpoint_version ? ` ckpt v${r.info.source.checkpoint_version}` : ""} · sha {r.sha256 ? r.sha256.slice(0, 10) : "—"}
                {ev?.score && ` · ${score(ev)} on ${ev.dataset?.name}`}
                {ev?.tokens_per_second ? ` · ${ev.tokens_per_second} tok/s` : ""}
                {ev?.peak_memory_bytes ? ` · eval memory ${formatBytes(ev.peak_memory_bytes)}` : ""}
                {r.info.serving ? ` · serving on ${r.info.serving.device}` : ""}
              </div>
              {r.error && <div className={cn(failed ? "text-danger" : "text-warning")}>{r.error}</div>}
              {ev?.guidance && <div className="text-muted">{ev.guidance}</div>}
              {ev?.note && <div className="text-faint">{ev.note}</div>}
              {ev?.samples && (
                <details className="text-faint">
                  <summary className="cursor-pointer">Evaluation details</summary>
                  <div className="mt-1 grid grid-cols-2 gap-1">
                    {Object.entries(ev.checks ?? {}).map(([k, v]) => <span key={k}>{v ? "✓" : "✗"} {k.replace(/_/g, " ")}</span>)}
                  </div>
                  {ev.samples.map((s: Any, i: number) => <pre key={i} className="selectable mt-1 whitespace-pre-wrap rounded bg-surface-2 p-1.5">{s.prompt}{s.output}</pre>)}
                </details>
              )}
            </CardContent>
          </Card>
        );
      })}
      {view}
      <EvalDatasets data={data} reload={load} />
    </div>
  );
}

// ---- Workers -------------------------------------------------------------------------------------
export function WorkersPanel() {
  const { data: workers, load } = usePoll<Any[]>("/v1/admin/workers", 15000);
  const { data: jobs } = usePoll<Any[]>("/v1/admin/jobs?limit=30", 15000);
  const { run, view } = useAction(load);
  if (!workers) return null;
  const gpu = workers.filter((w) => w.hardware.gpus?.length);
  const cpu = workers.filter((w) => !w.hardware.gpus?.length);
  const row = (w: Any) => (
    <div key={w.id} className="flex items-center justify-between rounded border border-border px-2.5 py-1.5">
      <span className="min-w-0 truncate">#{w.id} {w.name}
        <span className="text-faint"> @{w.owner} · {w.hardware.gpus?.map((g: Any) => `${g.name} ${g.memory_gb}GB`).join(", ") || `${w.hardware.cpu_count ?? "?"} CPU threads`} · v{w.version ?? "?"} · {w.verified_jobs}✓ {w.failed_jobs}✗{w.last_heartbeat_at ? ` · seen ${timeAgo(w.last_heartbeat_at)}` : ""}</span>
      </span>
      <span className="flex items-center gap-1">
        <Badge variant={w.status === "online" ? "success" : w.status === "revoked" ? "danger" : "default"}>{w.status}</Badge>
        {w.status !== "revoked" && <>
          <Button size="sm" variant="ghost" onClick={() => run(() => post("/v1/admin/evolution/training/start", { worker_id: w.id }), "Training requested; prerequisites and resource limits apply.")}>Start Training</Button>
          <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/training/workers/${w.id}/${w.paused ? "resume" : "pause"}`), w.paused ? "Worker resumed." : "Worker paused; checkpoint and lease retained.")}>{w.paused ? "Resume" : "Pause"}</Button>
          <Button size="sm" variant="ghost" onClick={() => run(() => post(`/v1/training/workers/${w.id}/stop`), "Worker stopped; job released and progress retained locally.")}>Stop</Button>
        </>}
        {w.status !== "revoked" && <Button size="sm" variant="ghost" onClick={() => confirm(`Revoke worker #${w.id}?`) && run(() => post(`/v1/training/workers/${w.id}/revoke`), "Worker revoked.")}>Revoke</Button>}
      </span>
    </div>
  );
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => run(() => post("/v1/admin/evolution/training/start", {}), "Compatible workers requested; training starts when prerequisites are ready.")}>Start All Compatible Workers</Button>
        <Button variant="outline" onClick={() => run(() => post("/v1/admin/evolution/training/start", { server_cpu: true }), "Server CPU training requested within configured limits.")}>Start Server CPU Training</Button>
        <Button variant="outline" onClick={() => run(() => post("/v1/admin/evolution/pause"), "Evolution paused.")}>Pause Training</Button>
        <Button variant="outline" onClick={() => run(() => post("/v1/admin/evolution/resume"), "Evolution resumed.")}>Resume Training</Button>
        <Button variant="outline" onClick={() => run(() => post("/v1/admin/evolution/cancel"), "Training cycle stopped; stable model retained.")}>Stop Training Cycle</Button>
      </div>
      <Card>
        <CardHeader><CardTitle>GPU workers ({gpu.filter((w) => w.status === "online").length} online / {gpu.length})</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-xs">{gpu.length ? gpu.map(row) : <span className="text-muted">None enrolled.</span>}</CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>CPU workers ({cpu.filter((w) => w.status === "online").length} online / {cpu.length})</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-xs">{cpu.length ? cpu.map(row) : <span className="text-muted">None enrolled.</span>}</CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Training jobs</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-xs">
          {!jobs?.length && <span className="text-muted">No training run is active.</span>}
          {jobs?.map((j) => (
            <div key={j.id} className="flex items-center justify-between gap-2 border-b border-border py-1 last:border-0">
              <span className="min-w-0 truncate">#{j.id} round {j.spec.round} {j.error && <span className="text-danger">· {String(j.error).slice(0, 90)}</span>}
                {(j.metrics?.progress || j.metrics?.training) && <span className="text-muted"> · {j.metrics.progress?.step ?? j.metrics.training?.steps ?? "Unavailable"} steps · {j.metrics.progress?.tokens ?? j.metrics.training?.tokens ?? "Unavailable"} tokens · loss {j.metrics.progress?.train_loss ?? j.metrics.training?.train_loss ?? "Unavailable"} · checkpoint step {j.metrics.progress?.checkpoint_step ?? "Unavailable"}</span>}
              </span>
              <span className="flex shrink-0 items-center gap-2 text-muted">
                {j.status === "leased" && j.progress != null && <Progress value={j.progress * 100} className="w-24" />}
                {j.status} · worker {j.worker_id ?? "—"} · {timeAgo(j.updated_at)}
              </span>
            </div>
          ))}
        </CardContent>
      </Card>
      {view}
    </div>
  );
}
