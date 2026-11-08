import { MothEmblem } from "@/components/MothEmblem";
import { Card, CardContent } from "@/components/ui/card";
import { modelLabel } from "@/lib/model-label";

type Any = Record<string, any>;
const measured = (value: unknown, digits = 0) => typeof value === "number" && Number.isFinite(value)
  ? value.toLocaleString(undefined, { maximumFractionDigits: digits }) : "Not reported";

/** Counts come from trainer events or worker reports, never elapsed-time animation. */
export function TrainingProgress({ progress, resources }: { progress: Any | null; resources: Any | null }) {
  const training = progress?.training;
  const state = !training ? "Loading training status" : !training.enabled ? "Training disabled"
    : training.paused ? "Paused by the Owner" : training.cycle?.status?.replaceAll("_", " ") ?? "No active training cycle";
  const experiments: Any[] = training?.experiments ?? [];
  const running: Any[] = resources?.training?.running ?? [];
  return <Card><CardContent className="space-y-3 p-3 sm:p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div><h2 className="text-sm font-medium">Live training progress</h2>
        <p className="mt-0.5 text-xs text-muted">{progress?.current ? modelLabel(progress.current) : "MOTH"} · {state}</p></div>
      <span className="text-[11px] text-faint">Updates from real trainer reports</span>
    </div>
    {training?.cycle?.waiting_reason && <p role="status" className="text-xs text-warning">{training.cycle.waiting_reason}</p>}
    {!experiments.length && <p className="text-xs text-muted">No experiment has reported progress yet. Start or resume training below.</p>}
    {experiments.map((experiment) => {
      const live = experiment.status === "running" ? running.find((r) => r.id === experiment.id) : undefined;
      const report = live?.progress && Object.keys(live.progress).length ? live.progress : experiment.measurement ?? {};
      const step = report.step;
      const max = report.max_steps ?? live?.config?.steps;
      const fraction = typeof report.fraction === "number" ? report.fraction : typeof step === "number" && max > 0
        ? step / max : typeof experiment.progress === "number" ? experiment.progress : null;
      const pct = fraction != null && Number.isFinite(fraction) ? Math.max(0, Math.min(100, fraction * 100)) : null;
      const active = experiment.status === "running" && !training.paused && (step > 0 || (pct ?? 0) > 0);
      return <section key={experiment.id} aria-label={`Experiment ${experiment.id} progress`} className="rounded-lg border border-border bg-bg p-3">
        <div className="mb-2 flex items-center gap-2 text-xs"><MothEmblem motion={active ? "working" : "none"} className="size-5 shrink-0" />
          <span className="font-medium">Experiment #{experiment.id}</span>
          <span className="text-muted">{experiment.backend ?? "Compute not assigned"}{experiment.device ? ` · ${experiment.device}` : ""}</span>
          <span className="ml-auto text-muted">{training.paused && experiment.status === "running" ? "pausing" : experiment.status}</span>
        </div>
        {pct != null ? <div role="progressbar" aria-label={`Experiment ${experiment.id} completion`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}
          className="h-1.5 overflow-hidden rounded-full bg-surface-3"><div className="h-full bg-accent transition-[width]" style={{ width: `${pct}%` }} /></div>
          : <p className="text-[11px] text-faint">Waiting for a progress report</p>}
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
          <div><dt className="text-faint">Steps</dt><dd className="mt-0.5 font-mono">{measured(step)}{max != null && ` / ${measured(max)}`}</dd></div>
          <div><dt className="text-faint">Tokens processed</dt><dd className="mt-0.5 font-mono">{measured(report.tokens_seen ?? report.tokens)}</dd></div>
          <div><dt className="text-faint">Training loss</dt><dd className="mt-0.5 font-mono">{measured(report.train_loss, 4)}</dd></div>
          <div><dt className="text-faint">Validation loss</dt><dd className="mt-0.5 font-mono">{measured(report.val_loss ?? report.best_val, 4)}</dd></div>
        </dl>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
          {report.tokens_per_sec != null && <span>{measured(report.tokens_per_sec)} tokens/s</span>}
          <span>Checkpoint: {report.checkpoint?.name ? `${report.checkpoint.name} · step ${report.checkpoint.step}` : "Not reported yet"}</span>
          {pct != null && <span className="ml-auto">{pct.toFixed(1)}%</span>}
        </div>
        {(experiment.error || report.error) && <p role="status" className="mt-2 text-xs text-warning">{experiment.error || report.error}</p>}
      </section>;
    })}
  </CardContent></Card>;
}
