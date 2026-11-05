import { useState } from "react";
import { Cpu, FlaskConical, Power, PowerOff, Trash2 } from "lucide-react";
import { del, get, post } from "@/lib/backend";
import { useResource } from "@/lib/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select } from "@/components/ui/select";
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
interface Status { loaded: boolean; id?: string; name?: string; device?: string }
interface Evaluation { val_loss: number; perplexity: number; next_token_accuracy: number; code_exact: number; code_total: number; dataset: string | null; ts: number; samples: { prompt: string; expected: string; output: string; pass: boolean | null }[] }

export function ModelsView() {
  const { data: models, reload } = useResource<ModelInfo[]>("/api/models", ["model"], []);
  const { data: status } = useResource<Status>("/api/model/status", ["model"]);
  const { data: datasets } = useResource<{ name: string }[]>("/api/datasets", [], []);
  const [device, setDevice] = useState("auto");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evals, setEvals] = useState<Record<string, Evaluation | null>>({});

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
          <h1 className="text-lg font-semibold">Models & inference</h1>
          <p className="mt-1 text-xs text-muted">MOTH models you trained and exported. Only MOTH's own models can be loaded.</p>
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}
        {modelsExtraSections.map((S, i) => <S key={i} />)}
        <div className="flex items-center gap-2 text-xs text-muted">
          Load on
          <Select className="h-7 text-xs" value={device} onChange={(e) => setDevice(e.target.value)}>
            <option value="auto">Auto (GPU if available)</option>
            <option value="cuda">NVIDIA GPU</option>
            <option value="cpu">CPU</option>
          </Select>
        </div>
        {!models?.length && (
          <Card><CardContent><EmptyState icon={<Cpu />} title="No models yet">Train a model, then use “Export” on the training run to make it available here.</EmptyState></CardContent></Card>
        )}
        {models?.map((m) => {
          const loaded = status?.loaded && status.id === m.id;
          const ev = evals[m.id];
          return (
            <Card key={m.id} className={loaded ? "border-accent/50 shadow-glow" : ""}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="flex items-center gap-2">
                    {m.name}
                    {loaded && <Badge variant="accent">loaded · {status?.device}</Badge>}
                  </CardTitle>
                  <div className="flex gap-1.5">
                    {loaded ? (
                      <Button size="sm" variant="secondary" disabled={!!busy} onClick={() => run("unload", () => post("/api/models/unload"))}><PowerOff /> Unload</Button>
                    ) : (
                      <Button size="sm" disabled={!!busy} onClick={() => run(m.id, () => post("/api/models/load", { id: m.id, device }))}><Power /> {busy === m.id ? "Loading…" : "Load"}</Button>
                    )}
                    <Button size="sm" variant="outline" disabled={!!busy} onClick={() => run(`eval-${m.id}`, () => post(`/api/models/${m.id}/evaluate`, { dataset: datasets?.[0]?.name ?? null }))}><FlaskConical /> Evaluate</Button>
                    <Button size="icon-sm" variant="ghost" onClick={() => confirm(`Delete model ${m.name}?`) && run(`del-${m.id}`, () => del(`/api/models/${m.id}`))}><Trash2 /></Button>
                  </div>
                </div>
                <CardDescription>
                  {formatNumber(m.params, 1)} parameters · {m.context_length} context · {m.dtype} · {formatNumber(m.size_bytes, 1)}B · exported {timeAgo(m.created)}
                </CardDescription>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4 text-xs">
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
