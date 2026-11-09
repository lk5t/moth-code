import { useCloudProgress } from "@/lib/cloud-progress";
import { MothEmblem } from "./MothEmblem";
import { livingActivity, pulses, dismissActivityError } from "@/lib/living-activity";

export function LivingMoth({ className }: {className?: string}) {
  useCloudProgress();
  const state=livingActivity.useStore((s) => s);
  const active=pulses(state);
  // Decorative activity reflects recorded stages, never individual neural calculations.
  const motion=active.includes("training") ? "training" : active[0];
  return <span data-living-state={active.join(" ")} title={`Activity: ${active.join(", ")}`}><MothEmblem motion={motion} className={className} /></span>;
}
export function IntelligencePulse() {
  const state=livingActivity.useStore((s) => s);
  const active=pulses(state);
  return <div className="flex flex-wrap items-center justify-center gap-1 text-[10px] text-muted" role="status" aria-label="MOTH activity">
    <span>{active.map((s) => s[0].toUpperCase()+s.slice(1)).join(" · ")}</span>
    {state.error && <button aria-label="Dismiss activity error" className="rounded px-1 text-danger focus-visible:outline" onClick={dismissActivityError}>×</button>}
  </div>;
}
