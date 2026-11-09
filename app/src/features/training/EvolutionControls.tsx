import { Switch } from "@/components/ui/switch";

type Settings = Record<string, any>;
/** Mounted only in Owner views; the existing API independently enforces Owner reauthentication. */
export function EvolutionControls({ settings: s, onChange }: { settings: Settings; onChange: (changes: Settings) => void }) {
  const toggle = (label: string, checked: boolean, changes: (v: boolean) => Settings) =>
    <label className="flex items-center justify-between gap-4"><span>{label}</span>
      <Switch aria-label={label} checked={checked} onCheckedChange={(v) => onChange(changes(v))} /></label>;
  const select = (label: string, key: string, fallback: string, choices: [string, string][]) =>
    <label className="flex items-center justify-between gap-4"><span>{label}</span>
      <select aria-label={label} className="h-8 rounded-md border border-border bg-bg px-2" value={s[key] ?? fallback}
        onChange={(e) => onChange({ [key]: e.target.value })}>{choices.map(([v, text]) => <option key={v} value={v}>{text}</option>)}</select></label>;
  return <div className="flex flex-col gap-3 text-xs">
    {toggle("Automatic Evolution", !!s.enabled, (enabled) => ({ enabled }))}
    {select("Training Mode", "training_mode", "automatic", [["automatic", "Automatic"], ["maximum", "Maximum Performance"], ["eco", "Eco"]])}
    {toggle("Use cloud workers", s.cloud_workers !== false, (cloud_workers) => ({ cloud_workers }))}
    {select("Training Priority", "training_priority", "balanced", [["balanced", "Balanced"], ["training_first", "Training First"]])}
    {toggle("Automatic Model Promotion", !!s.auto_deploy, (auto_deploy) => ({ auto_deploy }))}
    <p className="text-muted">Modes stay within configured resource limits. Training First still protects inference, memory and compute budgets. Paused training requires an explicit resume.</p>
  </div>;
}
