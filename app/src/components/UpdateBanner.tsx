import { Download, X } from "lucide-react";
import { dismissUpdateNotice, installNow, useUpdater } from "@/lib/updater";
import { Button } from "@/components/ui/button";

/** Shown once an update has been downloaded and verified: one click installs it. */
export function UpdateBanner() {
  const u = useUpdater((s) => s);
  if (u.dismissed || (u.phase !== "ready" && u.phase !== "installing")) return null;
  return (
    <div className="fixed right-4 top-4 z-50 flex w-[340px] items-start gap-3 rounded-lg border border-accent/40 bg-surface p-3 text-xs shadow-glow animate-rise">
      <Download className="mt-0.5 size-4 shrink-0 text-accent" />
      <div className="flex-1">
        <div className="text-[13px] font-medium text-fg">MOTH Code {u.version} is ready</div>
        <div className="mt-0.5 text-muted">
          {u.phase === "installing" ? "Installing… MOTH Code will start again in a moment." :
            "Downloaded and signature-verified. It installs when you restart or close MOTH Code; your work and settings are kept."}
        </div>
        {u.phase === "ready" && (
          <div className="mt-2 flex gap-2">
            <Button size="sm" onClick={() => installNow()}>Restart now</Button>
            <Button size="sm" variant="ghost" onClick={dismissUpdateNotice}>Later</Button>
          </div>
        )}
      </div>
      {u.phase === "ready" && (
        <button className="cursor-pointer text-faint hover:text-fg" aria-label="Dismiss" onClick={dismissUpdateNotice}><X className="size-3.5" /></button>
      )}
    </div>
  );
}
