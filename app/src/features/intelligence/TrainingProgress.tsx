import { useEffect, useState } from "react";
import { Cpu, HardDrive, MemoryStick, Network } from "lucide-react";
import { MothEmblem } from "@/components/MothEmblem";
import { Card, CardContent } from "@/components/ui/card";
import { modelLabel } from "@/lib/model-label";

type Any = Record<string, any>;
const num = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const measured = (value: unknown, digits = 0) => num(value) ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : "Not reported";
const gb = (b: number) => `${(b / 1024 ** 3).toFixed(1)} GB`;
export function duration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.floor(s / 60)} min ${s % 60} s`;
  return `${Math.floor(s / 3600)} h ${Math.floor((s % 3600) / 60)} min`;
}

function LossHistory({ points }: { points: Any[] }) {
  const values = points.filter((p) => Number.isFinite(p.step) && Number.isFinite(p.loss));
  if (values.length < 2) return null;
  const low = Math.min(...values.map((p) => p.loss)), high = Math.max(...values.map((p) => p.loss));
  const first = Math.min(...values.map((p) => p.step)), last = Math.max(...values.map((p) => p.step));
  return <figure className="mt-3"><figcaption className="text-[11px] text-muted">Measured loss · training (red), validation (gray)</figcaption>
    <svg viewBox="0 0 600 90" role="img" aria-label={`Loss history from step ${first} to ${last}`} className="mt-1 h-24 w-full">
      {['train', 'val'].map((split) => <polyline key={split} fill="none" stroke={split === 'train' ? '#C1121F' : '#999'} strokeWidth="2"
        points={values.filter((p) => p.split === split).map((p) => `${5 + (p.step - first) / Math.max(1, last - first) * 590},${80 - (p.loss - low) / Math.max(.00001, high - low) * 70}`).join(' ')} />)}
      <text x="5" y="89" fontSize="8" fill="currentColor">Step {first} → {last} · loss {low.toFixed(3)}–{high.toFixed(3)}</text>
    </svg></figure>;
}

/** Live CPU, memory, GPU and worker measurements from MOTH Cloud (Owner only). */
function SystemStrip({ resources, network }: { resources: Any | null; network: Any | null }) {
  const local = resources?.local;
  const gpu = local?.gpus?.[0];
  const cells: [React.ReactNode, string, string][] = [];
  if (local) {
    cells.push([<Cpu key="c" />, "CPU", num(local.cpu_percent) ? `${local.cpu_percent.toFixed(0)}% of ${local.cpu_count} cores` : `${local.cpu_count} cores · load ${local.load_average?.[0] ?? "not measured"}`]);
    if (local.memory) cells.push([<MemoryStick key="m" />, "Memory", `${gb(local.memory.used)} of ${gb(local.memory.total)} in use`]);
    cells.push([<HardDrive key="g" />, gpu ? "GPU memory" : "GPU", gpu ? `${gb(gpu.memory_total - gpu.memory_free)} of ${gb(gpu.memory_total)} · ${gpu.name}` : "None on MOTH Cloud — CPU and worker training"]);
  }
  if (network) cells.push([<Network key="n" />, "Workers online", `${network.workers_online} (${network.gpu_online} GPU · ${network.cpu_online} CPU)`]);
  if (!cells.length) return null;
  return <dl aria-label="Compute right now" className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
    {cells.map(([icon, label, value]) => <div key={label} className="flex items-start gap-2 rounded-lg border border-border bg-bg px-3 py-2 text-xs [&_svg]:mt-0.5 [&_svg]:size-3.5 [&_svg]:shrink-0 [&_svg]:text-accent">
      {icon}<div className="min-w-0"><dt className="text-faint">{label}</dt><dd className="mt-0.5 truncate text-fg" title={value}>{value}</dd></div></div>)}
  </dl>;
}

function Experiment({ experiment, report, paused, nowSec }: { experiment: Any; report: Any; paused: boolean; nowSec: number }) {
  const step = report.step, max = report.max_steps ?? experiment.plan?.steps;
  const phase: string | undefined = report.phase ?? experiment.progress?.phase; // 0.9.0: reported by the worker
  const fraction = num(report.fraction) ? report.fraction : num(step) && max > 0 ? step / max : num(experiment.progress) ? experiment.progress : null;
  const pct = fraction != null && Number.isFinite(fraction) ? Math.max(0, Math.min(100, fraction * 100)) : null;
  const running = experiment.status === "running";
  const active = running && !paused && (step > 0 || (pct ?? 0) > 0);
  // 0.8.1: MOTH Cloud measures elapsed time itself (from when the compute actually took the work), so a
  // job that waited in the queue, or a viewer whose clock differs from the server's, never inflates it.
  const elapsed = num(experiment.elapsed_seconds) ? experiment.elapsed_seconds
    : running && num(experiment.started_at) ? Math.max(0, nowSec - experiment.started_at)
    : num(experiment.compute_seconds) && experiment.compute_seconds > 0 ? experiment.compute_seconds : null;
  // Remaining time only from measurements: the trainer's own estimate, or the measured step rate.
  const eta = num(report.eta_seconds) && report.eta_seconds > 0 ? report.eta_seconds
    : active && num(step) && step > 0 && num(max) && elapsed ? (max - step) * (elapsed / step) : null;
  const domains = Object.entries(experiment.data?.domains ?? {}).sort((a: any, b: any) => b[1] - a[1]).slice(0, 4);
  const improvement = experiment.metrics?.primary_improvement;
  const failedGates = (experiment.metrics?.gates ?? []).filter((g: Any) => !g.passed).map((g: Any) => g.gate);
  return <section aria-label={`Experiment ${experiment.id} progress`} className="rounded-lg border border-border bg-bg p-3">
    <div className="mb-2 flex flex-wrap items-center gap-2 text-xs"><MothEmblem motion={active ? "training" : "none"} className="size-5 shrink-0" />
      <span className="font-medium">Experiment #{experiment.id}</span>
      <span className="text-muted">{experiment.backend ? `${experiment.backend}${experiment.device ? ` · ${experiment.device}` : ""}${experiment.worker_id ? ` · worker ${experiment.worker_id}` : ""}` : "Compute not assigned yet"}</span>
      <span className="ml-auto text-muted">{paused && running ? "pausing" : experiment.status}</span>
    </div>
    {running && phase && phase !== "training" && <p className="mb-2 text-[11px] text-muted">The worker is {phase}…</p>}
    {pct != null ? <div role="progressbar" aria-label={`Experiment ${experiment.id} completion`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
      className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full bg-accent shadow-[0_0_8px_var(--color-accent)] transition-[width]" style={{ width: `${pct}%` }} /></div>
      : <p className="text-[11px] text-faint">{running ? "Starting — waiting for the first progress report" : "Waiting for compute"}</p>}
    <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
      <div><dt className="text-faint">Steps</dt><dd className="mt-0.5 font-mono">{measured(step)}{max != null && ` / ${measured(max)}`}</dd></div>
      <div><dt className="text-faint">Tokens processed</dt><dd className="mt-0.5 font-mono">{measured(report.tokens_seen ?? report.tokens)}</dd></div>
      <div><dt className="text-faint">Training loss</dt><dd className="mt-0.5 font-mono">{measured(report.train_loss, 4)}</dd></div>
      <div><dt className="text-faint">Validation loss</dt><dd className="mt-0.5 font-mono">{measured(report.val_loss ?? report.best_val, 4)}</dd></div>
      <div><dt className="text-faint">Speed</dt><dd className="mt-0.5 font-mono">{num(report.tokens_per_sec) ? `${measured(report.tokens_per_sec)} tok/s` : "Not reported"}</dd></div>
      <div><dt className="text-faint">Elapsed</dt><dd className="mt-0.5 font-mono">{elapsed != null ? duration(elapsed) : "Not started"}</dd></div>
      <div><dt className="text-faint">Remaining</dt><dd className="mt-0.5 font-mono">{eta != null ? `≈ ${duration(eta)}` : running ? "Estimating" : "—"}</dd></div>
      <div><dt className="text-faint">Checkpoint</dt><dd className="mt-0.5 truncate font-mono">{report.checkpoint?.name ? `step ${report.checkpoint.step}` : "None yet"}</dd></div>
    </dl>
    {(domains.length > 0 || experiment.plan?.lr) && <p className="mt-2 text-[11px] text-muted">
      {domains.length > 0 && <>Data: {experiment.data?.stage ? `${experiment.data.stage} stage · ` : ""}{domains.map(([d, w]: any) => `${d} ${Math.round(w * 100)}%`).join(", ")}</>}
      {experiment.plan?.lr && <>{domains.length ? " · " : ""}learning rate {Number(experiment.plan.lr).toExponential(1)} · batch {experiment.plan.batch_size}</>}</p>}
    <LossHistory points={report.history ?? []} />
    {num(improvement) && <p className={`mt-2 text-xs ${experiment.status === "passed" || experiment.status === "deployed" ? "text-success" : "text-muted"}`}>
      Evaluation on held-out data: {improvement >= 0 ? "+" : ""}{(improvement * 100).toFixed(2)}% — {experiment.status === "rejected" ? `kept the previous model${failedGates.length ? ` (failed: ${failedGates.join(", ")})` : ""}` : "passed every gate"}</p>}
    {experiment.rationale && <p className="mt-1 text-[11px] text-faint">Why: {experiment.rationale}</p>}
    {(experiment.error || report.error) && <p role="status" className="mt-2 text-xs text-warning">{experiment.error || report.error}</p>}
  </section>;
}

/** Counts come from trainer events or worker reports, never elapsed-time animation. */
export function TrainingProgress({ progress, resources }: { progress: Any | null; resources: Any | null }) {
  const [nowSec, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => { const t = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(t); }, []);
  const training = progress?.training;
  const state = !training ? "Loading training status" : !training.enabled ? "Training disabled"
    : training.paused ? "Paused" : training.cycle?.status?.replaceAll("_", " ") ?? "No active training cycle";
  const experiments: Any[] = training?.experiments ?? [];
  const running: Any[] = resources?.training?.running ?? [];
  const reportOf = (e: Any) => {
    const live = e.status === "running" ? running.find((r) => r.id === e.id) : undefined;
    return live?.progress && Object.keys(live.progress).length ? live.progress : e.measurement ?? {};
  };
  const ordered = [...experiments].sort((a, b) => (b.status === "running" ? 1 : 0) - (a.status === "running" ? 1 : 0) || b.id - a.id);
  const [focus, ...rest] = ordered;
  return <Card><CardContent className="space-y-3 p-3 sm:p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><h2 className="text-sm font-medium">Live training</h2>
        <p className="mt-0.5 text-xs text-muted">{progress?.current ? modelLabel(progress.current) : "MOTH"} · {state}{training?.curriculum ? ` · ${training.curriculum} curriculum` : ""}</p></div>
      <span className="text-[11px] text-faint">Measured by the trainer · updates every few seconds</span>
    </div>
    <SystemStrip resources={resources} network={progress?.network ?? null} />
    {training?.cycle?.waiting_reason && <p role="status" className="text-xs text-warning">{training.cycle.waiting_reason}</p>}
    {!focus && <p className="text-xs text-muted">No experiment in this cycle yet. When Evolution runs, the active training job appears here with its real measurements.</p>}
    {focus && <Experiment experiment={focus} report={reportOf(focus)} paused={!!training?.paused} nowSec={nowSec} />}
    {rest.length > 0 && <details className="text-xs"><summary className="cursor-pointer text-muted hover:text-fg">Other experiments in this cycle ({rest.length})</summary>
      <div className="mt-2 space-y-2">{rest.map((e) => <Experiment key={e.id} experiment={e} report={reportOf(e)} paused={!!training?.paused} nowSec={nowSec} />)}</div></details>}
  </CardContent></Card>;
}
