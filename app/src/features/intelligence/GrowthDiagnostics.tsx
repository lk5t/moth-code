/**
 * AI → AI Settings: why the parameter count is what it is, and the one way to change it.
 * Ordinary training never changes the count. It changes only when a larger candidate — proposed by the
 * growth planner on plateau evidence, or requested here by the Owner — passes every evaluation gate.
 */
import { useState } from "react";
import { serverApi, useAccount } from "@/lib/account";
import { useResource } from "@/lib/hooks";
import { secure, formatBytes } from "@/features/owner/ops";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

const load = (path: string) => serverApi<any>(path);
const pct = (x: number) => `${(x * 100).toFixed(2)}%`;
export function GrowthDiagnostics() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data, error, reload } = useResource<any>("/v1/admin/evolution/growth-diagnostics", [], undefined, server + "\0" + token, load);
  const [choice, setChoice] = useState(""), [notice, setNotice] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true); setNotice(null);
    try { await secure(fn); setNotice(ok); await reload(); } catch (e) { setNotice((e as Error).message); } finally { setBusy(false); }
  };
  const imps: number[] = data?.evidence?.recent_improvements ?? [];
  const options: any[] = data?.options ?? [];
  const picked = options.find((o) => `${o.add_layers}:${o.ffn_hidden}` === choice);
  return <Card><CardHeader><CardTitle>Model size and growth</CardTitle></CardHeader><CardContent className="space-y-3 text-xs">
    {error && <p role="alert">Growth evidence unavailable: {error}</p>}
    {data && <>
      <p><span className="font-mono text-sm text-fg">{data.architecture_params?.toLocaleString() ?? "No model"}</span>{data.architecture_params != null && " parameters in the deployed model"}
        {data.registered_params != null && data.registered_params !== data.architecture_params && <span className="text-warning"> · the registry records {data.registered_params.toLocaleString()}</span>}</p>
      <p className="text-muted">Training changes the weights, not the count. The count grows only when a larger candidate — a copy of the model with added layers or wider layers that starts out computing exactly the same answers — is trained further and then beats the deployed model on held-out benchmarks.</p>
      <div><p className="font-medium text-fg">Automatic growth: {!data.enabled ? "turned off" : data.decision?.grow ? "a larger candidate is justified" : "not justified yet"}</p>
        {data.decision && <p className="text-muted">{data.decision.reason}.</p>}
        {imps.length > 0 && <p className="text-muted">Measured improvement of recent cycles: {imps.slice(-6).map(pct).join(", ")}. Growth is proposed after three in a row below {pct(data.budget?.plateau_threshold ?? 0.01)}.</p>}
        {data.blockers?.filter((b: string) => b !== data.decision?.reason).map((reason: string) => <p key={reason} className="text-warning">{reason}</p>)}</div>
      {options.length > 0 && <div className="space-y-2 rounded-lg border border-border p-3">
        <p className="font-medium text-fg">Request a growth experiment</p>
        <p className="text-muted">Adds one larger candidate to the next training cycle without waiting for a plateau. It is still only a candidate: it must pass every gate against the deployed model, or it is discarded and nothing changes.</p>
        {data.request ? <div className="flex flex-wrap items-center gap-2"><span>Requested: {data.request.params.toLocaleString()} parameters, in the next cycle.</span>
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(() => serverApi("/v1/admin/evolution/growth-request", { method: "DELETE" }), "Request withdrawn.")}>Withdraw</Button></div>
          : <div className="flex flex-wrap items-center gap-2">
            <select aria-label="Growth option" className="h-8 rounded-md border border-border bg-bg px-2" value={choice} onChange={(e) => setChoice(e.target.value)}>
              <option value="">Choose a size…</option>
              {options.map((o) => <option key={`${o.add_layers}:${o.ffn_hidden}`} value={`${o.add_layers}:${o.ffn_hidden}`}>{o.params.toLocaleString()} parameters (+{Math.round((o.ratio - 1) * 100)}%{o.add_layers ? `, ${o.add_layers} more layer${o.add_layers > 1 ? "s" : ""}` : ""}{`, layer width ${o.ffn_hidden}`})</option>)}
            </select>
            <Button size="sm" variant="secondary" disabled={busy || !picked} onClick={() => void act(() => serverApi("/v1/admin/evolution/growth-request", { method: "POST", json: { add_layers: picked.add_layers, ffn_hidden: picked.ffn_hidden } }), "Requested. The experiment is added when the next cycle is planned.")}>Request experiment</Button></div>}
      </div>}
      {data.attempts?.length > 0 && <div><p className="font-medium text-fg">Growth experiments so far</p>
        {data.attempts.map((a: any) => <p key={a.id} className="text-muted">Experiment #{a.id}: {a.growth?.params_before?.toLocaleString()} → {a.growth?.params_after?.toLocaleString()} parameters · {a.status}{a.error ? ` (${a.error})` : ""}</p>)}</div>}
      {data.attempts?.length === 0 && data.architecture_params != null && <p className="text-muted">No growth experiment is recorded for this lineage (latest 100 experiments).</p>}
      <details><summary className="cursor-pointer text-muted">Limits and resource estimate</summary>
        <p>Largest allowed step: ×{data.budget?.max_ratio} · Owner approval above ×{data.budget?.approval_ratio} · parameter ceiling {data.budget?.max_params?.toLocaleString()}</p>
        {data.estimated_training_bytes != null && <p>Memory to train the next candidate: {formatBytes(data.estimated_training_bytes)} · {data.available_backend ? `can run on ${data.available_backend.backend}` : "no computer can run it now"}</p>}
        <p className="text-muted">{data.compatibility}</p></details>
    </>}
    {notice && <p role="status" className="text-muted">{notice}</p>}
    <Button size="sm" variant="ghost" onClick={() => void reload()}>Refresh</Button>
  </CardContent></Card>;
}
