import { useEffect, useMemo, useState } from "react";
import { Brain, Database, Pause, Play, Plus, Square, Trash2, Type, Upload } from "lucide-react";
import { del, get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { useResource } from "@/lib/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { LossChart, type MetricPoint } from "@/components/LossChart";
import { cn, formatNumber, timeAgo } from "@/lib/utils";
import { DatasetQualityStudio } from "./DatasetQualityStudio";
import { SourcePicker, type SourceSel } from "./SourcePicker";

interface Job { id: string; kind: string; title: string; status: string; progress: number | null; message: string; error: string | null; created: number }
interface TokenizerInfo { name: string; vocab_size: number; fingerprint: string }
interface DatasetInfo { name: string; tokens: { train: number; val: number }; documents: { train: number; val: number }; sources: { spec: string; license: string }[]; tokenizer_fingerprint: string }
interface Preset { name: string; params: number; max_seq_len: number; vocab_size: number }
interface Run { id: string; name: string; status: string; step: number; config: Record<string, any>; best_val: number | null; error: string | null; updated_at: number; job: string | null }

const statusTone: Record<string, "success" | "warning" | "danger" | "accent" | "default"> = {
  running: "accent", completed: "success", stopped: "warning", interrupted: "warning", failed: "danger", created: "default",
};

export function TrainingView({ scope = "all" }: { scope?: "all" | "data" | "training" }) {
  const { data: jobs } = useResource<Job[]>("/api/jobs", ["job"], []);
  const { data: tokenizers } = useResource<TokenizerInfo[]>("/api/tokenizers", ["job"], []);
  const { data: datasets } = useResource<DatasetInfo[]>("/api/datasets", ["job"], []);
  const { data: runs, reload: reloadRuns } = useResource<Run[]>("/api/training/runs", ["job"], []);
  const { data: presets } = useResource<Preset[]>("/api/training/presets", [], []);
  const [dialog, setDialog] = useState<null | "tokenizer" | "dataset" | "run">(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeJobs = (jobs ?? []).filter((j) => j.status === "running" || Date.now() / 1000 - j.created < 30);
  const run = runs?.find((r) => r.id === selected) ?? runs?.[0];

  const act = (fn: () => Promise<unknown>) => async () => {
    try {
      setError(null);
      await fn();
      reloadRuns();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto flex max-w-6xl flex-col gap-3 p-3 sm:p-4">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-lg font-semibold">{scope === "data" ? "Local datasets and tokenizers" : "Local training runs"}</h1>
            <p className="mt-1 text-xs text-muted">{scope === "data" ? "Prepare licensed sources on this computer. Original files are preserved." : "Advanced local experiments, with resumable checkpoints. Cloud training has its own controls above."}</p>
          </div>
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}


        {activeJobs.length > 0 && (
          <Card>
            <CardContent className="flex flex-col gap-3">
              {activeJobs.map((j) => (
                <div key={j.id} className="flex items-center gap-3">
                  <div className="w-64 truncate text-xs">{j.title}</div>
                  <Progress value={(j.progress ?? 0) * 100} className="flex-1" />
                  <Badge variant={j.status === "running" ? "accent" : j.status === "completed" ? "success" : "danger"}>{j.status}</Badge>
                  <span className="w-40 truncate text-[11px] text-muted" title={j.error ?? j.message}>{j.error ?? j.message}</span>
                  {j.status === "running" && (
                    <Button size="icon-sm" variant="ghost" title="Stop" onClick={act(() => post(`/api/jobs/${j.id}/stop`))}><Square /></Button>
                  )}
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        <div className={`grid gap-3 ${scope === "data" ? "sm:grid-cols-2" : scope === "all" ? "lg:grid-cols-3" : "grid-cols-1"}`}>
          {scope !== "training" && <><StepCard n={1} icon={<Type />} title="Tokenizer" desc="Learns MOTH's vocabulary (custom BPE)." onNew={() => setDialog("tokenizer")}>
            {tokenizers?.length ? tokenizers.map((t) => (
              <Item key={t.name} title={t.name} sub={`${formatNumber(t.vocab_size, 1)} tokens · ${t.fingerprint.slice(0, 8)}`} />
            )) : <Empty text="No tokenizer yet" />}
          </StepCard>
          <StepCard n={2} icon={<Database />} title="Dataset" desc="Tokenised, license-tracked training data." onNew={() => setDialog("dataset")} disabled={!tokenizers?.length}>
            {datasets?.length ? datasets.map((d) => (
              <Item key={d.name} title={d.name} sub={`${(d.documents?.train || 0) + (d.documents?.val || 0)} examples · ${formatNumber(d.tokens.train)} train · ${formatNumber(d.tokens.val)} val tokens · ${tokenizers?.some(t => t.fingerprint === d.tokenizer_fingerprint) ? "tokenizer available" : "tokenizer unavailable"}`}
                action={<Button size="icon-sm" variant="ghost" onClick={act(() => (confirm(`Delete the prepared dataset ${d.name}? Original sources are kept.`) ? del(`/api/datasets/${encodeURIComponent(d.name)}`) : Promise.resolve()))}><Trash2 /></Button>} />
            )) : <Empty text="No dataset yet" />}
          </StepCard>
          </>}
          {scope !== "data" && <StepCard n={3} icon={<Brain />} title="Training runs" desc={datasets?.length ? "Real forward/backward passes and weight updates." : "Prepare a dataset in Data before starting a run."} onNew={() => setDialog("run")} disabled={!datasets?.length}>
            {runs?.length ? runs.map((r) => (
              <button key={r.id} onClick={() => setSelected(r.id)} className={cn("w-full cursor-pointer text-left", run?.id === r.id && "[&>div]:border-accent/60")}>
                <Item title={r.name} sub={`${r.config.preset} · step ${r.step}/${r.config.max_steps}`} action={<Badge variant={statusTone[r.status]}>{r.status}</Badge>} />
              </button>
            )) : <Empty text="No runs yet" />}
          </StepCard>}
        </div>

        {scope !== "data" && run && <RunDetail run={run} act={act} />}
      </div>

      {scope !== "training" && <DatasetQualityStudio tokenizers={tokenizers ?? []} datasets={datasets ?? []} />}
      <TokenizerDialog open={dialog === "tokenizer"} onClose={() => setDialog(null)} onError={setError} />
      <DatasetDialog open={dialog === "dataset"} onClose={() => setDialog(null)} onError={setError} tokenizers={tokenizers ?? []} />
      <RunDialog open={dialog === "run"} onClose={() => setDialog(null)} onError={setError} datasets={datasets ?? []} presets={presets ?? []}
        onCreated={(id) => { setSelected(id); reloadRuns(); }} />
    </div>
  );
}

function StepCard({ n, icon, title, desc, children, onNew, disabled }: { n: number; icon: React.ReactNode; title: string; desc: string; children: React.ReactNode; onNew: () => void; disabled?: boolean }) {
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 [&_svg]:size-4 [&_svg]:text-accent">
            <span className="flex size-5 items-center justify-center rounded-full border border-accent/40 text-[10px] text-accent">{n}</span>
            {icon}{title}
          </CardTitle>
          <Button size="sm" variant="outline" onClick={onNew} disabled={disabled}><Plus /> New</Button>
        </div>
        <CardDescription>{desc}</CardDescription>
      </CardHeader>
      <CardContent className="flex max-h-64 flex-col gap-1.5 overflow-auto">{children}</CardContent>
    </Card>
  );
}

function Item({ title, sub, action }: { title: string; sub: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2 rounded-md border border-border px-2.5 py-2 transition-colors hover:border-border-strong">
      <div className="min-w-0">
        <div className="truncate text-[13px]">{title}</div>
        <div className="truncate text-[11px] text-muted">{sub}</div>
      </div>
      {action}
    </div>
  );
}

const Empty = ({ text }: { text: string }) => <div className="py-4 text-center text-xs text-faint">{text}</div>;

function RunDetail({ run, act }: { run: Run; act: (fn: () => Promise<unknown>) => () => void }) {
  const [metrics, setMetrics] = useState<(MetricPoint & { lr?: number; tokens_per_sec?: number })[]>([]);
  const [exportName, setExportName] = useState("");
  const [extra, setExtra] = useState("");
  useEffect(() => {
    get<typeof metrics>(`/api/training/runs/${run.id}/metrics`).then(setMetrics).catch(() => setMetrics([]));
    setExportName(`${run.name}-step${run.step}`);
  }, [run.id]);
  useEvent("training", (e) => {
    if (e.run_id !== run.id || e.kind !== "metrics") return;
    setMetrics((m) => [...m, { step: e.step, split: e.split, loss: e.loss, lr: e.lr, tokens_per_sec: e.tokens_per_sec }]);
  });
  const lastTrain = useMemo(() => [...metrics].reverse().find((m) => m.split === "train"), [metrics]);
  const lastVal = useMemo(() => [...metrics].reverse().find((m) => m.split === "val"), [metrics]);
  const running = run.status === "running";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">{run.name} <Badge variant={statusTone[run.status]}>{run.status}</Badge></CardTitle>
          <div className="flex items-center gap-2">
            {running ? (
              <Button size="sm" variant="secondary" onClick={act(() => post(`/api/training/runs/${run.id}/stop`))}><Pause /> Pause & checkpoint</Button>
            ) : (
              <>
                <Input className="h-7 w-28 text-xs" placeholder="max steps" value={extra} onChange={(e) => setExtra(e.target.value)} title="Optionally extend max steps" />
                <Button size="sm" onClick={act(() => post(`/api/training/runs/${run.id}/resume`, { max_steps: extra ? Number(extra) : null }))}><Play /> Resume</Button>
                <Button size="icon-sm" variant="ghost" title="Delete run" onClick={act(() => (confirm(`Delete run ${run.name} and its checkpoints?`) ? del(`/api/training/runs/${run.id}`) : Promise.resolve()))}><Trash2 /></Button>
              </>
            )}
          </div>
        </div>
        <CardDescription>
          {run.config.preset} · seq {run.config.seq_len} · batch {run.config.batch_size}×{run.config.grad_accum} · lr {run.config.lr} · updated {timeAgo(run.updated_at)}
        </CardDescription>
        {run.error && <div className="mt-1 rounded border border-danger/30 bg-danger/10 px-2 py-1 text-[11px] text-danger">{run.error}</div>}
      </CardHeader>
      <CardContent>
        <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="Step" value={`${run.step} / ${run.config.max_steps}`} />
          <Stat label="Train loss" value={lastTrain ? lastTrain.loss.toFixed(3) : "—"} />
          <Stat label="Val loss" value={lastVal ? lastVal.loss.toFixed(3) : "—"} />
          <Stat label="Best val" value={run.best_val != null ? run.best_val.toFixed(3) : "—"} />
          <Stat label="Tokens / s" value={lastTrain?.tokens_per_sec ? formatNumber(lastTrain.tokens_per_sec, 1) : "—"} />
        </div>
        <Progress value={(run.step / run.config.max_steps) * 100} className="mb-4" />
        <LossChart points={metrics} />
        <div className="mt-4 flex items-center gap-2 border-t border-border pt-4">
          <Upload className="size-4 text-accent" />
          <span className="text-xs text-muted">Export for local inference</span>
          <Input className="h-7 max-w-64 text-xs" value={exportName} onChange={(e) => setExportName(e.target.value)} />
          <Button size="sm" variant="outline" disabled={!exportName} onClick={act(() => post(`/api/training/runs/${run.id}/export`, { name: exportName, which: "best" }))}>Export best</Button>
          <Button size="sm" variant="ghost" disabled={!exportName} onClick={act(() => post(`/api/training/runs/${run.id}/export`, { name: exportName, which: "latest" }))}>Export latest</Button>
        </div>
      </CardContent>
    </Card>
  );
}

const Stat = ({ label, value }: { label: string; value: string }) => (
  <div className="rounded-md border border-border bg-bg px-3 py-2">
    <div className="text-[10.5px] uppercase tracking-wider text-faint">{label}</div>
    <div className="mt-0.5 font-mono text-sm text-fg">{value}</div>
  </div>
);

function TokenizerDialog({ open, onClose, onError }: { open: boolean; onClose: () => void; onError: (e: string) => void }) {
  const [name, setName] = useState("moth-bpe-16k");
  const [vocab, setVocab] = useState(16384);
  const [sources, setSources] = useState<SourceSel[]>([{ spec: "stdlib", license: "PSF-2.0" }]);
  const submit = async () => {
    try {
      await post("/api/tokenizers", { name, vocab_size: vocab, sources });
      onClose();
    } catch (e) {
      onError(String((e as Error).message ?? e));
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="w-[560px]">
        <DialogTitle>New tokenizer</DialogTitle>
        <DialogDescription>Learns byte-level BPE merges from your selected data.</DialogDescription>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div><Label>Name</Label><Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label>Vocabulary size</Label><Input className="mt-1" type="number" value={vocab} onChange={(e) => setVocab(Number(e.target.value))} /></div>
        </div>
        <div className="mt-3 max-h-80 overflow-auto"><SourcePicker value={sources} onChange={setSources} /></div>
        <div className="mt-4 flex justify-end"><Button disabled={!name || !sources.length} onClick={submit}>Train tokenizer</Button></div>
      </DialogContent>
    </Dialog>
  );
}

function DatasetDialog({ open, onClose, onError, tokenizers }: { open: boolean; onClose: () => void; onError: (e: string) => void; tokenizers: TokenizerInfo[] }) {
  const [name, setName] = useState("code-v1");
  const [tok, setTok] = useState("");
  const [sources, setSources] = useState<SourceSel[]>([{ spec: "stdlib", license: "PSF-2.0" }]);
  useEffect(() => setTok((t) => t || tokenizers[0]?.name || ""), [tokenizers]);
  const submit = async () => {
    try {
      await post("/api/datasets", { name, tokenizer: tok, sources });
      onClose();
    } catch (e) {
      onError(String((e as Error).message ?? e));
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="w-[560px]">
        <DialogTitle>New dataset</DialogTitle>
        <DialogDescription>Tokenises the selected sources and records their licenses.</DialogDescription>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div><Label>Name</Label><Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label>Tokenizer</Label>
            <Select className="mt-1 w-full" value={tok} onChange={(e) => setTok(e.target.value)}>
              {tokenizers.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
            </Select>
          </div>
        </div>
        <div className="mt-3 max-h-80 overflow-auto"><SourcePicker value={sources} onChange={setSources} /></div>
        <div className="mt-4 flex justify-end"><Button disabled={!name || !tok || !sources.length} onClick={submit}>Prepare dataset</Button></div>
      </DialogContent>
    </Dialog>
  );
}

function RunDialog({ open, onClose, onError, datasets, presets, onCreated }: { open: boolean; onClose: () => void; onError: (e: string) => void; datasets: DatasetInfo[]; presets: Preset[]; onCreated: (id: string) => void }) {
  const [name, setName] = useState("moth-50m-v0.1");
  const [dataset, setDataset] = useState("");
  const [preset, setPreset] = useState("moth-50m");
  const [advanced, setAdvanced] = useState(false);
  const [conf, setConf] = useState({ max_steps: 20000, seq_len: 1024, batch_size: 8, grad_accum: 4, lr: 6e-4, warmup_steps: 500, eval_interval: 250, checkpoint_interval: 500, device: "auto", gradient_checkpointing: false });
  useEffect(() => setDataset((d) => d || datasets[0]?.name || ""), [datasets]);
  const num = (k: keyof typeof conf) => (
    <div key={k}>
      <Label>{k.replace(/_/g, " ")}</Label>
      <Input className="mt-1" type="number" step="any" value={conf[k] as number} onChange={(e) => setConf({ ...conf, [k]: Number(e.target.value) })} />
    </div>
  );
  const submit = async () => {
    try {
      const r = await post<Run>("/api/training/runs", { name, dataset, preset, config: conf });
      onCreated(r.id);
      onClose();
    } catch (e) {
      onError(String((e as Error).message ?? e));
    }
  };
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="w-[560px]">
        <DialogTitle>New training run</DialogTitle>
        <DialogDescription>Starts from random initialisation. You can pause at any time — progress is checkpointed and resumable.</DialogDescription>
        <div className="mt-4 grid grid-cols-2 gap-3">
          <div><Label>Run name</Label><Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} /></div>
          <div><Label>Dataset</Label>
            <Select className="mt-1 w-full" value={dataset} onChange={(e) => setDataset(e.target.value)}>
              {datasets.map((d) => <option key={d.name} value={d.name}>{d.name}</option>)}
            </Select>
          </div>
          <div><Label>Model size</Label>
            <Select className="mt-1 w-full" value={preset} onChange={(e) => {
              const p = presets.find((x) => x.name === e.target.value);
              setPreset(e.target.value);
              if (p) setConf((c) => ({ ...c, seq_len: Math.min(c.seq_len, p.max_seq_len) }));
            }}>
              {presets.map((p) => <option key={p.name} value={p.name}>{p.name} ({formatNumber(p.params, 1)} params)</option>)}
            </Select>
          </div>
          <div><Label>Device</Label>
            <Select className="mt-1 w-full" value={conf.device} onChange={(e) => setConf({ ...conf, device: e.target.value })}>
              <option value="auto">Auto (GPU if available)</option><option value="cuda">NVIDIA GPU (CUDA)</option><option value="cpu">CPU</option>
            </Select>
          </div>
          {num("max_steps")}
          {num("seq_len")}
        </div>
        <button className="mt-3 cursor-pointer text-xs text-muted hover:text-fg" onClick={() => setAdvanced(!advanced)}>{advanced ? "Hide" : "Show"} advanced settings</button>
        {advanced && (
          <div className="mt-2 grid grid-cols-3 gap-3">
            {(["batch_size", "grad_accum", "lr", "warmup_steps", "eval_interval", "checkpoint_interval"] as const).map(num)}
            <label className="col-span-3 flex items-center gap-2 text-xs text-muted">
              <input type="checkbox" className="accent-[#C1121F]" checked={conf.gradient_checkpointing} onChange={(e) => setConf({ ...conf, gradient_checkpointing: e.target.checked })} />
              Gradient checkpointing (less GPU memory, slower)
            </label>
          </div>
        )}
        <div className="mt-4 flex justify-end"><Button disabled={!name || !dataset} onClick={submit}><Play /> Start training</Button></div>
      </DialogContent>
    </Dialog>
  );
}
