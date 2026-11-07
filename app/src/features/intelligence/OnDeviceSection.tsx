/** Settings → MOTH on this computer: download the model MOTH Cloud serves and answer without the internet. */
import { useEffect, useState } from "react";
import { HardDriveDownload, Laptop, Trash2 } from "lucide-react";
import { del, get, post, put } from "@/lib/backend";
import { useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";

interface OnDeviceState {
  downloading: boolean;
  progress: number | null;
  error: string | null;
  loaded: boolean;
  answer_on_device: boolean;
  installed: { display_name?: string; model_version?: string; params?: number; official?: boolean; installed_at: number } | null;
}

export function OnDeviceSection() {
  const signedIn = useAccount((s) => !!s.token);
  const [st, setSt] = useState<OnDeviceState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () => get<OnDeviceState>("/api/ondevice").then(setSt).catch(() => setSt(null));
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    if (!st?.downloading) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [st?.downloading]);
  if (!st) return null;
  const inst = st.installed;
  const run = (p: Promise<unknown>) => p.then(load).catch((e) => setErr((e as Error).message));
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Laptop className="size-4 text-accent" />MOTH on this computer</CardTitle>
        <CardDescription>
          Download the model MOTH Cloud serves and answer without an internet connection. The download is verified
          (MOTH's release signature and SHA-256) before it is used. When MOTH Cloud can't be reached, chat uses it automatically.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-xs">
        {inst ? (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[13px] text-fg">{inst.display_name ?? "MOTH"}</span>
            {inst.params && <span className="text-muted">{(inst.params / 1e6).toFixed(1)}M parameters</span>}
            {inst.official && <Badge variant="success">signed by MOTH</Badge>}
            <div className="flex-1" />
            <Button size="sm" variant="ghost" onClick={() => run(del("/api/ondevice"))}><Trash2 />Remove</Button>
          </div>
        ) : (
          <div className="text-muted">Not downloaded.</div>
        )}
        {st.downloading ? (
          <div className="flex flex-col gap-1"><Progress value={(st.progress ?? 0) * 100} />
            <span className="text-muted">Downloading… {Math.round((st.progress ?? 0) * 100)}%</span></div>
        ) : (
          <div>
            <Button size="sm" variant={inst ? "secondary" : "default"} disabled={!signedIn}
              onClick={() => { setErr(null); run(post("/api/ondevice/download")); }}>
              <HardDriveDownload />{inst ? "Check for a newer model" : "Download MOTH"}
            </Button>
          </div>
        )}
        {inst && (
          <div className="flex items-center justify-between gap-6">
            <div><div className="text-[13px] text-fg">Answer on this computer</div>
              <div className="text-muted">Chat runs here instead of on MOTH Cloud (slower on older computers, nothing is sent).</div></div>
            <Switch checked={st.answer_on_device} onCheckedChange={(v) => run(put("/api/ondevice/settings", { answer_on_device: v }))} />
          </div>
        )}
        {(err || st.error) && <div className="text-danger">{err || st.error}</div>}
      </CardContent>
    </Card>
  );
}
