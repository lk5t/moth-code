import { useEffect, useState } from "react";
import { fetchBackendInfo, get, restartBackend, type BackendInfo } from "@/lib/backend";
import { startEvents, useEvent } from "@/lib/events";
import { appStore, useApp, type Project } from "@/lib/app-state";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Splash } from "@/components/Splash";
import { NavRail } from "@/components/NavRail";
import { StatusBar } from "@/components/StatusBar";
import { WorkspaceView } from "@/features/workspace/WorkspaceView";
import { ApprovalDialog } from "@/features/workspace/ApprovalDialog";
import { SettingsView } from "@/features/settings/SettingsView";
import { loadProjects } from "@/features/workspace/project-actions";
import { views } from "@/views";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { initAccounts } from "@/lib/account";
import { AccountDialog } from "@/features/account/AccountDialog";
import { ReauthDialog } from "@/features/account/reauth";
import { startConnectionMonitor } from "@/lib/connection";
import { startUpdater } from "@/lib/updater";
import { Welcome, useWelcomeVisible } from "@/features/onboarding/Welcome";

export default function App() {
  const [info, setInfo] = useState<BackendInfo | null>(null);
  const [minSplash, setMinSplash] = useState(true);
  const view = useApp((s) => s.view);
  const welcome = useWelcomeVisible();

  // If the event stream drops, check whether the backend process itself has failed
  // (crash, killed) and switch to the recovery screen instead of hanging.
  useEvent("connection", (e) => {
    if (e.connected) return;
    setTimeout(async () => {
      const i = await fetchBackendInfo().catch(() => null);
      if (i && i.status === "failed") setInfo(i);
    }, 3000);
  });

  useEffect(() => {
    const t = setTimeout(() => setMinSplash(false), 900);
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        const i = await fetchBackendInfo().catch((e) => ({ status: "failed", url: "", token: "", error: String(e) }) as BackendInfo);
        setInfo(i);
        if (i.status === "ready") {
          startEvents();
          initAccounts().catch(() => {}).finally(() => startConnectionMonitor());
          startUpdater(); // background checks and downloads; installs on restart or exit
          const projects = await loadProjects().catch(() => [] as Project[]);
          let last: string | null = null;
          try {
            last = localStorage.getItem("moth.lastProject");
          } catch {
            /* storage unavailable */
          }
          const project = projects.find((p) => String(p.id) === last) ?? null;
          if (project) await get(`/api/projects/${project.id}/tree`).then(() => appStore.setState({ project })).catch(() => {});
          return;
        }
        if (i.status === "failed") return;
        await new Promise((r) => setTimeout(r, 400));
      }
    };
    poll();
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, []);

  if (!info || info.status !== "ready" || minSplash) {
    const failed = info?.status === "failed";
    return (
      <Splash
        status={failed ? "The MOTH backend failed to start" : "Starting MOTH…"}
        error={failed ? [info?.error, ...(info?.logs ?? [])].filter(Boolean).join("\n") : null}
        onRetry={() => restartBackend().then(() => location.reload())}
      />
    );
  }

  const Extra = views[view];
  return (
    <TooltipProvider>
      <div className="relative flex h-full flex-col animate-fade-in">
        {welcome && <Welcome />}
        <div className="flex min-h-0 flex-1">
          <NavRail />
          <main className="min-w-0 flex-1">
            {/* Workspace stays mounted so editor/terminal state survives view switches. */}
            <div className={view === "workspace" ? "flex h-full" : "hidden"}>
              <ErrorBoundary label="The workspace"><WorkspaceView /></ErrorBoundary>
            </div>
            {view === "settings" && <ErrorBoundary label="Settings"><SettingsView /></ErrorBoundary>}
            {Extra && <ErrorBoundary key={view} label="This view"><Extra /></ErrorBoundary>}
          </main>
        </div>
        <StatusBar />
        <ApprovalDialog />
        <AccountDialog />
        <ReauthDialog />
      </div>
    </TooltipProvider>
  );
}
