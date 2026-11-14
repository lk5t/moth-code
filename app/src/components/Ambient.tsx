/** 1.0 ambient background: a slow glow that follows what MOTH is doing (CSS in index.css, ".ambient"). */
import { useEffect } from "react";
import { livingActivity, pulses } from "@/lib/living-activity";

export function Ambient() {
  const state = livingActivity.useStore((s) => s);
  const active = pulses(state);
  const mood = active.includes("training") ? "training" : active[0];
  useEffect(() => { document.documentElement.dataset.ambient = mood; }, [mood]);
  return <div aria-hidden="true" className="ambient" style={{ zIndex: 5 }} />;
}
