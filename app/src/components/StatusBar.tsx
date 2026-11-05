import { useEffect, useState } from "react";
import { get } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { appStore, useApp } from "@/lib/app-state";
import { cn } from "@/lib/utils";

interface StatusInfo {
  loaded: boolean;
  name?: string;
  device?: string;
  params?: number;
}

export function StatusBar() {
  const project = useApp((s) => s.project);
  const updateVersion = useApp((s) => s.updateVersion);
  const [connected, setConnected] = useState(true);
  const [model, setModel] = useState<StatusInfo | null>(null);
  const [training, setTraining] = useState<string | null>(null);

  const loadModel = () => get<StatusInfo>("/api/model/status").then(setModel).catch(() => setModel(null));
  useEffect(() => {
    loadModel();
  }, []);
  useEvent("connection", (e) => setConnected(!!e.connected));
  useEvent("model", loadModel);
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
      <span>{model?.loaded ? `${model.name} · ${model.device}` : "no model loaded"}</span>
    </footer>
  );
}
