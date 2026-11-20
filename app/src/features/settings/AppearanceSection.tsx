import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { ACCENTS, ACCENT_RGB, THEMES, THEME_LABEL, setTheme, useTheme } from "@/lib/theme";
import { UI_SIZES, UI_SIZE_LABEL, setUiSize, useUiSize } from "@/lib/ui-size";
import { setMotion, useMotion } from "@/lib/motion";
import { Row } from "./SettingsView";

const DESC = { compact: "More fits on screen (default)", normal: "How MOTH 1.x looked", large: "Bigger text and buttons" } as const;

/** 2.0: app size and animations. */
export function AppearanceSection() {
  const size = useUiSize();
  const motion = useMotion();
  return <Card>
    <CardHeader>
      <CardTitle>Appearance</CardTitle>
      <CardDescription>Ctrl + and Ctrl − change the size from anywhere, Ctrl 0 goes back to Compact.</CardDescription>
    </CardHeader>
    <CardContent>
      <div role="radiogroup" aria-label="App size" className="grid grid-cols-3 gap-2">
        {UI_SIZES.map((s) => <button key={s} role="radio" aria-checked={size === s} onClick={() => setUiSize(s)}
          className={cn("lift rounded-lg border p-3 text-left", size === s ? "border-accent bg-accent-soft shadow-glow" : "border-border bg-surface-2")}>
          <div className={cn("font-medium", s === "compact" ? "text-xs" : s === "normal" ? "text-sm" : "text-base")}>{UI_SIZE_LABEL[s]}</div>
          <div className="mt-0.5 text-[0.6875rem] text-muted">{DESC[s]}</div>
        </button>)}
      </div>
      <ThemePicker />
      <div className="mt-3">
        <Row title="Animations" desc="Smooth motion across the app. Always off when Windows has animations turned off.">
          <Switch checked={motion} onCheckedChange={setMotion} aria-label="Animations" />
        </Row>
      </div>
    </CardContent>
  </Card>;
}

/** 2.4: colour theme and accent colour. */
function ThemePicker() {
  const t = useTheme();
  return <div className="mt-4 space-y-3">
    <div>
      <div className="mb-1.5 text-xs text-muted">Theme</div>
      <div role="radiogroup" aria-label="Theme" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {THEMES.map((th) => <button key={th} role="radio" aria-checked={t.theme === th} onClick={() => setTheme({ theme: th })}
          className={cn("lift rounded-lg border p-2 text-left text-xs", t.theme === th ? "border-accent shadow-glow" : "border-border")}>
          <span className={cn("mb-1.5 block h-6 rounded", th === "light" ? "bg-[#f0f0f2] ring-1 ring-[#dcdce1]" : th === "midnight" ? "bg-[#0e1320]" : th === "graphite" ? "bg-[#2a2a2f]" : "bg-[#141414]")} />
          {THEME_LABEL[th]}</button>)}
      </div>
    </div>
    <div>
      <div className="mb-1.5 text-xs text-muted">Accent colour</div>
      <div role="radiogroup" aria-label="Accent colour" className="flex gap-2">
        {ACCENTS.map((a) => <button key={a} role="radio" aria-checked={t.accent === a} aria-label={a} title={a} onClick={() => setTheme({ accent: a })}
          style={{ background: ACCENT_RGB[a][0] }} className={cn("size-7 rounded-full transition-transform hover:scale-110", t.accent === a && "ring-2 ring-fg ring-offset-2 ring-offset-bg")} />)}
      </div>
    </div>
  </div>;
}
