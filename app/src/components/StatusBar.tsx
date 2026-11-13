import { useCloudProgress } from "@/lib/cloud-progress";
import { modelLabel } from "@/lib/model-label";
import { useState } from "react";
import { useEvent } from "@/lib/events";
import { useApp } from "@/lib/app-state";
import { useAccount } from "@/lib/account";
import { useCloudStatus } from "@/lib/cloud";
import { checkNow, useConnection } from "@/lib/connection";
import { installNow, useUpdater } from "@/lib/updater";
import { cn } from "@/lib/utils";

/** One quiet line of status. Nothing here ever opens a popup by itself. */
export function StatusBar() {
  const {data: live} = useCloudProgress();
  const project = useApp((s) => s.project);
  const [backendUp, setBackendUp] = useState(true);
  const { status: cloud } = useCloudStatus();
  const conn = useConnection((s) => s.status);
  const signedIn = useAccount((s) => !!s.user);
  const required = useAccount((s) => s.updateRequired);
  const upd = useUpdater((s) => s);
  const [training, setTraining] = useState<string | null>(null);

  useEvent("connection", (e) => setBackendUp(!!e.connected));
  useEvent("training", (e) => {
    if (e.kind === "metrics") setTraining(`training · step ${e.step} · loss ${Number(e.loss).toFixed(3)}`);
    if (e.kind === "status" && e.status !== "running") setTraining(null);
  });

  const cloudLabel =
    conn === "unconfigured" ? "MOTH Cloud · not configured"
      : conn === "offline" ? "MOTH Cloud offline · retrying"
        : conn === "reconnecting" || conn === "connecting" ? "MOTH Cloud · connecting…"
          : !signedIn ? "MOTH Cloud · signed out"
            : cloud?.available ? `MOTH Cloud · ${live ? live.current ? "answering" : "no native model deployed" : "ready"}`
              : cloud?.reason === "inference_disabled" ? "MOTH Cloud · inference turned off"
                : cloud?.reason === "not_moth" ? "not a MOTH Cloud server"
                  : cloud?.reason === "unreachable" ? "MOTH Cloud unreachable · retrying"
                    : cloud?.reason === "training_first_model" ? "MOTH Cloud · training the first model"
                      : cloud?.reason === "model_loading" ? "MOTH Cloud · loading the model…"
                    : "MOTH Cloud · no model deployed yet";
  const dot = conn === "online" ? (signedIn && cloud?.available ? "bg-success" : "bg-warning")
    : conn === "offline" ? "bg-danger" : "bg-warning animate-pulse";

  return (
    <footer className="flex h-6 shrink-0 items-center gap-4 border-t border-border bg-bg px-3 text-[11px] text-faint">
      {!backendUp && (
        <span className="flex items-center gap-1.5"><span className="size-1.5 animate-pulse rounded-full bg-danger" />restarting local services…</span>
      )}
      {project && <span className="truncate" title={project.path}>{project.path}</span>}
      <div className="flex-1" />
      {training && <span className="text-[#ff6b75]">{training}</span>}
      {signedIn && live?.current && <span aria-label="Active MOTH model" className="text-muted">{modelLabel(live.current)}</span>}
      {required && upd.phase !== "ready" && (
        <span className="text-warning">MOTH Cloud needs version {required} · {upd.phase === "downloading" ? `downloading ${Math.round(upd.progress)}%` : "updating automatically"}</span>
      )}
      {upd.phase === "ready" && (
        <button className="cursor-pointer text-[#ff6b75] hover:underline" onClick={() => installNow()}>
          Restart to update to {upd.version}
        </button>
      )}
      <button className="flex cursor-pointer items-center gap-1.5 hover:text-fg"
        title={cloud?.error ? `${cloud.error}\n\nClick to check again.` : "Check the connection now"} onClick={() => checkNow()}>
        <span className={cn("size-1.5 rounded-full", dot)} />
        {cloudLabel}
      </button>
    </footer>
  );
}
