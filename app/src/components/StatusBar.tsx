import { useState } from "react";
import { useEvent } from "@/lib/events";
import { appStore, useApp } from "@/lib/app-state";
import { useCloudStatus } from "@/lib/cloud";
import { cn } from "@/lib/utils";

export function StatusBar() {
  const project = useApp((s) => s.project);
  const updateVersion = useApp((s) => s.updateVersion);
  const [connected, setConnected] = useState(true);
  const { status: cloud } = useCloudStatus();
  const [training, setTraining] = useState<string | null>(null);

  useEvent("connection", (e) => setConnected(!!e.connected));
  useEvent("training", (e) => {
    if (e.kind === "metrics") setTraining(`training · step ${e.step} · loss ${Number(e.loss).toFixed(3)}`);
    if (e.kind === "status" && e.status !== "running") setTraining(null);
  });

  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-border bg-bg px-3 text-[11px] text-faint">
      <span className="flex items-center gap-1.5">
        <span className={cn("size-1.5 rounded-full", connected ? "bg-success" : "bg-danger animate-pulse")} />
        {connected ? "backend connected" : "reconnecting…"}
      </span>
      {project && <span className="truncate" title={project.path}>{project.path}</span>}
      <div className="flex-1" />
      {training && <span className="text-[#ff6b75]">{training}</span>}
      {updateVersion && (
        <button className="cursor-pointer text-[#ff6b75] hover:underline" onClick={() => appStore.setState({ view: "settings" })}>
          update {updateVersion} available
        </button>
      )}
      <span className="flex items-center gap-1.5">
        <span className={cn("size-1.5 rounded-full", cloud?.available ? "bg-success" : cloud?.signed_in ? "bg-warning" : "bg-faint")} />
        {cloud?.available ? `MOTH Cloud · ${cloud.model?.name}` : !cloud?.signed_in ? "MOTH Cloud · signed out" : cloud?.reachable === false ? "MOTH Cloud offline" : "MOTH Cloud unavailable"}
      </span>
    </footer>
  );
}
