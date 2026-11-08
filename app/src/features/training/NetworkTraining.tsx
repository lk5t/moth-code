import { EvolutionControls } from "./EvolutionControls";
/**
 * Model training → MOTH training network: one model, trained by MOTH Cloud, its workers and this computer.
 *
 * "Train MOTH now" starts an evolution cycle of the deployed MOTH lineage on MOTH Cloud. With "Use cloud
 * workers" on (the default), compatible workers share the work in distributed rounds; "Contribute this
 * computer" lets this computer take part in the same experiment. Every number comes from MOTH Cloud.
 */
import { useEffect, useState } from "react";
import { Cloud, Cpu, Laptop, Play } from "lucide-react";
import { get, put } from "@/lib/backend";
import { serverApi } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { formatNumber } from "@/lib/utils";
import { secure } from "@/features/owner/ops";

type Any = Record<string, any>;

function usePoll<T>(fn: () => Promise<T>, ms: number): [T | null, () => void, string | null] {
  const [d, setD] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () => fn().then((v) => { setD(v); setError(null); }).catch((e) => setError(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, ms);
    return () => clearInterval(t);
  }, []);
  return [d, load, error];
}

export function ParticipantSwitch({ compact = false }: { compact?: boolean }) {
  const [st, reload, loadError] = usePoll<Any>(() => get<Any>("/api/participant"), 5000);
  const [err, setErr] = useState<string | null>(null);
  if (!st) return <p role="status" className="text-xs text-muted">{loadError || "Checking this computer's training connection…"}</p>;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-[13px] text-fg"><Laptop className="size-4 text-accent" />Contribute this computer</div>
          {!compact && <div className="text-xs text-muted">This computer trains parts of MOTH's experiments when it is idle enough. Stop at any time; work is checkpointed.</div>}
        </div>
        <Switch aria-label="Contribute this computer" checked={!!st.enabled} disabled={!st.available}
          onCheckedChange={(v) => { setErr(null); put("/api/participant", { enabled: v }).then(reload).catch((e) => setErr((e as Error).message)); }} />
      </div>
      {st.enabled && (
        <div className="text-xs text-muted">
          {st.job ? <>Training job {st.job}{st.progress != null && ` · ${Math.round(st.progress * 100)}%`}</> :
            st.paused_by_owner ? "Paused by the Owner" : "Waiting for work"} · {st.completed_jobs} job(s) done this session
        </div>
      )}
      {!st.available && <div className="text-xs text-muted">This build cannot train for the network.</div>}
      {(err || st.error) && <div className="text-xs text-danger">{err || st.error}</div>}
    </div>
  );
}

export function NetworkTraining() {
  const [evo, reloadEvo, loadError] = usePoll<Any>(() => serverApi<Any>("/v1/admin/evolution/status"), 5000);
  const [con] = usePoll<Any>(() => serverApi<Any>("/v1/admin/evolution/contributions"), 5000);
  const [msg, setMsg] = useState<string | null>(null);
  if (!evo) return <p role="status" className="text-xs text-muted">{loadError || "Loading training status…"}</p>;
  const s = evo.settings;
  const trainNow = () => secure(() => serverApi("/v1/admin/evolution/run", { method: "POST" }))
    .then(() => { setMsg("Training requested. Live status shows data preparation and compute availability."); reloadEvo(); }).catch((e) => setMsg((e as Error).message));
  const cyc = evo.cycle;
  const active = cyc && !["completed", "rejected", "failed", "cancelled", "rolled_back"].includes(cyc.status);
  const exp = con?.experiment;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Cloud className="size-4 text-accent" />MOTH training network</CardTitle>
        <CardDescription>
          One MOTH model, improved by MOTH Cloud, its workers and this computer together. Training continues the deployed
          model ({evo.active_model?.name ?? "none yet"}) — it never starts from random weights.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" disabled={!!active && !s.paused} onClick={trainNow}><Play />{s.paused ? "Resume MOTH training" : active ? "Training cycle active" : "Train MOTH now"}</Button>
          {cyc && <Badge variant={active ? "accent" : cyc.status === "completed" ? "success" : "default"}>Cycle #{cyc.id}: {cyc.status.replaceAll("_", " ")}</Badge>}
          {cyc?.result?.waiting_reason && <span className="text-muted">{cyc.result.waiting_reason}</span>}
        </div>
        <EvolutionControls settings={s} onChange={(changes) => secure(() => serverApi("/v1/admin/evolution/settings", {
          method: "PUT", json: { changes },
        })).then(reloadEvo).catch((e) => setMsg((e as Error).message))} />
        <ParticipantSwitch />
        {exp && (
          <div className="flex flex-col gap-2 rounded-md border border-border p-3">
            <div className="flex items-center gap-2 text-fg">Experiment #{exp.id} · round {Math.min(exp.round + 1, exp.rounds)} of {exp.rounds}
              <span className="text-muted">({exp.shards} participants, {exp.local_steps} steps each per round)</span></div>
            <Progress value={(exp.round / Math.max(1, exp.rounds)) * 100} />
            {exp.current_jobs.length > 0 && (
              <div className="flex flex-col gap-1">
                {exp.current_jobs.map((j: Any) => (
                  <div key={j.shard} className="flex items-center gap-2">
                    <span className="w-16 text-muted">shard {j.shard + 1}</span>
                    <span className="w-48 truncate">{j.worker ? `${j.worker.name}${j.worker.this_app ? " (this computer)" : ""}` : "waiting for a participant"}</span>
                    <Badge>{j.status}</Badge>
                    {j.progress != null && <span className="text-muted">{Math.round(j.progress * 100)}%</span>}
                  </div>
                ))}
              </div>
            )}
            {exp.contributors.length > 0 && (
              <div className="flex flex-col gap-1 pt-1">
                <div className="text-muted">Contributions to this experiment (verified):</div>
                {exp.contributors.map((c: Any) => (
                  <div key={c.worker_id} className="flex items-center gap-2">
                    {c.compute === "gpu" ? <Badge variant="accent">GPU</Badge> : <Badge><Cpu className="size-3" />CPU</Badge>}
                    <span className="w-48 truncate text-fg">{c.name}{c.this_app ? " (this computer)" : ""}</span>
                    <span className="text-muted">{formatNumber(c.tokens)} tokens · {c.rounds} round(s)</span>
                  </div>
                ))}
              </div>
            )}
            {exp.history.length > 0 && (
              <div className="text-muted">Last round: probe loss {exp.history.at(-1).probe_before.toFixed(3)} → {exp.history.at(-1).probe_after.toFixed(3)}
                {exp.history.at(-1).accepted ? " (applied)" : " (discarded)"}</div>
            )}
          </div>
        )}
        {msg && <div className="text-muted">{msg}</div>}
      </CardContent>
    </Card>
  );
}
