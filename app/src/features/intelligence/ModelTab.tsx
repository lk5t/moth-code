/**
 * AI → Model (0.7.1): the one place to understand the active MOTH model and its lifecycle.
 *
 * Everything shown is a measurement from MOTH Cloud's progress report: the saved weights' parameter
 * count, the architecture from the model's configuration, held-out benchmark results, the checkpoint
 * and the deployment. The core visual draws one ring per decoder layer (grouped above 12) split into
 * one segment per attention head — the real shape of the model, not simulated neurons. It turns only
 * while training is running and pulses when reported training steps increase.
 */
import { useEffect, useRef, useState } from "react";
import { History, RotateCcw, ShieldCheck } from "lucide-react";
import { refreshCloudProgress } from "@/lib/cloud-progress";
import { serverApi, useAccount } from "@/lib/account";
import { modelLabel } from "@/lib/model-label";
import { paramsLabel } from "@/lib/params";
import { secure } from "@/features/owner/ops";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { LoadingBlock } from "@/components/ui/skeleton";
import { MothEmblem } from "@/components/MothEmblem";
import { cn } from "@/lib/utils";

type Any = Record<string, any>;

const CAPABILITY: Record<string, string> = {
  conversation: "Language & conversation", writing: "Writing", knowledge: "Knowledge", reasoning: "Reasoning",
  math: "Arithmetic", code: "Coding", instruction: "Instruction following", safety: "Safety",
  dialogue: "Conversation (multi-turn)", codegen: "Code generation (executed)", debugging: "Debugging (executed)",
};
/** 0.8.0 priorities: conversation and coding first, then the other foundations. */
export const PRIORITY = ["dialogue", "holdout_conversation", "codegen", "debugging", "code", "holdout_code", "instruction",
  "reasoning", "math", "knowledge", "holdout_knowledge", "holdout_reasoning", "holdout_math", "holdout_language",
  "holdout_writing", "safety"];
const rank = (k: string) => { const i = PRIORITY.indexOf(k); return i < 0 ? 99 : i; };
export const capabilityLabel = (key: string) =>
  CAPABILITY[key] ?? (key.startsWith("holdout_") ? `Held-out ${key.slice(8).replaceAll("_", " ")}` : key.replaceAll("_", " "));

/** Rates (accuracy, pass rate …) are 0–1 values shown as percentages; losses and the like are not. */
export function isRate(b: Any | undefined): boolean {
  return !!b && typeof b.value === "number" && !/loss|perplexity|bpb|bits/i.test(String(b.metric ?? "")) && b.value >= 0 && b.value <= 1;
}

/** A benchmark value as people read it: rates as percentages, losses as numbers. */
export function benchmarkValue(b: Any | undefined): string {
  if (!b || typeof b.value !== "number" || !Number.isFinite(b.value)) return "—";
  const metric = String(b.metric ?? "");
  if (!isRate(b)) return `${b.value.toFixed(3)}${metric ? ` ${metric.replaceAll("_", " ")}` : ""}`;
  return `${(b.value * 100).toFixed(1)}%`;
}

/** A change shown in the benchmark's own unit: percentage points for rates, the raw amount otherwise. */
export function changeLabel(b: Any, change: number): string {
  const mag = Math.abs(change);
  return isRate(b) ? `${(mag * 100).toFixed(1)} pts` : mag.toFixed(3);
}

/** Change from the rollback model, signed so that positive always means better. */
export function benchmarkChange(cur: Any | undefined, prev: Any | undefined): number | null {
  if (!cur || !prev || typeof cur.value !== "number" || typeof prev.value !== "number") return null;
  const d = cur.value - prev.value;
  return cur.higher_is_better === false ? -d : d;
}

function stepOf(p: Any | null): number {
  return (p?.training?.experiments ?? []).reduce((n: number, e: Any) => n + Number(e?.measurement?.step ?? e?.progress?.step ?? 0), 0);
}

export function ModelCore({ config, training, pulse, label }: { config: Any | undefined; training: boolean; pulse: boolean; label: string }) {
  const layers = Math.max(0, Number(config?.n_layers ?? 0));
  const heads = Math.max(1, Math.min(32, Number(config?.n_heads ?? 1)));
  const rings = Math.min(layers, 12);
  const r0 = 62, r1 = 138;
  const desc = layers ? `${label}: ${layers} decoder layers${layers > 12 ? " (drawn as 12 groups)" : ""}, ${config?.n_heads ?? "?"} attention heads per layer, ${config?.d_model ?? "?"} dimensions.` : `${label}: architecture not reported.`;
  return <svg viewBox="0 0 320 320" className={cn("mx-auto w-full max-w-[320px]", pulse && "animate-pulse-glow")} role="img" aria-label={desc}>
    <defs>
      <radialGradient id="moth-core" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stopColor="var(--color-accent)" stopOpacity="0.55" />
        <stop offset="70%" stopColor="var(--color-accent)" stopOpacity="0.12" />
        <stop offset="100%" stopColor="var(--color-accent)" stopOpacity="0" />
      </radialGradient>
    </defs>
    <circle cx="160" cy="160" r="150" fill="url(#moth-core)" />
    <g className={cn("origin-center", training && "model-core-spin")} style={{ transformOrigin: "160px 160px" }}>
      {Array.from({ length: rings }, (_, i) => {
        const r = rings === 1 ? (r0 + r1) / 2 : r0 + (r1 - r0) * i / (rings - 1);
        const circ = 2 * Math.PI * r, seg = circ / heads, gap = Math.min(6, seg * 0.25);
        return <circle key={i} cx="160" cy="160" r={r} fill="none" stroke="var(--color-accent)"
          strokeOpacity={0.25 + 0.6 * (i + 1) / rings} strokeWidth={i === rings - 1 ? 2.2 : 1.4}
          strokeDasharray={`${seg - gap} ${gap}`} transform={`rotate(${i * 9} 160 160)`} />;
      })}
    </g>
    <circle cx="160" cy="160" r="46" fill="var(--color-bg)" stroke="var(--color-accent)" strokeOpacity="0.6" />
  </svg>;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="min-w-0"><p className="text-[11px] text-faint">{label}</p><div className="mt-0.5 truncate text-xs text-fg">{children}</div></div>;
}

export function ModelTab({ progress }: { progress: Any | null }) {
  const owner = useAccount((s) => s.user?.role === "owner");
  const p = progress;
  const cur = p?.current;
  const step = stepOf(p);
  const prevStep = useRef<number | null>(null);
  const [pulse, setPulse] = useState(false);
  useEffect(() => {
    const grew = prevStep.current !== null && step > prevStep.current;
    prevStep.current = step;
    if (!grew) return;
    setPulse(true);
    const t = setTimeout(() => setPulse(false), 4000);
    return () => clearTimeout(t);
  }, [step]);
  const [confirm, setConfirm] = useState(false), [busy, setBusy] = useState(false), [msg, setMsg] = useState<string | null>(null);
  if (!p) return <Card><CardContent className="p-6"><LoadingBlock label="Loading the active model…" lines={4} /></CardContent></Card>;
  if (!cur) return <EmptyState title="No active MOTH model yet">Start Evolution in AI → Evolution. The first model is MOTH 0.0.1.</EmptyState>;
  const timeline: Any[] = p.timeline ?? [];
  const life = p.lifecycle ?? {};
  const rollback = timeline.find((v) => v.version === life.rollback);
  const running = (p.training?.experiments ?? []).some((e: Any) => e.status === "running");
  const cycle = p.training?.cycle;
  const status = p.training?.paused ? "Paused by the Owner" : running ? "Training a candidate" : cycle ? cycle.status.replaceAll("_", " ") : "Waiting for the next round";
  const name = modelLabel(cur);
  const cfg = cur.config ?? {};
  const benches = (Object.entries(cur.benchmarks ?? {}) as [string, Any][]).sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b));
  const perf = cur.performance;
  const roll = async () => {
    if (!rollback) return;
    setBusy(true); setMsg(null);
    try { await secure(() => serverApi("/v1/admin/evolution/rollback", { method: "POST", json: { version: rollback.version } })); setMsg(`${modelLabel(rollback)} is active again.`); refreshCloudProgress(); }
    catch (e) { setMsg((e as Error).message); } finally { setBusy(false); setConfirm(false); }
  };
  return <div className="flex flex-col gap-3 animate-fade-in">
    <Card className="overflow-hidden border-accent/30 bg-[radial-gradient(ellipse_at_top,rgb(193_18_31/0.10),transparent_60%)]">
      <CardContent className="grid gap-4 p-4 sm:grid-cols-[minmax(240px,320px)_1fr] sm:p-6">
        <div className="relative flex items-center justify-center">
          <ModelCore config={cfg} training={running} pulse={pulse} label={name} />
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
            <MothEmblem className={cn("size-12", running && "motion-safe:animate-pulse")} />
          </div>
        </div>
        <div className="flex min-w-0 flex-col justify-center gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.2em] text-faint">Active model</p>
            <h2 className="mt-1 text-3xl font-medium tracking-tight">{name}</h2>
            <p className="mt-1 text-xs text-muted">{paramsLabel(cur.params, cur.params_verified)}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
              <Badge variant={p.serving?.accepting_requests ? "success" : "default"}>{p.serving?.reason ?? "Deployment status unavailable"}</Badge>
              <span className="flex items-center gap-1.5 text-muted"><span className={cn("size-1.5 rounded-full", running ? "bg-accent motion-safe:animate-pulse" : "bg-faint")} />{status}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Fact label="Architecture">{cfg.n_layers ? `${cfg.n_layers} layers · ${cfg.d_model} dimensions` : "Not reported"}</Fact>
            <Fact label="Attention heads">{cfg.n_heads ? `${cfg.n_heads} per layer` : "Not reported"}</Fact>
            <Fact label="Vocabulary">{cfg.vocab_size ? cfg.vocab_size.toLocaleString() : "Not reported"}</Fact>
            <Fact label="Latest checkpoint">{p.checkpoint ? p.checkpoint.available ? `Step ${p.checkpoint.step ?? "not recorded"}` : "Recorded checkpoint is missing" : "Not recorded"}</Fact>
            <Fact label="Deployed">{cur.deployed_at ? new Date(cur.deployed_at * 1000).toLocaleString() : "Not recorded"}</Fact>
            <Fact label="Revision">{cur.revision ?? "Not recorded"}</Fact>
            <Fact label="Internal identifier"><span className="font-mono" title={cur.model_id ?? cur.name}>{cur.model_id ?? cur.name ?? `v${cur.version}`}</span></Fact>
            <Fact label="Tokenizer identity"><span className="font-mono" title={cur.tokenizer_fingerprint}>{cur.tokenizer_fingerprint ?? "Not recorded"}</span></Fact>
            <Fact label="Lineage">{timeline.length} measured version{timeline.length === 1 ? "" : "s"} · release v{cur.version}</Fact>
            {perf && <Fact label="Serving speed">{perf.tokens_per_second} tokens/s · {perf.threads} thread{perf.threads === 1 ? "" : "s"}{perf.tuned ? " (tuned)" : ""}</Fact>}
            {perf?.load_seconds != null && <Fact label="Load time">{perf.load_seconds.toFixed(2)} s</Fact>}
          </div>
          {p.improvement?.verified && <p className="flex items-center gap-1.5 text-xs text-success"><ShieldCheck className="size-3.5" />Verified improvement: held-out score {(p.improvement.primary_improvement * 100).toFixed(2)}% better than its parent, every gate passed.</p>}
        </div>
      </CardContent>
    </Card>

    <Card aria-label="Capability benchmarks"><CardContent className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-medium">Capabilities</h3>
        <span className="text-[11px] text-faint">Held-out benchmarks of {name}{rollback ? `, compared with ${modelLabel(rollback)}` : ""}</span></div>
      {benches.length ? <ul className="mt-3 grid gap-2 sm:grid-cols-2">{benches.map(([k, b]) => {
        const prev = rollback?.benchmarks?.[k];
        const change = benchmarkChange(b, prev);
        const pct = isRate(b) && b.higher_is_better !== false ? b.value * 100 : null;
        return <li key={k} className="rounded-lg border border-border bg-bg/60 p-2.5">
          <div className="flex items-center justify-between gap-2 text-xs"><span className="text-fg">{capabilityLabel(k)}</span>
            <span className="tabular-nums text-muted">{benchmarkValue(b)}{change != null && <span className={cn("ml-1.5", change > 0 ? "text-success" : change < 0 ? "text-danger" : "text-faint")}><span className="sr-only">{change > 0 ? "better by" : change < 0 ? "worse by" : "unchanged"}</span>{change > 0 ? "▲" : change < 0 ? "▼" : "="} {changeLabel(b, change)}</span>}</span></div>
          {pct != null && <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-2"><div className="h-full rounded-full bg-accent transition-[width] duration-700" style={{ width: `${Math.max(2, pct)}%` }} /></div>}
        </li>;
      })}</ul> : <p className="mt-2 text-xs text-muted">No benchmark results are recorded for this version yet. They appear after its first evaluation.</p>}
    </CardContent></Card>

    <BenchmarkHistory timeline={timeline} />

    <Card aria-label="Model lifecycle"><CardContent className="flex flex-col gap-3 p-4 text-xs">
      <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-medium">Lifecycle</h3>
        <span className="text-faint">One active model and one rollback model keep their weights. Older versions keep their measurements only.</span></div>
      <div className="grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-accent/40 bg-accent-soft p-3"><p className="text-faint">Active</p><p className="mt-0.5 text-sm text-fg">{name}</p><p className="text-muted">Serving users · release v{cur.version}</p></div>
        <div className="rounded-lg border border-border p-3"><p className="text-faint">Rollback</p>
          {rollback ? <><p className="mt-0.5 text-sm text-fg">{modelLabel(rollback)}</p><p className="text-muted">Previous working version · weights kept</p>
            {owner && <div className="mt-2 flex items-center gap-2">
              {!confirm ? <Button size="sm" variant="outline" disabled={busy} onClick={() => setConfirm(true)}><RotateCcw />Roll back</Button>
                : <><Button size="sm" disabled={busy} onClick={() => void roll()}>{busy ? "Rolling back…" : `Make ${modelLabel(rollback)} active`}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button></>}
            </div>}</> : <p className="mt-0.5 text-muted">None yet. After the next verified upgrade, {name} becomes the rollback model.</p>}
        </div>
      </div>
      {msg && <p role="status" className="text-muted">{msg}</p>}
      {timeline.length > 1 && <details className="rounded-lg border border-border">
        <summary className="flex cursor-pointer items-center gap-2 p-2.5 text-muted"><History className="size-3.5" />Version history ({timeline.length})</summary>
        <ul className="divide-y divide-border border-t border-border">{[...timeline].reverse().map((v) => <li key={v.version} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
          <span className="text-fg">{modelLabel(v)}{v.deployed && <Badge variant="accent" className="ml-2">active</Badge>}{v.version === life.rollback && <Badge className="ml-2">rollback</Badge>}</span>
          <span className="text-faint">{v.params != null ? `${Number(v.params).toLocaleString()} parameters · ` : ""}{v.retained ? "weights kept" : "measurements only"}{v.deployed_at ? ` · ${new Date(v.deployed_at * 1000).toLocaleDateString()}` : ""}</span>
        </li>)}</ul>
      </details>}
    </CardContent></Card>
  </div>;
}


/** Benchmarks of every promoted MOTH version side by side, with the change from the previous one (0.8.0). */
export function BenchmarkHistory({ timeline }: { timeline: Any[] }) {
  const versions = timeline.filter((v) => v.model_version && Object.keys(v.benchmarks ?? {}).length).slice(-5);
  if (versions.length < 1) return null;
  const caps = [...new Set(versions.flatMap((v) => Object.keys(v.benchmarks)))].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  const date = (v: Any) => {
    const ts = Math.max(0, ...(Object.values(v.benchmarks ?? {}) as Any[]).map((b) => Number(b.evaluated_at) || 0));
    return ts ? new Date(ts * 1000).toLocaleDateString() : "—";
  };
  return <Card aria-label="Benchmark history"><CardContent className="p-4">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 className="text-sm font-medium">Benchmark history</h3>
      <span className="text-[11px] text-faint">Held-out benchmarks of each promoted version; ▲ better, ▼ worse than the version before</span></div>
    <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[480px] text-xs">
      <thead><tr className="text-left text-faint"><th className="py-1 pr-3 font-normal">Capability</th>
        {versions.map((v) => <th key={v.version} className="px-2 py-1 text-right font-normal"><div className="text-fg">{modelLabel(v)}</div><div>{date(v)}</div></th>)}</tr></thead>
      <tbody>{caps.map((k) => <tr key={k} className="border-t border-border">
        <td className="py-1.5 pr-3 text-fg">{capabilityLabel(k)}</td>
        {versions.map((v, i) => {
          const b = v.benchmarks[k];
          const ch = i > 0 ? benchmarkChange(b, versions[i - 1].benchmarks[k]) : null;
          return <td key={v.version} className="px-2 py-1.5 text-right tabular-nums text-muted">{benchmarkValue(b)}
            {ch != null && Math.abs(ch) > 1e-9 && <span className={cn("ml-1", ch > 0 ? "text-success" : "text-danger")}>{ch > 0 ? "▲" : "▼"}</span>}</td>;
        })}
      </tr>)}</tbody>
    </table></div>
  </CardContent></Card>;
}
