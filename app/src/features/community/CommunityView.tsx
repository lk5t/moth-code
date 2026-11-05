import { useEffect, useState } from "react";
import { BookOpenCheck, HeartHandshake, Lock, Pause, Play, Upload } from "lucide-react";
import { post, put } from "@/lib/backend";
import { useApp } from "@/lib/app-state";
import { useResource } from "@/lib/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { timeAgo } from "@/lib/utils";
import { Row } from "@/features/settings/SettingsView";

interface Settings {
  enabled: boolean; paused: boolean; coordinator_url: string; gpu_memory_fraction: number; duty_cycle: number; device: string;
  schedule_enabled: boolean; schedule_days: number[]; schedule_start_hour: number; schedule_end_hour: number; max_rounds_per_day: number;
}
interface Community {
  settings: Settings; can_contribute: boolean; reason: string; rounds_today: number;
  coordinator: { round?: number; version?: number; pending_contributions?: number; error?: string } | null;
  running: { id: string; progress: number | null; message: string }[];
  history: { ts: number; message: string }[];
}
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function CommunityView() {
  const { data, setData, reload } = useResource<Community>("/api/community", ["job"]);
  const project = useApp((s) => s.project);
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => setUrl(data?.settings.coordinator_url ?? ""), [data?.settings.coordinator_url]);
  if (!data) return null;
  const s = data.settings;
  const save = async (patch: Partial<Settings>) => setData(await put<Community>("/api/community", patch));
  const run = async (fn: () => Promise<any>) => {
    setMsg(null);
    try {
      const r = await fn();
      if (r?.examples) setMsg(`Exported ${r.examples} verified task transcript(s). Use source “${r.source_spec}” in a new dataset to fine-tune locally.`);
      reload();
    } catch (e) {
      setMsg(String((e as Error).message ?? e));
    }
  };

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto flex max-w-3xl flex-col gap-5 p-8 animate-rise">
        <div>
          <h1 className="text-lg font-semibold">Learning network</h1>
          <p className="mt-1 text-xs text-muted">Help MOTH improve by donating computing power — only if you choose to.</p>
        </div>
        {msg && <div className="rounded-md border border-border bg-surface px-3 py-2 text-xs text-muted">{msg}</div>}

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Lock className="size-4 text-accent" />What is shared</CardTitle>
            <CardDescription>
              When you contribute, MOTH downloads the current community model and a <b>public</b> data shard from the coordinator,
              trains on it, and uploads only the resulting weight update and loss statistics. Your projects, files, chats,
              credentials and personal data are never read for or included in a contribution. Off by default.
            </CardDescription>
          </CardHeader>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle className="flex items-center gap-2"><HeartHandshake className="size-4 text-accent" />Community training</CardTitle>
              <Switch checked={s.enabled} onCheckedChange={(v) => save({ enabled: v })} />
            </div>
            <CardDescription>
              Status: {data.can_contribute ? <Badge variant="success">ready</Badge> : <Badge>{data.reason}</Badge>}
              {data.coordinator && !data.coordinator.error && <> · round {data.coordinator.round}, model v{data.coordinator.version}</>}
              {data.coordinator?.error && <span className="text-danger"> · {data.coordinator.error}</span>}
            </CardDescription>
          </CardHeader>
          {s.enabled && (
            <CardContent>
              <div className="mb-3 grid grid-cols-[1fr_auto] items-end gap-2">
                <div>
                  <Label>Coordinator URL</Label>
                  <Input className="mt-1" placeholder="No public MOTH coordinator is running yet" value={url} onChange={(e) => setUrl(e.target.value)} />
                </div>
                <Button variant="secondary" onClick={() => save({ coordinator_url: url.trim() })}>Save</Button>
              </div>
              <Row title="GPU memory limit" desc={`${Math.round(s.gpu_memory_fraction * 100)}% of GPU memory at most`}>
                <input type="range" min={0.1} max={0.9} step={0.05} value={s.gpu_memory_fraction} className="w-40 accent-[#C1121F]"
                  onChange={(e) => save({ gpu_memory_fraction: Number(e.target.value) })} />
              </Row>
              <Row title="Compute usage" desc={`Train ${Math.round(s.duty_cycle * 100)}% of the time, rest between steps`}>
                <input type="range" min={0.1} max={1} step={0.05} value={s.duty_cycle} className="w-40 accent-[#C1121F]"
                  onChange={(e) => save({ duty_cycle: Number(e.target.value) })} />
              </Row>
              <Row title="Only during scheduled hours" desc={s.schedule_enabled ? `${s.schedule_start_hour}:00 – ${s.schedule_end_hour}:00` : "Any time"}>
                <Switch checked={s.schedule_enabled} onCheckedChange={(v) => save({ schedule_enabled: v })} />
              </Row>
              {s.schedule_enabled && (
                <div className="flex flex-wrap items-center gap-3 py-2 text-xs">
                  <span>From</span>
                  <Input type="number" min={0} max={23} className="w-16" value={s.schedule_start_hour} onChange={(e) => save({ schedule_start_hour: Number(e.target.value) })} />
                  <span>to</span>
                  <Input type="number" min={0} max={23} className="w-16" value={s.schedule_end_hour} onChange={(e) => save({ schedule_end_hour: Number(e.target.value) })} />
                  {DAYS.map((d, i) => (
                    <label key={d} className="flex items-center gap-1">
                      <input type="checkbox" className="accent-[#C1121F]" checked={s.schedule_days.includes(i)}
                        onChange={(e) => save({ schedule_days: e.target.checked ? [...s.schedule_days, i] : s.schedule_days.filter((x) => x !== i) })} />{d}
                    </label>
                  ))}
                </div>
              )}
              <Row title="Daily limit" desc={`${data.rounds_today} of ${s.max_rounds_per_day} rounds today`}>
                <Input type="number" min={1} className="w-20" value={s.max_rounds_per_day} onChange={(e) => save({ max_rounds_per_day: Number(e.target.value) })} />
              </Row>
              <div className="mt-3 flex items-center gap-2">
                {s.paused ? (
                  <Button variant="secondary" onClick={() => save({ paused: false })}><Play /> Resume participation</Button>
                ) : (
                  <Button variant="secondary" onClick={() => save({ paused: true })}><Pause /> Pause</Button>
                )}
                <Button disabled={!data.can_contribute || data.running.length > 0} onClick={() => run(() => post("/api/community/contribute"))}><Upload /> Contribute one round</Button>
              </div>
              {data.running.map((j) => (
                <div key={j.id} className="mt-3 flex items-center gap-3 text-xs">
                  <Progress value={(j.progress ?? 0) * 100} className="flex-1" />
                  <span className="text-muted">{j.message}</span>
                </div>
              ))}
            </CardContent>
          )}
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><BookOpenCheck className="size-4 text-accent" />Personal learning (local only)</CardTitle>
            <CardDescription>
              Turn tasks MOTH completed <i>and</i> verified with your tests into training examples stored on this PC. Use them as a
              dataset source to fine-tune your own model in Training. Nothing is uploaded.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex gap-2">
            <Button variant="outline" onClick={() => run(() => post("/api/learning/personal/export", { project_id: project?.id ?? null }))}>
              Export verified tasks{project ? ` from ${project.name}` : ""}
            </Button>
          </CardContent>
        </Card>

        {data.history.length > 0 && (
          <Card>
            <CardHeader><CardTitle>History</CardTitle></CardHeader>
            <CardContent className="space-y-1 text-xs">
              {data.history.map((h, i) => <div key={i} className="flex justify-between gap-3"><span>{h.message}</span><span className="shrink-0 text-faint">{timeAgo(h.ts)}</span></div>)}
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
