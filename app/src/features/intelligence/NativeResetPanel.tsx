/**
 * Settings → Advanced → Genesis Reset (Owner only).
 *
 * Permanently deletes MOTH's native AI on the signed-in deployment so it can start again from zero.
 * Four deliberate steps: review the real deletion inventory (re-authentication required), type
 * RESET GENESIS, confirm once more, then the server deletes and verifies. The server enforces Owner
 * permission, re-authentication, the preview and the phrase independently of this screen.
 * Deleting one selected model is a different, ordinary operation (Intelligence → Advanced).
 */
import { useEffect, useRef, useState } from "react";
import { serverApi, useAccount } from "@/lib/account";
import { get, post } from "@/lib/backend";
import { useResource } from "@/lib/hooks";
import { refreshCloudProgress } from "@/lib/cloud-progress";
import { secure, formatBytes } from "@/features/owner/ops";
import { openIntelligence } from "@/lib/app-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";

type Plan = Record<string, any>;
const path = "/v1/admin/evolution/native-reset";
const load = (url: string) => serverApi<Plan>(url);
export const GENESIS_PHRASE = "RESET GENESIS";
/** MOTH Cloud 0.6.0 expects its original phrase on the wire; the Owner still types RESET GENESIS. */
const LEGACY_WIRE_PHRASE = "DELETE ALL NATIVE AI DATA";
const backupText = "DELETE MANAGED AI BACKUPS";

const DELETED = ["The active native model and every previous, candidate and archived model", "Model weights, packages, architecture revisions, checkpoints and optimizer states",
  "Imported and prepared training datasets, and custom tokenizers", "Training history, steps and metrics; evolution experiments; evaluations and benchmark results",
  "Promotion and rollback records, model-specific worker assignments, training caches and temporary files"];
const KEPT = ["Accounts, sign-in, credentials and security keys", "Billing, plans and referrals", "Ordinary conversations, projects and source files",
  "General settings, worker enrolments and consent", "The MOTH applications themselves"];

export function NativeResetPanel() {
  const owner = useAccount((s) => s.user?.role === "owner"), token = useAccount((s) => s.token), server = useAccount((s) => s.serverUrl);
  const { data: plan, error, reload } = useResource<Plan>(owner ? path : null, [], undefined, server + "\0" + token, load);
  const [backups, setBackups] = useState(false), [confirmation, setConfirmation] = useState(""), [backupConfirmation, setBackupConfirmation] = useState("");
  const [local, setLocal] = useState<Plan | null>(null), [alsoLocal, setAlsoLocal] = useState(false), [localResult, setLocalResult] = useState<string | null>(null);
  const [finalOpen, setFinalOpen] = useState(false);
  const [busy, setBusy] = useState(false), [notice, setNotice] = useState("");
  const current = useRef({ server, token }); current.current = { server, token };
  useEffect(() => { setConfirmation(""); setBackupConfirmation(""); setBackups(false); setNotice(""); setBusy(false); setFinalOpen(false); setAlsoLocal(false); setLocalResult(null); }, [server, token]);
  useEffect(() => { if (owner) get<Plan>("/api/native-ai").then(setLocal).catch(() => setLocal(null)); }, [owner, plan?.status]);
  if (!owner) return null;
  const active = () => current.current.server === server && current.current.token === token;
  const act = async (suffix: string, json: unknown, after?: () => Promise<void>) => {
    setBusy(true); setNotice("");
    try {
      await secure(() => { if (!active()) throw new Error("Account changed; inspect the current deployment before continuing."); return serverApi(path + suffix, { server, token, method: "POST", json, timeoutMs: 60000 }); });
      if (active()) { if (after) await after(); setConfirmation(""); setBackupConfirmation(""); refreshCloudProgress(true); await reload(); }
    } catch (e) { if (active()) { setNotice((e as Error).message); await reload(); } }
    finally { if (active()) setBusy(false); }
  };
  const clearLocal = async () => {
    if (!alsoLocal) return;
    try { const r = await post<Plan>("/api/native-ai/reset", { confirmation: GENESIS_PHRASE }); setLocalResult(`Deleted ${r.deleted_files} files (${formatBytes(r.deleted_bytes)}) of native AI data on this computer.`); }
    catch (e) { setLocalResult(`This computer's native AI data was not deleted: ${(e as Error).message}`); }
  };
  const execute = () => { setFinalOpen(false); void act("/execute", { reset_id: plan!.id, confirmation: plan!.confirmation ?? LEGACY_WIRE_PHRASE, backup_confirmation: backupConfirmation }, clearLocal); };
  const pending = ["fencing", "deleting", "failed"].includes(plan?.status);
  const reviewing = plan?.status === "preview" || pending;
  const ready = confirmation === GENESIS_PHRASE && (!plan?.backups || backupConfirmation === backupText);
  const inventory = plan?.inventory;
  const files = inventory?.roots?.reduce((n: number, r: Plan) => n + r.files, 0) ?? 0, bytes = inventory?.roots?.reduce((n: number, r: Plan) => n + r.bytes, 0) ?? 0;
  const records = inventory ? Object.values(inventory.records as Record<string, number>).reduce((a, b) => a + Number(b), 0) : 0;
  return <section className="space-y-4 rounded-xl border border-danger/50 p-4 text-xs" aria-label="Genesis Reset">
    <div><h3 className="text-sm font-semibold text-danger">Genesis Reset</h3>
      <p className="mt-1 text-muted">Permanently delete MOTH's native AI on <strong className="text-fg">{server}</strong> and start again from zero. This cannot be undone. Deleting a single model is a separate, ordinary action in Intelligence → Advanced.</p></div>
    <div className="grid gap-4 sm:grid-cols-2">
      <div><p className="font-medium text-fg">Deleted</p><ul className="mt-1 list-inside list-disc space-y-0.5 text-muted">{DELETED.map((t) => <li key={t}>{t}</li>)}</ul></div>
      <div><p className="font-medium text-fg">Kept</p><ul className="mt-1 list-inside list-disc space-y-0.5 text-muted">{KEPT.map((t) => <li key={t}>{t}</li>)}</ul></div>
    </div>
    <p className="text-muted">Training stops and worker assignments are revoked first; connected workers delete their cached copies and report back. Copies MOTH cannot reach — exported packages, infrastructure snapshots, offline computers — are not deleted and are listed after the reset. Managed GENESIS backups are kept unless you include them below.</p>

    {!reviewing && <div className="space-y-2">
      <p className="font-medium text-fg">Step 1 · Review what will be deleted</p>
      <label className="flex items-center gap-2"><input type="checkbox" checked={backups} onChange={(e) => setBackups(e.target.checked)} disabled={busy} />Also delete managed GENESIS model backups (separate confirmation)</label>
      <Button size="sm" variant="secondary" disabled={busy} onClick={() => void act("/preview", { include_managed_backups: backups })}>Review deletion</Button>
      <p className="text-faint">You will be asked for your password. Nothing is deleted in this step.</p>
    </div>}

    {inventory && reviewing && <div className="space-y-2 rounded-lg border border-border p-3">
      <p className="font-medium text-fg">Step 1 · Reviewed: {files.toLocaleString()} files ({formatBytes(bytes)}) and {records.toLocaleString()} records will be deleted</p>
      <details><summary className="cursor-pointer text-muted">Show the full inventory</summary>
        {inventory.roots.map((r: Plan) => <p key={r.category}>{r.category}: {r.files} files · {formatBytes(r.bytes)}</p>)}
        {Object.entries(inventory.records).map(([name, count]) => <p key={name}>{name}: {String(count)}</p>)}
        <p>Managed backup files: {inventory.managed_backup_files} · {plan.backups ? "will be deleted" : "kept"}</p>
        {inventory.external_references.map((ref: string) => <p key={ref}>Outside MOTH's storage, kept: {ref}</p>)}
      </details>
      <p className="text-muted">{inventory.disclosure}</p>
      {local && local.files > 0 && <label className="flex items-center gap-2"><input type="checkbox" checked={alsoLocal} onChange={(e) => setAlsoLocal(e.target.checked)} disabled={busy || local.running_jobs?.length > 0} />
        Also delete native AI data on this computer ({local.files} files, {formatBytes(local.bytes)}: local models, checkpoints, datasets, tokenizers){local.running_jobs?.length > 0 && " — stop local training first"}</label>}
    </div>}

    {plan && reviewing && <div className="space-y-2">
      <p className="font-medium text-fg">Step 2 · Type {GENESIS_PHRASE}</p>
      <Input aria-label="Genesis Reset confirmation" placeholder={GENESIS_PHRASE} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} autoComplete="off" spellCheck={false} />
      {plan.backups && <label className="block">Backups are included. Also type {backupText}<Input aria-label="Managed backup deletion confirmation" value={backupConfirmation} onChange={(e) => setBackupConfirmation(e.target.value)} autoComplete="off" spellCheck={false} /></label>}
      <p className="font-medium text-fg">Step 3 · Final confirmation</p>
      <Button size="sm" disabled={busy || !ready} onClick={() => setFinalOpen(true)}>{busy ? "Genesis Reset is running…" : pending ? "Continue the interrupted reset" : "Continue to final confirmation"}</Button>
      {pending && <p className="text-warning">A reset was started and did not finish. Native training and serving stay stopped until it completes; continuing is safe.</p>}
      {plan.status === "preview" && <p className="text-faint">This review expires 10 minutes after it was made.</p>}
    </div>}

    <Dialog open={finalOpen} onOpenChange={setFinalOpen}><DialogContent>
      <DialogTitle>Delete MOTH's native AI permanently?</DialogTitle>
      <DialogDescription>{files.toLocaleString()} files ({formatBytes(bytes)}) and {records.toLocaleString()} records on {server} will be deleted{plan?.backups ? ", including managed backups" : ""}{alsoLocal ? ", and the native AI data on this computer" : ""}. Every model, checkpoint, dataset, tokenizer and training record is removed. Accounts, conversations and projects are kept. This cannot be undone.</DialogDescription>
      <div className="mt-4 flex justify-end gap-2"><Button size="sm" variant="secondary" onClick={() => setFinalOpen(false)}>Cancel</Button>
        <Button size="sm" onClick={execute}>Delete everything and reset</Button></div>
    </DialogContent></Dialog>

    {plan?.status === "completed" && plan.ready_for_genesis !== false && <div className="space-y-2 rounded-lg border border-border p-3">
      <p className="text-sm font-medium text-fg">No Model — Ready for Genesis</p>
      <p>Verified: no native model, checkpoint, dataset, tokenizer or training record remains in MOTH's storage on this deployment. Nothing was created in their place.</p>
      <p className="text-muted">Kept managed backup files: {plan.retained_managed_backup_files} · Copies outside MOTH's storage: {plan.retained_external_copies} · Workers still to confirm cleanup: {plan.pending_worker_acknowledgements?.length || 0} · Worker cache files reported as kept: {Object.values(plan.reported_retained_worker_cache_files || {}).reduce((sum: number, n) => sum + Number(n), 0)}</p>
      {localResult && <p>{localResult}</p>}
      <p className="text-muted">{plan.disclosure}</p>
      <div className="flex flex-wrap gap-2"><Button size="sm" onClick={() => openIntelligence("overview")}>Begin Genesis</Button>
        <Button size="sm" variant="ghost" onClick={() => void reload()}>Refresh worker cleanup</Button></div>
    </div>}
    {(error || notice || plan?.error) && <p role="alert" className="text-danger">{notice || error || plan?.error}</p>}
  </section>;
}
