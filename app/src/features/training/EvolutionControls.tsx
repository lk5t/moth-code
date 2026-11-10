import { Switch } from "@/components/ui/switch";

type Settings = Record<string, any>;
/** Mounted only in Owner views; the existing API independently enforces Owner reauthentication. */
export function EvolutionControls({ settings: s, onChange, scope = "all" }: { settings: Settings; onChange: (changes: Settings) => void; scope?: "all" | "training" | "network" | "advanced" }) {
  const toggle = (label: string, checked: boolean, changes: (v: boolean) => Settings) =>
    <label className="flex items-center justify-between gap-4"><span>{label}</span>
      <Switch aria-label={label} checked={checked} onCheckedChange={(v) => onChange(changes(v))} /></label>;
  const select = (label: string, key: string, fallback: string, choices: [string, string][]) =>
    <label className="flex items-center justify-between gap-4"><span>{label}</span>
      <select aria-label={label} className="h-8 rounded-md border border-border bg-bg px-2" value={s[key] ?? fallback}
        onChange={(e) => onChange({ [key]: e.target.value })}>{choices.map(([v, text]) => <option key={v} value={v}>{text}</option>)}</select></label>;
  return <div className="flex flex-col gap-3 text-xs">
    {(scope === "all" || scope === "training") && <label className="flex items-center justify-between gap-4">Training schedule<select aria-label="Training schedule" className="h-8 rounded border border-border bg-bg px-2" value={s.automatic === false ? "manual" : "automatic"} onChange={e=>onChange({automatic:e.target.value === "automatic"})}><option value="automatic">Automatic</option><option value="manual" disabled={typeof s.automatic !== "boolean"}>Manual · one requested cycle</option></select></label>}
    {(scope === "all" || scope === "advanced") && select("Training Mode", "training_mode", "automatic", [["automatic", "Automatic"], ["maximum", "Maximum Performance"], ["eco", "Eco"]])}
    {(scope === "all" || scope === "network") && toggle("Use cloud workers", s.cloud_workers !== false, (cloud_workers) => ({ cloud_workers }))}
    {(scope === "all" || scope === "advanced") && select("Training Priority", "training_priority", "balanced", [["balanced", "Balanced"], ["training_first", "Training First"]])}
    {(scope === "all" || scope === "advanced") && toggle("Automatic Model Promotion", !!s.auto_deploy, (auto_deploy) => ({ auto_deploy }))}
    <p className="text-muted">Modes stay within configured resource limits. Training First still protects inference, memory and compute budgets. Paused training requires an explicit resume.</p>
  </div>;
}
