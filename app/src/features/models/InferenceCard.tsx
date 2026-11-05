import { useEffect, useState } from "react";
import { Cloud, HardDrive, Sparkles } from "lucide-react";
import { put } from "@/lib/backend";
import { useResource } from "@/lib/hooks";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Inference {
  settings: { mode: string; cloud_url: string; cloud_api_key: string; consent_remote_chat: boolean; consent_remote_project_data: boolean };
  status: { mode: string; local: { loaded: boolean; name?: string }; cloud: { configured: boolean; reachable?: boolean; error?: string; models?: { name: string }[] } };
}

const MODES = [
  { id: "local", label: "Local", icon: <HardDrive />, desc: "Runs on this PC. Nothing leaves your computer." },
  { id: "cloud", label: "MOTH Cloud", icon: <Cloud />, desc: "MOTH models on MOTH-operated servers (not available yet)." },
  { id: "auto", label: "Automatic", icon: <Sparkles />, desc: "Local when a model is loaded, otherwise MOTH Cloud — with your permission." },
];

export function InferenceCard() {
  const { data, setData } = useResource<Inference>("/api/inference", ["model"]);
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  useEffect(() => {
    if (data) {
      setUrl(data.settings.cloud_url);
      setKey(data.settings.cloud_api_key);
    }
  }, [data?.settings.cloud_url]);
  if (!data) return null;
  const s = data.settings;
  const save = async (patch: Partial<Inference["settings"]>) => setData(await put<Inference>("/api/inference", patch));
  const cloud = data.status.cloud;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Inference</CardTitle>
        <CardDescription>Every option runs MOTH's own trained models — never a third-party AI.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-3 gap-2">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => save({ mode: m.id })}
              className={cn(
                "flex cursor-pointer flex-col gap-1 rounded-lg border border-border p-3 text-left transition-all hover:border-border-strong [&_svg]:size-4",
                s.mode === m.id && "border-accent/70 bg-accent-soft shadow-glow",
              )}
            >
              <span className="flex items-center gap-2 text-[13px] font-medium">{m.icon}{m.label}</span>
              <span className="text-[11px] leading-snug text-muted">{m.desc}</span>
            </button>
          ))}
        </div>
        {s.mode !== "local" && (
          <div className="flex flex-col gap-3 rounded-lg border border-border p-3">
            <div className="flex items-center gap-2 text-xs">
              MOTH Cloud status:
              {!cloud.configured ? <Badge>not configured</Badge> : cloud.reachable ? <Badge variant="success">reachable · {cloud.models?.map((m) => m.name).join(", ")}</Badge> : <Badge variant="danger">{cloud.error}</Badge>}
            </div>
            <div className="text-[11px] text-muted">
              Signed in? Leave the endpoint empty: MOTH Cloud then uses your account's server and plan allowance. MOTH-operated GPU
              inference is not available yet; a self-hosted <code className="text-fg">moth cloud-serve</code> endpoint also works.
            </div>
            <div className="grid grid-cols-[1fr_200px_auto] items-end gap-2">
              <div><Label>Endpoint URL</Label><Input className="mt-1" placeholder="https://…" value={url} onChange={(e) => setUrl(e.target.value)} /></div>
              <div><Label>API key (optional)</Label><Input className="mt-1" type="password" value={key} onChange={(e) => setKey(e.target.value)} /></div>
              <Button variant="secondary" onClick={() => save({ cloud_url: url.trim(), cloud_api_key: key })}>Save</Button>
            </div>
            <label className="flex items-center justify-between gap-4 text-xs">
              <span>Allow sending chat messages to MOTH Cloud<span className="block text-[11px] text-muted">Credentials are always redacted before sending.</span></span>
              <Switch checked={s.consent_remote_chat} onCheckedChange={(v) => save({ consent_remote_chat: v })} />
            </label>
            <label className="flex items-center justify-between gap-4 text-xs">
              <span>Allow sending project data (agent tasks)<span className="block text-[11px] text-muted">Agent tasks include your project's files in requests.</span></span>
              <Switch checked={s.consent_remote_project_data} onCheckedChange={(v) => save({ consent_remote_project_data: v })} />
            </label>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
