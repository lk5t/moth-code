import { modelLabel } from "@/lib/model-label";
/**
 * Intelligence: how capable MOTH is and how it got there — the progress dashboard and the MOTH timeline.
 *
 * Every number is a measurement from MOTH Cloud (held-out benchmarks never trained on, recorded counts).
 * The only estimate shown — when the next training cycle starts — is labelled "estimated".
 */
import { useMemo, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Brain, Cpu, Database, GitBranch, Layers, Minus, Sparkles } from "lucide-react";
import { useCloudProgress } from "@/lib/cloud-progress";
import { useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { cn, formatNumber } from "@/lib/utils";

type Any = Record<string, any>;

const LABEL: Record<string, string> = {
  parameters: "Parameter count", training_steps: "Training steps", validation_loss: "Validation loss",
  math: "Maths (GSM8K)", reasoning: "Reasoning (ARC-Easy)", code: "Code (MBPP, executed)", instruction: "Instruction following",
  safety: "Safety", holdout_language: "Language (held-out loss)", holdout_conversation: "Conversation (held-out loss)",
  holdout_knowledge: "Knowledge (held-out loss)", holdout_writing: "Writing (held-out loss)", holdout_math: "Maths text (held-out loss)",
  holdout_reasoning: "Reasoning text (held-out loss)", holdout_code: "Code text (held-out loss)",
};
const METHOD: Record<string, string> = {
  foundation: "Foundation training", continued: "Continued training", expansion: "Parameter growth", upload: "Uploaded",
  network: "Training network", migration: "Architecture migration", from_scratch: "New architecture",
};
const fmt = (b: Any) => (b.higher_is_better ? `${(b.value * 100).toFixed(1)}%` : b.value.toFixed(3));
const when = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString() : "—");

function Stat({ icon, label, value, sub }: { icon: React.ReactNode; label: string; value: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-1 text-xs">
        <div className="flex items-center gap-2 text-muted [&_svg]:size-4">{icon}{label}</div>
        <div className="text-base font-semibold text-fg">{value}</div>
        {sub && <div className="text-muted">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function Change({ cur, prev }: { cur: Any; prev?: Any }) {
  if (!prev) return <span className="text-faint">first measurement</span>;
  const d = cur.value - prev.value;
  const better = cur.higher_is_better ? d > 1e-9 : d < -1e-9;
  const worse = cur.higher_is_better ? d < -1e-9 : d > 1e-9;
  const Icon = better ? ArrowUpRight : worse ? ArrowDownRight : Minus;
  return (
    <span className={cn("flex items-center gap-1", better ? "text-success" : worse ? "text-danger" : "text-faint")}>
      <Icon className="size-3.5" />{better ? "improved" : worse ? "regressed" : "unchanged"} ({fmt(prev)} before)
    </span>
  );
}

const EVENT: Record<string, string> = { "models.deployed": "Deployed", "models.rollback": "Rolled back", "evolution.rollback": "Rolled back automatically" };

/** One benchmark across model versions (measured points only). */
function TimelineChart({ versions, metric, onSelect }: { versions: Any[]; metric: string; onSelect?: (v: Any) => void }) {
  const pts = versions.map((v, i) => ({ i, v, b: v.benchmarks[metric] })).filter((p) => p.b);
  const W = 640, H = 180, pad = { l: 44, r: 16, t: 14, b: 30 };
  if (pts.length === 0) return <div className="py-6 text-center text-xs text-muted">Not measured yet.</div>;
  if (pts.length === 1) {  // one measurement is a fact, not a trend: state it instead of drawing an invented axis
    const only = pts[0];
    return <div className="py-4 text-center text-xs text-muted">{modelLabel(only.v)}: <span className="font-mono text-fg">{metric === "parameters" ? Math.round(only.b.value).toLocaleString() : fmt(only.b)}</span> {metric === "parameters" ? "parameters" : (LABEL[metric] ?? metric).toLowerCase()}. A chart appears once a second version has been measured.</div>;
  }
  const vals = pts.map((p) => p.b.value);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi - lo < 1e-6) { const m = Math.max(0.05, Math.abs(hi) * 0.1); hi += m; lo -= m; }  // one value: centre it
  const n = Math.max(1, versions.length - 1);
  const x = (i: number) => pad.l + (i / n) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const d = pts.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.b.value).toFixed(1)}`).join("");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${LABEL[metric] ?? metric} across model versions`}>
      {[0, 0.5, 1].map((f) => {
        const v = lo + f * (hi - lo);
        return (
          <g key={f}>
            <line x1={pad.l} x2={W - pad.r} y1={y(v)} y2={y(v)} className="stroke-border" strokeWidth={1} />
            <text x={pad.l - 6} y={y(v) + 3} textAnchor="end" className="fill-[var(--color-faint,#888)] text-[10px]">
              {metric === "parameters" ? formatNumber(Math.round(v)) : metric === "training_steps" ? v.toFixed(0)
                : pts[0].b.higher_is_better ? `${(v * 100).toFixed(0)}%` : v.toFixed(2)}
            </text>
          </g>
        );
      })}
      <path d={d} fill="none" className="stroke-accent" strokeWidth={2} />
      {pts.map((p) => (
        <g key={p.i} role="button" tabIndex={0} aria-label={`Inspect ${modelLabel(p.v)} ${LABEL[metric] ?? metric}`}
          onClick={() => onSelect?.(p.v)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect?.(p.v); } }} className="cursor-pointer">
          <title>{`${p.v.model_version ?? p.v.name}: ${fmt(p.b)}`}</title>
          <circle cx={x(p.i)} cy={y(p.b.value)} r={3.5} className="fill-accent" />
          <text x={x(p.i)} y={H - 10} textAnchor="middle" className="fill-[var(--color-muted,#999)] text-[10px]">
            {p.v.model_version ? `MOTH ${p.v.model_version}` : `v${p.v.version}`}
          </text>
        </g>
      ))}
    </svg>
  );
}

export function IntelligenceView({ embedded = false, focus = "all" }: { embedded?: boolean; focus?: "all" | "history" | "improvements" }) {
  const sessionToken = useAccount((s) => s.token);
  const signedIn = !!sessionToken;
  const {data:p,error:err} = useCloudProgress();
  const [metric, setMetric] = useState<string>("holdout_language");
  const [selection, setSelection] = useState<Any | null>(null);
  const versions: Any[] = p?.timeline ?? [];
  const chartVersions = useMemo(() => versions.map((v) => {
    const benchmarks = { ...v.benchmarks };
    const measured = { parameters: v.params, training_steps: v.lineage_totals?.steps ?? v.training?.step ?? v.training?.steps,
      validation_loss: v.training?.best_val ?? v.training?.val_loss };
    for (const [key, value] of Object.entries(measured)) {
      if (typeof value === "number" && Number.isFinite(value)) benchmarks[key] = { value, higher_is_better: false };
    }
    return { ...v, benchmarks };
  }), [p]);
  const metrics = useMemo(() => Array.from(new Set(chartVersions.flatMap((v) => Object.keys(v.benchmarks)))).sort(), [chartVersions]);
  const shown = metrics.includes(metric) ? metric : metrics[0] ?? metric;  // never chart a measurement this lineage does not have
  if (!signedIn) return <EmptyState title="Sign in to see MOTH's progress">The dashboard shows MOTH Cloud's measurements.</EmptyState>;
  if (err) return <EmptyState title="Progress is not available">{err}</EmptyState>;
  if (!p) return null;
  const cur = p.current;
  const prev = cur ? versions.find((v) => v.version === cur.parent) : null;
  const caps = cur ? Object.entries(cur.benchmarks as Record<string, Any>) : [];
  return (
    <div className={embedded ? "min-w-0" : "h-full overflow-auto"}>
      <div className={embedded ? "flex flex-col gap-5" : "mx-auto flex max-w-5xl flex-col gap-5 p-8 animate-rise"}>
        {!embedded && <div>
          <h1 className="text-lg font-semibold">Intelligence</h1>
          <p className="mt-1 text-xs text-muted">Recorded model sizes and training progress, with capabilities measured on held-out benchmarks MOTH never trained on.</p>
        </div>}
        {focus !== "improvements" && p.deployment_events?.length > 0 && <Card><CardHeader><CardTitle>Deployment history</CardTitle>
          <CardDescription>Recorded promotions and rollbacks</CardDescription></CardHeader>
          <CardContent><ol className="max-h-48 space-y-2 overflow-auto text-xs">
            {p.deployment_events.map((event: Any, index: number) => <li key={`${event.ts}-${index}`} className="flex flex-wrap gap-x-3 gap-y-1 border-l-2 border-accent pl-3">
              <time className="text-muted">{when(event.ts)}</time><span>{EVENT[event.action] ?? event.action.replaceAll('.', ' · ')}</span><span className="text-muted">{String(event.target ?? "").replace(/^release:/, "internal version ")}</span>
            </li>)}
          </ol></CardContent></Card>}
        {focus === "all" && <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat icon={<Brain />} label="Current model" value={cur ? (modelLabel(cur)) : "None yet"}
            sub={cur ? `${formatNumber(cur.params ?? 0)} parameters · ${METHOD[cur.method] ?? cur.method}` : "Nothing is deployed on MOTH Cloud"} />
          <Stat icon={<Sparkles />} label="Training" value={!p.training.enabled ? "off" : p.training.paused ? "paused" : p.training.cycle ? p.training.cycle.status.replaceAll("_", " ") : "waiting"}
            sub={<>{p.training.curriculum && `curriculum: ${p.training.curriculum}`}
              {p.training.next_cycle_at_estimate && <> · next cycle {when(p.training.next_cycle_at_estimate)} <i>(estimated)</i></>}</>} />
          <Stat icon={<Cpu />} label="Training network" value={`${p.network.workers_online} online`}
            sub={`${p.network.gpu_online} GPU · ${p.network.cpu_online} CPU · ${formatNumber(p.network.verified_tokens)} verified tokens`} />
          <Stat icon={<Layers />} label="Lineage" value={`${versions.length} version${versions.length === 1 ? "" : "s"}`}
            sub={cur?.lineage_totals ? `${formatNumber(cur.lineage_totals.tokens)} tokens trained since the foundation` : "one continuous model"} />
        </div>

        }
        {focus !== "history" && cur && (
          <Card>
            <CardHeader>
              <CardTitle>Capabilities of {modelLabel(cur)}</CardTitle>
              <CardDescription>Accuracy: higher is better. Held-out loss: lower is better (how well MOTH predicts unseen text of that kind).</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-1.5 text-xs">
              {caps.length === 0 && <div className="text-muted">Not measured yet — benchmarks run when a model is evaluated.</div>}
              {caps.map(([k, b]) => (
                <div key={k} className="flex flex-wrap items-center gap-3 border-b border-border pb-1.5 last:border-0">
                  <span className="w-56 text-fg">{LABEL[k] ?? k}</span>
                  <span className="w-20 font-mono">{fmt(b)}</span>
                  <Change cur={b} prev={prev?.benchmarks?.[k]} />
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {focus === "all" && <div className="grid gap-3 sm:grid-cols-2">
          <Stat icon={<GitBranch />} label="Stable model" value={p.stable ? (modelLabel(p.stable)) : "—"}
            sub={p.rollout?.length > 1 ? `staged rollout: ${p.rollout.map((r: Any) => `v${r.version} ${r.role}${r.percent ? ` ${r.percent}%` : ""}`).join(", ")}` : "serves everyone"} />
          <Stat icon={<GitBranch />} label="Development checkpoint" value={p.development ? `v${p.development.version}` : "—"}
            sub={p.development ? "full training state kept: the next cycle continues from here" : "created by the first training cycle"} />
        </div>

        }
        {focus !== "improvements" && <Card>
          <CardHeader>
            <CardTitle>MOTH timeline</CardTitle>
            <CardDescription>Every version of the one MOTH model, from its foundation onward. Points are measurements; nothing is interpolated.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 text-xs">
            {metrics.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {metrics.map((m) => (
                  <button key={m} aria-pressed={shown === m} onClick={() => setMetric(m)}
                    className={cn("cursor-pointer rounded-md border border-border px-2 py-0.5", shown === m ? "bg-surface-2 text-fg" : "text-muted hover:text-fg")}>
                    {LABEL[m] ?? m}
                  </button>
                ))}
              </div>
            )}
            <TimelineChart versions={chartVersions} metric={shown} onSelect={setSelection} />
            {selection && <div role="status" className="rounded-lg border border-border bg-bg p-3">
              <div className="font-medium">{modelLabel(selection)}</div>
              <div className="mt-1 text-muted">{formatNumber(selection.params)} parameters · {when(selection.created_at)}
                {selection.lineage_totals && ` · ${formatNumber(selection.lineage_totals.tokens)} recorded training tokens`}</div>
              <div className="mt-1 text-muted">{selection.benchmarks[metric] ? `${LABEL[metric] ?? metric}: ${fmt(selection.benchmarks[metric])}` : "This metric was not measured for this version."}</div>
            </div>}
            <ol className="flex flex-col gap-2">
              {[...versions].reverse().map((v) => (
                <li key={v.version} className="flex flex-col gap-0.5 border-l-2 border-border pl-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[13px] font-medium text-fg">{modelLabel(v)}</span>
                    <span className="text-faint">v{v.version}</span>
                    <Badge>{METHOD[v.method] ?? v.method}</Badge>
                    {v.deployed && <Badge variant="success">serving</Badge>}
                    {v.stable && !v.deployed && <Badge variant="success">stable</Badge>}
                    {v.status === "failed" && <Badge variant="danger">rejected or rolled back</Badge>}
                    <span className="text-muted">{when(v.created_at)}</span>
                  </div>
                  <div className="text-muted">
                    {v.params ? `${formatNumber(v.params)} parameters` : ""}
                    {v.growth ? ` · grown from ${formatNumber(v.growth.params_before)}` : ""}
                    {v.lineage_totals ? ` · ${formatNumber(v.lineage_totals.tokens)} tokens in total` : ""}
                    {v.architecture ? ` · ${v.architecture}` : ""}
                    {v.training?.best_val != null ? ` · validation loss ${v.training.best_val.toFixed(3)}` : ""}
                    {v.datasets?.length ? ` · data: ${v.datasets.map((d: Any) => d.sources ? d.sources.join(", ") : d.sha256).join("; ")}` : ""}
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>}

        {focus === "all" && p.datasets && (
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Database className="size-4 text-accent" />What MOTH learns from</CardTitle>
              <CardDescription>Approved, licensed datasets (dataset library build {p.datasets.build}).</CardDescription></CardHeader>
            <CardContent className="flex flex-col gap-1 text-xs">
              {p.datasets.sources.map((s: Any) => (
                <div key={s.id} className="flex flex-wrap gap-2"><span className="w-64 text-fg">{s.name}</span><span className="text-muted">{s.license}</span>
                  {s.records != null && <span className="text-faint">{formatNumber(s.records)} records</span>}</div>
              ))}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
