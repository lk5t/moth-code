import { useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { isTauri } from "@/lib/backend";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";

type UpdateState =
  | { kind: "idle" }
  | { kind: "checking" }
  | { kind: "none" }
  | { kind: "available"; version: string; notes?: string }
  | { kind: "downloading"; progress: number }
  | { kind: "ready" }
  | { kind: "error"; message: string };

let pending: any = null;

export async function checkForUpdate(): Promise<{ version: string; body?: string } | null> {
  if (!isTauri()) return null;
  const { check } = await import("@tauri-apps/plugin-updater");
  pending = await check();
  return pending ? { version: pending.version, body: pending.body } : null;
}

/** Signed in-app updates from GitHub Releases (verified with the bundled public key). */
export function UpdatesSection() {
  const [state, setState] = useState<UpdateState>({ kind: "idle" });

  const check = async () => {
    setState({ kind: "checking" });
    try {
      const u = await checkForUpdate();
      setState(u ? { kind: "available", version: u.version, notes: u.body } : { kind: "none" });
    } catch (e) {
      setState({ kind: "error", message: String((e as Error).message ?? e) });
    }
  };

  const install = async () => {
    if (!pending) return;
    let total = 0;
    let done = 0;
    try {
      await pending.downloadAndInstall((ev: any) => {
        if (ev.event === "Started") total = ev.data.contentLength ?? 0;
        if (ev.event === "Progress") {
          done += ev.data.chunkLength;
          setState({ kind: "downloading", progress: total ? (done / total) * 100 : 0 });
        }
        if (ev.event === "Finished") setState({ kind: "ready" });
      });
      const { relaunch } = await import("@tauri-apps/plugin-process");
      await relaunch();
    } catch (e) {
      setState({ kind: "error", message: String((e as Error).message ?? e) });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Download className="size-4 text-accent" />Updates</CardTitle>
        <CardDescription>Updates are downloaded from GitHub Releases and installed only if their signature verifies.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        {!isTauri() ? (
          <span className="text-muted">Updates are available in the installed desktop app.</span>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" disabled={state.kind === "checking" || state.kind === "downloading"} onClick={check}>
                <RefreshCw /> Check for updates
              </Button>
              {state.kind === "available" && <Button size="sm" onClick={install}>Install {state.version}</Button>}
              {state.kind === "none" && <span className="text-muted">You're up to date.</span>}
              {state.kind === "checking" && <span className="text-muted">Checking…</span>}
              {state.kind === "ready" && <span className="text-success">Installed — restarting…</span>}
              {state.kind === "error" && <span className="text-danger">{state.message}</span>}
            </div>
            {state.kind === "available" && state.notes && <pre className="selectable max-h-32 overflow-auto whitespace-pre-wrap text-muted">{state.notes}</pre>}
            {state.kind === "downloading" && <Progress value={state.progress} />}
          </>
        )}
      </CardContent>
    </Card>
  );
}
