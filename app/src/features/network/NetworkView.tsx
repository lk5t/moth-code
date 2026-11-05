import { useEffect, useState } from "react";
import { Copy, Cpu, Pause, Play, Server, ShieldCheck, Trash2 } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label } from "@/components/ui/input";
import { EmptyState } from "@/components/ui/empty";
import { openAccountDialog } from "@/features/account/AccountDialog";
import { cn, timeAgo } from "@/lib/utils";

interface Worker {
  id: number;
  name: string;
  status: "online" | "offline" | "paused" | "revoked";
  paused: boolean;
  hardware: { gpus?: { name: string; memory_gb: number }[]; cuda?: string; os?: string };
  limits: { gpu_memory_fraction?: number; duty_cycle?: number };
  version: string | null;
  verified_jobs: number;
  failed_jobs: number;
  enrolled_at: number;
  last_heartbeat_at: number | null;
  referred: boolean;
}
interface Job { id: number; status: string; worker_id: number; progress: number | null; error: string | null; updated_at: number }
interface Listing { workers: Worker[]; jobs: Job[]; network: { configured: boolean; round: number | null; checkpoint_version: number | null } }
interface Enrollment { token: string; expires_at: number; command: string | null; manual_command: string; note: string | null; release: { version: string; sha256: string } | null }

const statusTone: Record<string, "success" | "warning" | "danger" | "default"> = { online: "success", paused: "warning", offline: "default", revoked: "danger" };

function Copyable({ text, label }: { text: string; label: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="relative">
      <pre className="selectable overflow-x-auto whitespace-pre-wrap break-all rounded-md border border-border bg-bg p-3 pr-24 font-mono text-[11.5px] text-fg">{text}</pre>
      <Button size="sm" variant="secondary" className="absolute right-2 top-2" onClick={async () => {
        await navigator.clipboard.writeText(text).catch(() => {});
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}><Copy /> {done ? "Copied" : label}</Button>
    </div>
  );
}

export function NetworkView() {
  const user = useAccount((s) => s.user);
  const [data, setData] = useState<Listing | null>(null);
  const [name, setName] = useState("");
  const [referral, setReferral] = useState("");
  const [enrollment, setEnrollment] = useState<Enrollment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, tick] = useState(0);

  const load = () => serverApi<Listing>("/v1/training/workers").then(setData).catch((e) => setError(e.message));
  useEffect(() => {
    if (!user) return;
    load();
    const t = setInterval(() => { load(); tick((n) => n + 1); }, 15000);
    return () => clearInterval(t);
  }, [user?.id]);

  if (!user) {
    return (
      <EmptyState icon={<Server />} title="Training & Referrals">
        Sign in to contribute GPU training compute to MOTH and earn rewards.
        <div className="mt-3"><Button onClick={() => openAccountDialog("login")}>Sign in</Button></div>
      </EmptyState>
    );
  }

  const act = (fn: () => Promise<unknown>) => async () => {
    setError(null);
    try {
      await fn();
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const expiresIn = enrollment ? Math.max(0, Math.round(enrollment.expires_at - Date.now() / 1000)) : 0;

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto flex max-w-4xl flex-col gap-5 p-8 animate-rise">
        <div>
          <h1 className="text-lg font-semibold">Training & Referrals</h1>
          <p className="mt-1 text-xs text-muted">
            Help train the official MOTH model by contributing GPU compute. MOTH Worker is a separate program for Linux GPU
            servers (for example a rented RTX 3060 12 GB). It is not an AI assistant and never sees your projects.
          </p>
        </div>
        {error && <div className="rounded-md border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">{error}</div>}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-accent" />How it works</CardTitle>
            <CardDescription>
              Workers download the current training checkpoint and a public, licensed data shard, train within the limits you
              set, and upload a weight update. Every update is verified before it counts. Verified work can earn MOTH usage
              credits for whoever referred the server; idle or failing servers earn nothing. Pause, limit or revoke a
              worker here at any time. Participation is optional.
            </CardDescription>
          </CardHeader>
          <CardContent className="text-xs text-muted">
            Training network: {data?.network.configured
              ? <>round <span className="text-fg">{data.network.round}</span> · checkpoint v{data.network.checkpoint_version}</>
              : "not accepting jobs yet (the Owner has not started a training run)"}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Server className="size-4 text-accent" />Add a GPU server</CardTitle>
            <CardDescription>Generates a one-time command (valid 15 minutes). Run it in the server's terminal. The download is checked against a pinned SHA-256 before anything runs.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="grid grid-cols-[1fr_200px_auto] items-end gap-2">
              <div><Label>Server name</Label><Input className="mt-1" placeholder="rtx3060-rental" value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div><Label>Referral code (optional)</Label><Input className="mt-1 uppercase" placeholder="someone else's code" value={referral} onChange={(e) => setReferral(e.target.value.toUpperCase())} /></div>
              <Button onClick={act(async () => setEnrollment(await serverApi<Enrollment>("/v1/training/enrollments", { method: "POST", json: { name: name || null, referral_code: referral || null } })))}>
                Generate command
              </Button>
            </div>
            {enrollment && (
              <div className="flex flex-col gap-2">
                {enrollment.command ? <Copyable text={enrollment.command} label="Copy" /> : (
                  <>
                    <div className="text-xs text-warning">{enrollment.note}</div>
                    <Copyable text={enrollment.manual_command} label="Copy" />
                  </>
                )}
                <div className="text-[11px] text-faint">
                  {expiresIn > 0 ? `Expires in ${Math.floor(expiresIn / 60)}:${String(expiresIn % 60).padStart(2, "0")} · single use` : "Expired — generate a new command."}
                  {enrollment.release && ` · MOTH Worker ${enrollment.release.version}`}
                  {" · Requires Linux, Python 3.10+, and an NVIDIA GPU with 8 GB+ VRAM."}
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Cpu className="size-4 text-accent" />Your workers</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-2">
            {!data?.workers.length && <div className="py-4 text-center text-xs text-faint">No workers yet.</div>}
            {data?.workers.map((w) => (
              <div key={w.id} className={cn("rounded-lg border border-border p-3", w.status === "online" && "border-success/30")}>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-[13px] font-medium">
                      {w.name} <Badge variant={statusTone[w.status]}>{w.status}</Badge>
                      {w.referred && <Badge>referred</Badge>}
                    </div>
                    <div className="mt-0.5 truncate text-[11px] text-muted">
                      {w.hardware.gpus?.length ? w.hardware.gpus.map((g) => `${g.name} (${g.memory_gb} GB)`).join(", ") : "no GPU detected"}
                      {w.hardware.cuda && ` · CUDA ${w.hardware.cuda}`} · {w.verified_jobs} verified / {w.failed_jobs} failed jobs
                      {w.last_heartbeat_at && ` · seen ${timeAgo(w.last_heartbeat_at)}`}
                    </div>
                  </div>
                  {w.status !== "revoked" && (
                    <div className="flex shrink-0 gap-1">
                      {w.paused
                        ? <Button size="sm" variant="secondary" onClick={act(() => serverApi(`/v1/training/workers/${w.id}/resume`, { method: "POST" }))}><Play /> Resume</Button>
                        : <Button size="sm" variant="secondary" onClick={act(() => serverApi(`/v1/training/workers/${w.id}/pause`, { method: "POST" }))}><Pause /> Pause</Button>}
                      <Button size="icon-sm" variant="ghost" title="Revoke (disconnect permanently)"
                        onClick={() => confirm(`Revoke ${w.name}? It will stop and can't reconnect.`) && act(() => serverApi(`/v1/training/workers/${w.id}/revoke`, { method: "POST" }))()}>
                        <Trash2 />
                      </Button>
                    </div>
                  )}
                </div>
                {w.status !== "revoked" && (
                  <div className="mt-2 flex items-center gap-4 text-[11px] text-muted">
                    <label className="flex items-center gap-2">GPU memory
                      <input type="range" min={0.1} max={0.95} step={0.05} className="w-28 accent-[#C1121F]" defaultValue={w.limits.gpu_memory_fraction ?? 0.9}
                        onMouseUp={(e) => act(() => serverApi(`/v1/training/workers/${w.id}/limits`, { method: "PUT", json: { gpu_memory_fraction: Number((e.target as HTMLInputElement).value) } }))()} />
                      {Math.round((w.limits.gpu_memory_fraction ?? 0.9) * 100)}%
                    </label>
                    <label className="flex items-center gap-2">Compute
                      <input type="range" min={0.1} max={1} step={0.05} className="w-28 accent-[#C1121F]" defaultValue={w.limits.duty_cycle ?? 1}
                        onMouseUp={(e) => act(() => serverApi(`/v1/training/workers/${w.id}/limits`, { method: "PUT", json: { duty_cycle: Number((e.target as HTMLInputElement).value) } }))()} />
                      {Math.round((w.limits.duty_cycle ?? 1) * 100)}%
                    </label>
                  </div>
                )}
              </div>
            ))}
            {!!data?.jobs.length && (
              <details className="mt-1">
                <summary className="cursor-pointer text-xs text-muted">Recent jobs</summary>
                <div className="mt-2 space-y-1 text-[11px]">
                  {data.jobs.map((j) => (
                    <div key={j.id} className="flex justify-between rounded border border-border px-2 py-1">
                      <span>job #{j.id} · worker {j.worker_id}{j.error ? <span className="text-danger"> · {j.error.slice(0, 80)}</span> : ""}</span>
                      <span className="text-muted">{j.status}{j.progress != null && j.status === "leased" ? ` ${Math.round(j.progress * 100)}%` : ""} · {timeAgo(j.updated_at)}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </CardContent>
        </Card>
        <p className="text-center text-[11px] text-faint">
          Share your referral code (Settings → Referrals) with people renting GPU servers. You earn credits only for their verified training work.
        </p>
      </div>
    </div>
  );
}
