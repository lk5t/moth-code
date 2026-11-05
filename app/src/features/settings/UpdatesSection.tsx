import { Download, RefreshCw } from "lucide-react";
import { isTauri } from "@/lib/backend";
import { APP_VERSION } from "@/lib/endpoint";
import { checkForUpdates, installNow, useUpdater } from "@/lib/updater";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { timeAgo } from "@/lib/utils";

/** Automatic, signed updates from MOTH Cloud. Nothing to do here normally. */
export function UpdatesSection() {
  const u = useUpdater((s) => s);
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Download className="size-4 text-accent" />Updates</CardTitle>
        <CardDescription>
          MOTH Code updates itself. New versions download in the background and install the next time you restart or
          close the app. Every update is signature-checked; your settings, workspaces and accounts are kept.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        {!isTauri() ? (
          <span className="text-muted">Automatic updates run in the installed desktop app.</span>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-muted">Version {APP_VERSION}</span>
              {u.phase === "up-to-date" && <span className="text-success">· up to date</span>}
              {u.phase === "checking" && <span className="text-muted">· checking…</span>}
              {u.phase === "downloading" && <span className="text-muted">· downloading {u.version}…</span>}
              {u.phase === "error" && <span className="text-danger">· {u.error} (it will retry automatically)</span>}
              {u.lastCheck && <span className="text-faint">· last checked {timeAgo(u.lastCheck / 1000)}</span>}
              <div className="flex-1" />
              {u.phase === "ready" ? (
                <Button size="sm" onClick={() => installNow()}>Restart and update to {u.version}</Button>
              ) : (
                <Button variant="ghost" size="sm" disabled={u.phase === "checking" || u.phase === "downloading"}
                  onClick={() => checkForUpdates({ manual: true }).catch(() => {})}><RefreshCw /> Check now</Button>
              )}
            </div>
            {u.phase === "downloading" && <Progress value={u.progress} />}
            {u.phase === "ready" && u.notes && <pre className="selectable max-h-32 overflow-auto whitespace-pre-wrap text-muted">{u.notes}</pre>}
          </>
        )}
      </CardContent>
    </Card>
  );
}
