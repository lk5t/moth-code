/**
 * No Model — Ready for Genesis: the guided fresh start shown wherever MOTH has no native model
 * (a new deployment, or after a Genesis Reset).
 *
 * Four real steps, each backed by the existing server operations: (optionally) prepare data so a
 * tokenizer can be trained from it, choose the model size and tokenizer, create and activate the
 * untrained model, start training. Parameter counts and "can this deployment train it" come from the
 * server; nothing here is estimated by the app.
 */
import { useState } from "react";
import { Check, Database, Play, Sprout } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { refreshCloudProgress } from "@/lib/cloud-progress";
import { secure, formatBytes } from "@/features/owner/ops";
import { navigate } from "@/lib/navigation";
import { openIntelligence } from "@/lib/app-state";
import { LivingMoth } from "@/components/LivingMoth";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn, formatNumber } from "@/lib/utils";

type Any = Record<string, any>;
const load = (path: string) => serverApi<Any>(path);

export function GenesisSetup() {
  const owner = useAccount((s) => s.user?.role === "owner");
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data, error, reload } = useResource<Any>(owner ? "/v1/admin/evolution/initialize/options" : null, [], undefined, server + "\0" + token, load);
  const [size, setSize] = useState("seed"), [tokenizer, setTokenizer] = useState("byte");
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState<string | null>(null);
  const legacy = owner && !!error;  // a MOTH Cloud older than this app: only the default seed can be created
  const chosen = data?.sizes?.find((s: Any) => s.id === size)?.tokenizers?.[tokenizer];
  const create = async () => {
    setBusy(true); setNotice(null);
    try {
      await secure(() => serverApi("/v1/admin/evolution/initialize/activate", { method: "POST", json: legacy ? undefined : { size, tokenizer }, timeoutMs: 600000 }));
      refreshCloudProgress(true);
      openIntelligence("training");
    } catch (e) { setNotice((e as Error).message); void reload(); }
    finally { setBusy(false); }
  };
  return <Card aria-label="Genesis setup"><CardContent className="space-y-4 p-5">
    <div className="flex flex-wrap items-center gap-3"><LivingMoth className="size-10" /><div>
      <h2 className="text-xl font-medium">No Model — Ready for Genesis</h2>
      <p className="text-xs text-muted">MOTH has no native model on this deployment. {owner ? "Create one and train it from zero." : "The Owner can create one and start training."}</p>
    </div></div>
    {owner && <ol className="space-y-4 text-xs">
      <li className="space-y-2"><p className="flex items-center gap-2 text-sm font-medium"><Database className="size-4 text-accent" />1 · Data and tokenizer <span className="font-normal text-muted">(optional first step)</span></p>
        <p className="text-muted">A tokenizer decides how text becomes tokens and cannot be changed later without starting again. Byte-level needs nothing. To train one from data instead, prepare the dataset library first, then return here.</p>
        <div className="grid gap-2 sm:grid-cols-2">{(data?.tokenizers ?? [{ id: "byte", label: "Byte-level", available: true, note: "Lossless, needs no data." }]).map((t: Any) =>
          <button key={t.id} type="button" disabled={!t.available || busy} aria-pressed={tokenizer === t.id} onClick={() => setTokenizer(t.id)}
            className={cn("rounded-lg border p-3 text-left transition-colors disabled:opacity-50", tokenizer === t.id ? "border-accent bg-surface-2" : "border-border hover:bg-surface-2")}>
            <span className="flex items-center gap-2 text-fg">{tokenizer === t.id && <Check className="size-3.5 text-accent" />}{t.label}</span><span className="mt-1 block text-muted">{t.note}</span></button>)}</div>
        <Button size="sm" variant="ghost" onClick={() => navigate("data")}>Prepare data</Button></li>
      <li className="space-y-2"><p className="flex items-center gap-2 text-sm font-medium"><Sprout className="size-4 text-accent" />2 · Model size</p>
        <p className="text-muted">The parameter count is fixed by this choice. Ordinary training changes the weights, not the count; it grows later only through an evaluated growth experiment.</p>
        {legacy ? <p className="text-muted">This MOTH Cloud creates the standard seed model (about 0.1M parameters). Update MOTH Cloud to choose a size.</p> :
          <div className="grid gap-2 sm:grid-cols-3">{(data?.sizes ?? []).map((s: Any) => { const o = s.tokenizers?.[tokenizer]; return (
            <button key={s.id} type="button" disabled={busy || !o} aria-pressed={size === s.id} onClick={() => setSize(s.id)}
              className={cn("rounded-lg border p-3 text-left transition-colors disabled:opacity-50", size === s.id ? "border-accent bg-surface-2" : "border-border hover:bg-surface-2")}>
              <span className="flex items-center gap-2 text-fg">{size === s.id && <Check className="size-3.5 text-accent" />}{s.label}</span>
              {o && <span className="mt-1 block font-mono text-fg">{formatNumber(o.params)} parameters</span>}
              {o && <span className="block text-muted">{o.layers} layers · {o.d_model} wide · {formatBytes(o.training_memory_bytes)} to train</span>}
              <span className="mt-1 block text-muted">{s.note}</span>
              {o && !o.trainable_here && <span className="mt-1 block text-warning">Cannot train here yet: {o.blockers?.[0] ?? "no suitable computer"}</span>}
            </button>); })}</div>}</li>
      <li className="space-y-2"><p className="flex items-center gap-2 text-sm font-medium"><Play className="size-4 text-accent" />3 · Create the model</p>
        <p className="text-muted">Creates random, untrained weights{chosen ? ` (${chosen.params.toLocaleString()} parameters)` : ""}, checks they load and generate, and makes them the active model. It will answer poorly until it is trained.</p>
        <Button size="sm" disabled={busy || (!legacy && (!data?.can_initialize || !chosen))} onClick={() => void create()}>{busy ? "Creating the model…" : "Create and activate the model"}</Button>
        {data && !data.can_initialize && <p className="text-warning">A model is already registered ({data.existing}). Open Intelligence → Advanced to evaluate and deploy it.</p>}</li>
      <li><p className="text-sm font-medium">4 · Train</p><p className="text-muted">After creation this opens Intelligence → Training, where you start, pause and follow training.</p></li>
    </ol>}
    {notice && <p role="alert" className="text-xs text-danger">{notice}</p>}
  </CardContent></Card>;
}
