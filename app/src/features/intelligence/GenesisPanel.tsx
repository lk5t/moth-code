import { useEffect, useState } from "react";
import { Archive, RotateCcw, Sprout } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { secure, formatBytes } from "@/features/owner/ops";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

type Plan = Record<string, any>;

/** Separate backup review and activation: installing an update never resets the deployed model. */
export function GenesisPanel() {
  const owner = useAccount((s) => s.user?.role === "owner");
  const [plan, setPlan] = useState<Plan | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [start, setStart] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = () => serverApi<Plan>("/v1/admin/evolution/genesis").then(setPlan);
  useEffect(() => { if (owner) load().catch((e) => setError(e.message)); }, [owner]);
  const act = async (path: string, json?: unknown) => {
    setBusy(true); setError(null);
    try { await secure(() => serverApi(path, { method: "POST", json, timeoutMs: 600000 })); await load(); }
    catch (e) { setError((e as Error).message); await load().catch(() => {}); }
    finally { setBusy(false); }
  };
  if (!owner) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Sprout className="size-4 text-accent" />Legacy lineage recovery · fresh MOTH 0.01</CardTitle>
        <CardDescription>Start a new native lineage with fresh weights. Preparation pauses training, archives existing models and checkpoints, and verifies a complete restoration. Your accounts and projects are kept.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-xs">
        <div className="text-muted">Production activation requires your separate approval after reviewing the verified backup. A fresh baseline is untrained and may answer worse than the previous model. Future automatic promotions still require measured improvement.</div>
        {(!plan || ["not_prepared", "preparing", "restored"].includes(plan.status)) && (
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => act("/v1/admin/evolution/genesis/prepare")}>
            <Archive />{busy ? "Verifying backup…" : plan?.status === "preparing" ? "Retry after current jobs finish" : "Prepare and verify backup"}
          </Button>
        )}
        {plan?.status === "prepared" && <>
          <div className="rounded-lg border border-border bg-surface-2 p-3">
            <p className="font-medium text-fg">Backup and restoration verified</p>
            <p className="mt-1 text-muted">{plan.previous_name ?? "Empty installation"} · {plan.archive_files} files · {formatBytes(plan.archive_bytes)}</p>
            <p className="mt-1 text-muted">Fresh baseline: {plan.parameters?.toLocaleString()} parameters · {plan.model_config?.n_layers} layers · step 0 · no inherited optimizer state</p>
          </div>
          <label className="flex items-center justify-between gap-3">Begin eligible training after activation
            <Switch checked={start} onCheckedChange={setStart} disabled={busy} />
          </label>
          <label className="flex flex-col gap-1 text-muted">Type RESET MOTH TO 0.01 to approve activation
            <Input aria-label="Confirm fresh MOTH lineage" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} placeholder="RESET MOTH TO 0.01" />
          </label>
          <Button size="sm" disabled={busy || confirmation !== plan.confirmation} onClick={() => act("/v1/admin/evolution/genesis/activate", {
            reset_id: plan.id, confirmation, start_training: start,
          })}><Sprout />{busy ? "Activating…" : "Approve and activate fresh lineage"}</Button>
        </>}
        {plan?.status === "active" && <p className="text-success">Fresh lineage activated by the Owner. Its current training and evaluations are shown above.</p>}
        {plan && ["preparing", "prepared", "active"].includes(plan.status) && (
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => {
            if (confirm("Restore the previous model and keep training paused? Current checkpoints will be retained.")) act(`/v1/admin/evolution/genesis/${plan.id}/restore`);
          }}><RotateCcw />{plan.status === "active" ? "Restore previous lineage" : "Cancel reset preparation"}</Button>
        )}
        {error && <p role="alert" className="text-danger">{error}</p>}
      </CardContent>
    </Card>
  );
}
