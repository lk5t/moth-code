/**
 * Evolution: one-click improvement of MOTH. A single switch for automatic evolution, what is happening
 * now, and start / pause / resume. Advanced settings stay in Owner tools → Evolution.
 */
import { useEffect, useState } from "react";
import { Pause, Play, Settings2, Sparkles } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { appStore } from "@/lib/app-state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { NetworkTraining, ParticipantSwitch } from "@/features/training/NetworkTraining";
import { secure } from "@/features/owner/ops";

type Any = Record<string, any>;
const STATE: Record<string, string> = {
  planning: "Choosing what to train next", waiting_for_compute: "Waiting for computers to train on", training: "Training",
  evaluating: "Testing the new version", deploying: "Rolling out", monitoring: "Watching the new version in use",
  completed: "Finished", rejected: "Finished — no safe improvement found", failed: "Stopped after a problem",
  cancelled: "Cancelled", rolled_back: "Rolled back to the previous version",
};

export function EvolutionView() {
  const signedIn = useAccount((s) => !!s.token);
  const isOwner = useAccount((s) => s.user?.role === "owner");
  const [p, setP] = useState<Any | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const load = () => serverApi<Any>("/v1/intelligence/progress").then(setP).catch(() => {});
  useEffect(() => {
    if (!signedIn) return;
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, [signedIn]);
  if (!signedIn) return <EmptyState title="Sign in to follow MOTH's evolution">Evolution runs on MOTH Cloud.</EmptyState>;
  if (!p) return null;
  const tr = p.training;
  const cyc = tr.cycle;
  const busy = cyc && !["completed", "rejected", "failed", "cancelled", "rolled_back"].includes(cyc.status);
  const act = (fn: () => Promise<unknown>, ok: string) => secure(fn).then(() => { setMsg(ok); load(); }).catch((e) => setMsg((e as Error).message));
  const settings = (v: Any) => serverApi("/v1/admin/evolution/settings", { method: "PUT", json: v });
  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-5 p-8 animate-rise">
        <div>
          <h1 className="text-lg font-semibold">Evolution</h1>
          <p className="mt-1 text-xs text-muted">MOTH improves itself: it trains a new version, tests it against the current one on held-out benchmarks, and only keeps it if it is better.</p>
        </div>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Sparkles className="size-4 text-accent" />Automatic evolution</CardTitle>
            <CardDescription>Current model: {p.current ? (p.current.model_version ? `MOTH ${p.current.model_version}` : p.current.name) : "none deployed yet"}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4 text-xs">
            {isOwner && (
              <div className="flex items-center justify-between gap-4">
                <div><div className="text-[13px] text-fg">Improve MOTH automatically</div>
                  <div className="text-muted">Training cycles run on their own when data and computers are available.</div></div>
                <Switch checked={tr.enabled && !tr.paused} onCheckedChange={(v) =>
                  act(() => settings(v ? { enabled: true, paused: false } : { paused: true }), v ? "Automatic evolution is on." : "Paused.")} />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <span className="text-[13px] text-fg">{cyc ? STATE[cyc.status] ?? cyc.status : tr.enabled ? "Waiting for the next cycle" : "Off"}</span>
                {cyc && <Badge>cycle #{cyc.id}</Badge>}
              </div>
              {cyc?.waiting_reason && <div className="text-muted">{cyc.waiting_reason}</div>}
              {busy && tr.experiment_progress != null && <Progress value={tr.experiment_progress * 100} />}
              {!busy && tr.next_cycle_at_estimate && <div className="text-muted">Next cycle: {new Date(tr.next_cycle_at_estimate * 1000).toLocaleString()} (estimated)</div>}
            </div>
            {isOwner && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={!!busy} onClick={() => act(() => serverApi("/v1/admin/evolution/run", { method: "POST" }), "Started.")}><Play />Start now</Button>
                {tr.paused
                  ? <Button size="sm" variant="secondary" onClick={() => act(() => serverApi("/v1/admin/evolution/resume", { method: "POST" }), "Resumed.")}><Play />Resume</Button>
                  : <Button size="sm" variant="secondary" onClick={() => act(() => serverApi("/v1/admin/evolution/pause", { method: "POST" }), "Paused.")}><Pause />Pause</Button>}
                <Button size="sm" variant="ghost" onClick={() => appStore.setState({ view: "owner" })}><Settings2 />Advanced settings</Button>
              </div>
            )}
            {msg && <div className="text-muted">{msg}</div>}
          </CardContent>
        </Card>
        {isOwner ? <NetworkTraining /> : <Card><CardContent><ParticipantSwitch /></CardContent></Card>}
      </div>
    </div>
  );
}
