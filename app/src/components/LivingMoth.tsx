import { useCloudProgress } from "@/lib/cloud-progress";
import { MothEmblem } from "./MothEmblem";
import { livingActivity, pulses, dismissActivityError } from "@/lib/living-activity";
import { useEffect, useState } from "react";
import { useAlerts } from "@/lib/alerts";

const SLEEP_AFTER_MS = 3 * 60_000;
let lastInput = Date.now();
if (typeof window !== "undefined") {
  for (const ev of ["pointerdown", "keydown", "wheel"]) window.addEventListener(ev, () => { lastInput = Date.now(); }, { passive: true });
}

/** 1.0: the moth's mood — asleep when nothing happens for a while, cheering right after a promotion. */
function useMood(active: string[]): "sleeping" | "cheering" | null {
  const burst = useAlerts((s) => s.celebrate);
  const [cheer, setCheer] = useState(false);
  const [, tick] = useState(0);
  useEffect(() => { if (!burst) return; setCheer(true); const t = setTimeout(() => setCheer(false), 4000); return () => clearTimeout(t); }, [burst]);
  useEffect(() => { const t = setInterval(() => tick((n) => n + 1), 30_000); return () => clearInterval(t); }, []);
  if (cheer) return "cheering";
  return active.length === 1 && active[0] === "idle" && Date.now() - lastInput > SLEEP_AFTER_MS ? "sleeping" : null;
}

export function LivingMoth({ className }: {className?: string}) {
  useCloudProgress();
  const state=livingActivity.useStore((s) => s);
  const active=pulses(state);
  // Decorative activity reflects recorded stages, never individual neural calculations.
  const mood=useMood(active);
  const motion=mood ?? (active.includes("training") ? "training" : active[0]);
  const label=mood === "sleeping" ? "MOTH is resting" : mood === "cheering" ? "MOTH just got smarter!" : `Activity: ${active.join(", ")}`;
  return <span data-living-state={active.join(" ")} data-mood={mood ?? undefined} title={label}><MothEmblem motion={motion} className={className} /></span>;
}
export function IntelligencePulse() {
  const state=livingActivity.useStore((s) => s);
  const active=pulses(state);
  return <div className="flex flex-wrap items-center justify-center gap-1 text-[0.625rem] text-muted" role="status" aria-label="MOTH activity">
    <span>{active.map((s) => s[0].toUpperCase()+s.slice(1)).join(" · ")}</span>
    {state.error && <button aria-label="Dismiss activity error" className="rounded px-1 text-danger focus-visible:outline" onClick={dismissActivityError}>×</button>}
  </div>;
}
