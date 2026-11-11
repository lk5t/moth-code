import { useEffect, useState } from "react";
import { CheckCircle2, CloudUpload, Cpu, FlaskConical, ShieldCheck, Trash2, XCircle } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { serverApi } from "@/lib/account";
import { askPassword } from "@/features/account/reauth";
import { del, get, post } from "@/lib/backend";
import { useResource } from "@/lib/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { formatNumber, timeAgo } from "@/lib/utils";
import { modelsExtraSections } from "./sections";

interface ModelInfo {
  id: string;
  name: string;
  params: number;
  context_length: number;
  created: number;
  dtype: string;
  size_bytes: number;
  tokenizer_fingerprint: string;
  training: { run?: string; step?: number; val_loss?: number; best_val?: number; sources?: { spec: string; license: string }[] };
}
interface Evaluation { val_loss: number; perplexity: number; next_token_accuracy: number; code_exact: number; code_total: number; dataset: string | null; ts: number; samples: { prompt: string; expected: string; output: string; pass: boolean | null }[] }

interface PublishJob {
  model_id: string;
  stage: "validating" | "packaging" | "uploading" | "paused" | "processing" | "evaluating" | "evaluated" | "published" | "deployed" | "failed" | "idle";
  progress?: number;
  error?: string | null;
  release_version?: number;
  duplicate?: boolean;
  message?: string;
  resumed?: boolean;
  active?: boolean;
  notice?: string | null;
  size?: number;
  evaluation?: { passed?: boolean; reason?: string; score?: { metric: string; value: number }; dataset?: { name: string }; guidance?: string; note?: string };
}
interface Validation { ok: boolean; problems: string[]; info: Record<string, any> }

const STAGE_TEXT: Record<string, string> = {
  validating: "Checking the package…", packaging: "Preparing upload…", uploading: "Uploading to MOTH Cloud",
  paused: "Upload paused — it resumes automatically when MOTH Cloud is reachable", processing: "MOTH Cloud is verifying the upload…",
  evaluating: "MOTH Cloud is evaluating the model (it runs real inference)…",
  evaluated: "Evaluated — scored worse than the active model; you can still publish it from the Owner Dashboard",
  published: "Published — ready to deploy from Intelligence → Advanced → Cloud model registry", deployed: "Deployed — serving MOTH Cloud users",
  failed: "Publishing failed",
};

function usePublishJobs() {
  const [jobs, setJobs] = useState<Record<string, PublishJob>>({});
  const load = () => get<{ jobs: PublishJob[] }>("/api/publish")
    .then((r) => setJobs(Object.fromEntries(r.jobs.map((j) => [j.model_id, j])))).catch(() => {});
  const active = Object.values(jobs).some((j) => ["validating", "packaging", "uploading", "processing", "evaluating"].includes(j.stage));
  useEffect(() => {
    load();
    const t = setInterval(load, active ? 1000 : 10000);
    return () => clearInterval(t);
  }, [active]);
  return { jobs, load };
}

function PublishStatus({ job }: { job?: PublishJob }) {
  if (!job || job.stage === "idle") return null;
  const bad = job.stage === "failed";
  const good = job.stage === "published" || job.stage === "deployed";
  return (
    <div className={`col-span-2 flex flex-col gap-1.5 rounded-md border px-3 py-2 ${bad ? "border-danger/30 bg-danger/5" : good ? "border-success/30 bg-success/5" : "border-border"}`}>
      <div className="flex items-center gap-2">
        {bad ? <XCircle className="size-4 text-danger" /> : good ? <CheckCircle2 className="size-4 text-success" /> : <CloudUpload className="size-4 text-accent" />}
        <span className="text-fg">{job.duplicate && job.message ? job.message : STAGE_TEXT[job.stage] ?? job.stage}</span>
        {job.release_version && <span className="text-faint">· release v{job.release_version}</span>}
        {job.resumed && job.stage === "uploading" && <span className="text-faint">· resumed</span>}
      </div>
      {job.stage === "uploading" && (
        <>
          <Progress value={(job.progress ?? 0) * 100} />
          <div className="text-muted">
            {Math.round((job.progress ?? 0) * 100)}%{job.size ? ` of ${formatNumber(job.size, 1)}B` : ""} · interrupted
            uploads continue from the last completed chunk
          </div>
        </>
      )}
      {job.notice && <div className="text-warning">{job.notice}</div>}
      {job.evaluation?.score && (
        <div className="text-muted">
          Score {job.evaluation.score.value.toFixed(3)} {job.evaluation.score.metric === "bits_per_byte" ? "bits/byte" : "loss"} on {job.evaluation.dataset?.name}
        </div>
      )}
      {job.error && <div className={bad ? "text-danger" : "text-warning"}>{job.error}</div>}
      {job.evaluation?.guidance && <div className="text-muted">{job.evaluation.guidance}</div>}
      {job.evaluation?.note && <div className="text-faint">{job.evaluation.note}</div>}
    </div>
  );
}

export function ModelsView() {
  const { data: models, reload } = useResource<ModelInfo[]>("/api/models", ["model"], []);
  const { data: datasets } = useResource<{ name: string }[]>("/api/datasets", [], []);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evals, setEvals] = useState<Record<string, Evaluation | null>>({});
  const [checks, setChecks] = useState<Record<string, Validation>>({});
  const { jobs, load: loadJobs } = usePublishJobs();

  const run = async (key: string, fn: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await fn();
      reload();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    } finally {
      setBusy(null);
    }
  };
  const loadEval = (id: string) => get<Evaluation>(`/api/models/${id}/evaluation`).then((e) => setEvals((s) => ({ ...s, [id]: e }))).catch(() => setEvals((s) => ({ ...s, [id]: null })));

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto flex max-w-5xl flex-col gap-5 p-8 animate-rise">
        <div>
          <h1 className="text-lg font-semibold">Owner · model packages</h1>
          <p className="mt-1 text-xs text-muted">
            Models trained with the Owner training tools. Publishing sends one to MOTH Cloud:
            <span className="text-fg"> Validate → Upload → Evaluate → Publish</span> happen automatically (uploads resume if
            interrupted); then deploy it for everyone from Intelligence → Advanced → Cloud model registry. Models never serve users from this PC.
          </p>
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}
        {modelsExtraSections.map((S, i) => <S key={i} />)}
        {!models?.length && (
          <Card><CardContent><EmptyState icon={<Cpu />} title="No models yet">Train a model, then use “Export” on the training run to make it available here.</EmptyState></CardContent></Card>
        )}
        {models?.map((m) => {
          const ev = evals[m.id];
          return (
            <Card key={m.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2">
                    {m.name}
                  </CardTitle>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => run(`val-${m.id}`, async () => {
                      setChecks((c) => ({ ...c, [m.id]: undefined as any }));
                      const v = await post<Validation>(`/api/publish/${m.id}/validate`);
                      setChecks((c) => ({ ...c, [m.id]: v }));
                    })}><ShieldCheck /> {busy === `val-${m.id}` ? "Validating…" : "Validate"}</Button>
                    <Button size="sm" disabled={!!busy || ["validating", "packaging", "uploading", "processing", "evaluating"].includes(jobs[m.id]?.stage ?? "")}
                      onClick={() => run(`pub-${m.id}`, async () => {
                        try {
                          await post(`/api/models/${m.id}/publish`);
                        } catch (e) {
                          if ((e as { status?: number }).status !== 428) throw e;
                          const pw = await askPassword();
                          if (!pw) throw e;
                          await serverApi("/v1/auth/reauth", { method: "POST", json: { password: pw } });
                          await post(`/api/models/${m.id}/publish`);
                        }
                        loadJobs();
                      })}><CloudUpload /> {busy === `pub-${m.id}` ? "Starting…" : jobs[m.id]?.stage === "paused" || jobs[m.id]?.stage === "failed" ? "Retry publishing" : "Publish to MOTH Cloud"}</Button>
                    <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run(`eval-${m.id}`, () => post(`/api/models/${m.id}/evaluate`, { dataset: datasets?.[0]?.name ?? null }))}><FlaskConical /> Evaluate</Button>
                    <Button size="icon-sm" variant="ghost" onClick={() => confirm(`Delete model ${m.name}?`) && run(`del-${m.id}`, () => del(`/api/models/${m.id}`))}><Trash2 /></Button>
                  </div>
                </div>
                <CardDescription>
                  {formatNumber(m.params, 1)} parameters · {m.context_length} context · {m.dtype} · {formatNumber(m.size_bytes, 1)}B · exported {timeAgo(m.created)}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4 text-xs">
                {checks[m.id] && (
                  <div className={`col-span-2 rounded-md border px-3 py-2 ${checks[m.id].ok ? "border-success/30 bg-success/5" : "border-danger/30 bg-danger/5"}`}>
                    {checks[m.id].ok ? (
                      <span className="text-success">✓ Ready to publish: checksum, architecture ({checks[m.id].info.config?.n_layers} layers, d_model {checks[m.id].info.config?.d_model}), tokenizer ({checks[m.id].info.tokenizer?.vocab_size} tokens) and weights all verified. MOTH Cloud needs about {formatNumber(checks[m.id].info.resources?.ram_cpu_bytes / 2 ** 30, 1)} GB RAM to serve it on CPU.</span>
                    ) : (
                      <div className="text-danger">This model can't be published yet:<ul className="ml-4 list-disc">{checks[m.id].problems.map((p) => <li key={p}>{p}</li>)}</ul></div>
                    )}
                  </div>
                )}
                <PublishStatus job={jobs[m.id]} />
                <div className="space-y-1 text-muted">
                  <div>Run: <span className="text-fg">{m.training.run ?? "—"}</span> · step {m.training.step ?? "—"}</div>
                  <div>Validation loss: <span className="text-fg">{m.training.val_loss?.toFixed(3) ?? m.training.best_val?.toFixed(3) ?? "—"}</span></div>
                  <div className="flex flex-wrap gap-1">Data: {m.training.sources?.map((s) => <Badge key={s.spec}>{s.spec.replace(/^dir:.*[\\/]/, "dir:")} · {s.license}</Badge>) ?? "—"}</div>
                </div>
                <div>
                  {ev === undefined ? (
                    <button className="cursor-pointer text-muted hover:text-fg" onClick={() => loadEval(m.id)}>Show latest evaluation</button>
                  ) : ev === null ? (
                    <span className="text-muted">Not evaluated yet.</span>
                  ) : (
                    <div className="space-y-1 text-muted">
                      <div>Val loss <span className="text-fg">{ev.val_loss.toFixed(3)}</span> · perplexity <span className="text-fg">{formatNumber(ev.perplexity, 1)}</span></div>
                      <div>Next-token accuracy <span className="text-fg">{(ev.next_token_accuracy * 100).toFixed(1)}%</span></div>
                      <div>Code completion benchmark <span className="text-fg">{ev.code_exact}/{ev.code_total}</span> exact</div>
                      <div className="text-faint">evaluated {timeAgo(ev.ts)}</div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
