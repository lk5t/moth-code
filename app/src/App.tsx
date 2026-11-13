import { lazy, Suspense, useEffect, useState } from "react";
import { fetchBackendInfo, get, restartBackend, type BackendInfo } from "@/lib/backend";
import { startLivingActivity } from "@/lib/living-activity";
import { startEvents, useEvent } from "@/lib/events";
import { appStore, useApp, type Project } from "@/lib/app-state";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Splash } from "@/components/Splash";
import { NavRail } from "@/components/NavRail";
import { StatusBar } from "@/components/StatusBar";
import { WorkspaceShell } from "@/features/workspace/WorkspaceShell";
import { ApprovalDialog } from "@/features/workspace/ApprovalDialog";
const SettingsView = lazy(() => import("@/features/settings/SettingsView").then((m) => ({ default: m.SettingsView })));
import { loadProjects } from "@/features/workspace/project-actions";
import { views } from "@/views";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { initAccounts } from "@/lib/account";
import { AccountDialog } from "@/features/account/AccountDialog";
import { ReauthDialog } from "@/features/account/reauth";
import { startConnectionMonitor } from "@/lib/connection";
import { startUpdater } from "@/lib/updater";
import { UpdateBanner } from "@/components/UpdateBanner";
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
    startUpdater(); // independent of the local backend: an update can fix a broken backend
    const t = setTimeout(() => setMinSplash(false), 900);
    let cancelled = false;
    const poll = async () => {
      while (!cancelled) {
        const i = await fetchBackendInfo().catch((e) => ({ status: "failed", url: "", token: "", error: String(e) }) as BackendInfo);
        setInfo(i);
        if (i.status === "ready") {
          startLivingActivity();
          startEvents();
          initAccounts().catch(() => {}).finally(() => startConnectionMonitor());
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
      <>
      <UpdateBanner />
      <Splash
        status={failed ? "The MOTH backend failed to start" : "Starting MOTH…"}
        error={failed ? [info?.error, ...(info?.logs ?? [])].filter(Boolean).join("\n") : null}
        onRetry={() => restartBackend().then(() => location.reload())}
      />
      </>
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
            <div className={view === "workspace" || view === "chat" ? "flex h-full" : "hidden"}>
              <ErrorBoundary label="The workspace"><WorkspaceShell /></ErrorBoundary>
            </div>
            {view === "settings" && <div className="h-full animate-view-in"><ErrorBoundary label="Settings"><Suspense fallback={null}><SettingsView /></Suspense></ErrorBoundary></div>}
            {Extra && <div key={["intelligence", "evolution", "training", "models"].includes(view) ? "intelligence" : view} className="h-full animate-view-in">
              <ErrorBoundary label="This view"><Extra /></ErrorBoundary></div>}
          </main>
        </div>
        <StatusBar />
        <UpdateBanner />
        <ApprovalDialog />
        <AccountDialog />
        <ReauthDialog />
      </div>
    </TooltipProvider>
  );
}
