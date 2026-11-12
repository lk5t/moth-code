import { modelLabel } from "@/lib/model-label";
import { useState } from "react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { formatBytes, useAction, usePoll } from "./ops";
import { serverApi } from "@/lib/account";
import { paramsLabel } from "@/lib/params";

type Any = Record<string, any>;
const number = (n: number | null | undefined) => n == null ? "Unavailable" : n.toLocaleString(undefined, { maximumFractionDigits: 6 });
const bytes = (n: number | null | undefined) => n == null ? "Unavailable" : formatBytes(n);
const date = (n: number | null | undefined) => n == null ? "Unavailable" : new Date(n * 1000).toLocaleString();

export function ModelOverview() {
  const { data, error, load } = usePoll<Any>("/v1/admin/model-overview", 10000);
  const { run, view } = useAction(load);
  const [compare, setCompare] = useState<number | null>(null);
  if (!data) return <p className="text-muted">{error ?? "Loading MOTH measurements…"}</p>;
  const model = data.model;
  if (!model) return <Card><CardHeader><CardTitle>MOTH AI</CardTitle><CardDescription>No native model is registered. Initialization creates an untrained 99,648-parameter MOTH 0.0.1. Existing weights must be imported and preserved.</CardDescription></CardHeader>
    <CardContent><Button onClick={() => run(() => serverApi("/v1/admin/evolution/initialize", { method: "POST" }), "MOTH 0.0.1 initialized. Evaluate the checkpoint in Model registry before deployment.")}>Initialize MOTH 0.0.1</Button>{view}</CardContent></Card>;
  const versions: Any[] = data.accepted_versions ?? [];
  const previous = versions.find(v => v.release === compare) ?? versions.at(-2);
  const comparable = previous && model.evaluation?.dataset?.sha256 &&
    model.evaluation.dataset.sha256 === previous.evaluation?.dataset?.sha256 &&
    model.evaluation.score?.metric === previous.evaluation?.score?.metric;
  const progress = data.training?.progress;
  const train = model.training ?? {};
  const gates: Any[] = data.evaluation?.gates ?? [];
  const stats: [string, React.ReactNode][] = [
    ["Parameters", paramsLabel(model.params, model.params_verified)], ["Model version", model.model_version ?? "Unavailable"],
    ["Architecture", model.architecture ?? "Unavailable"], ["Checkpoint size", bytes(data.checkpoint?.bytes)],
    ["Total training steps", number(model.totals?.steps)], ["Total training tokens", number(model.totals?.tokens)],
    ["Training loss", number(progress?.train_loss ?? train.train_loss)],
    ["Validation loss", number(train.val_loss ?? train.best_val)],
    ["Active CPU / GPU workers", `${number(data.workers?.active_cpu)} / ${number(data.workers?.active_gpu)}`],
    ["Current step", number(progress?.step)], ["Current run tokens", number(progress?.tokens_seen ?? progress?.tokens)],
    ["Current training status", data.training?.status ?? "Unavailable"],
  ];
  return <div className="flex flex-col gap-4">
    <Card><CardHeader><CardTitle>{modelLabel(model)}</CardTitle><CardDescription>Release #{model.release} · {model.status}{train.step === 0 ? " · Untrained initial checkpoint" : ""}</CardDescription></CardHeader>
      <CardContent><div className="grid grid-cols-2 gap-3 lg:grid-cols-3">{stats.map(([label, value]) => <div key={label} className="rounded border border-border p-3"><div className="text-xs text-muted">{label}</div><div className="break-words font-mono text-sm">{value}</div></div>)}</div>
        {model.source_type === "native-initialization" && model.status !== "deployed" && <div className="mt-3 space-y-2"><p className="text-xs text-muted">This is an untrained baseline. Activation runs real evaluation and a serving health check; it does not establish useful AI capability.</p><Button onClick={() => run(() => serverApi("/v1/admin/evolution/initialize/activate", { method: "POST" }), "Initial baseline evaluated and activated. Enable server CPU or compatible workers in Network to train.")}>Evaluate & activate initial baseline</Button></div>}
        {progress?.fraction != null && <div className="mt-3"><Progress value={progress.fraction * 100} /><span className="text-xs text-muted">{(progress.fraction * 100).toFixed(1)}% of the current experiment</span></div>}
        <details className="mt-3 text-xs"><summary className="cursor-pointer text-muted">Architecture and checkpoint details</summary>
          <pre className="mt-2 overflow-auto">{model.config ? JSON.stringify(model.config, null, 2) : "Unavailable"}</pre>
          <p>Latest valid checkpoint: {data.checkpoint ? `${data.checkpoint.kind} · ${data.checkpoint.sha256}` : "Unavailable"}</p>
          {data.development_checkpoint?.valid === false && <p className="text-danger">Development checkpoint failed integrity verification.</p>}
        </details>
      </CardContent></Card>
    <Card><CardHeader><CardTitle>Evaluation and knowledge retention</CardTitle><CardDescription>Recorded promotion gates; every retained capability must pass before an upgrade.</CardDescription></CardHeader>
      <CardContent className="space-y-2 text-xs">{gates.length ? gates.map((g, i) => <div key={`${g.gate}-${i}`} className="border-b border-border pb-1"><span className={g.passed ? "text-success" : "text-danger"}>{g.passed ? "Passed" : "Failed"}</span> · {g.gate} · {g.detail ?? "Unavailable"}</div>) : <p className="text-muted">Unavailable</p>}</CardContent></Card>
    <Card><CardHeader><CardTitle>Accepted MOTH versions</CardTitle><CardDescription>One lineage. Prior checkpoints remain available for rollback.</CardDescription></CardHeader><CardContent className="overflow-auto text-xs">
      {versions.length ? <table className="w-full text-left"><thead><tr>{["MOTH", "Parameters", "Steps", "Loss", "Architecture change", "Last activation", "Compare"].map(h => <th key={h} className="p-2 text-muted">{h}</th>)}</tr></thead><tbody>{versions.map(v => <tr key={v.release} className="border-t border-border"><td className="p-2">{modelLabel(v)}</td><td>{number(v.params)}</td><td>{number(v.totals?.steps)}</td><td>{number(v.training?.val_loss ?? v.training?.best_val)}</td><td>{v.method ?? "Unavailable"}{v.growth ? ` · ${number(v.growth.params_before)} → ${number(v.growth.params_after)}` : ""}</td><td>{date(v.deployed_at)}</td><td><Button size="sm" variant="ghost" onClick={() => setCompare(v.release)}>Compare #{v.release}</Button></td></tr>)}</tbody></table> : <p className="text-muted">No accepted checkpoint yet.</p>}
      {previous && <div className="mt-3 space-y-1 border-t border-border pt-3"><p>Compared with {modelLabel(previous)}: parameter change {model.params != null && previous.params != null ? number(model.params - previous.params) : "Unavailable"}.</p>
        <p>Held-out evaluation change: {number(comparable && model.evaluation.score?.value != null && previous.evaluation.score?.value != null ? model.evaluation.score.value - previous.evaluation.score.value : null)}{comparable ? ` ${model.evaluation.score.metric} (lower is better)` : " · requires measurements on the same evaluation dataset"}.</p>
      </div>}
    </CardContent></Card>
    <details className="text-xs"><summary className="cursor-pointer text-muted">Training, growth and failure history</summary><div className="mt-2 space-y-2">{data.training?.experiments?.map((e: Any) => <div key={e.experiment} className="rounded border border-border p-2">Experiment #{e.experiment} · {e.status} · {date(e.created_at)} · candidate {e.candidate ?? "Unavailable"}
      {e.growth && <p>Proposed expansion: {number(e.growth.params_before)} → {number(e.growth.params_after)} parameters</p>}
      <p>Measured improvement: {number(e.metrics?.primary_improvement)}{e.error && ` · ${e.error}`}</p></div>)}</div></details>
    <details className="text-xs"><summary className="cursor-pointer text-muted">Recent model activity</summary>{data.recent?.map((e: Any) => <p key={e.id} className="mt-1 text-muted">{date(e.ts)} · {e.message}</p>)}</details>
    {view}
  </div>;
}
