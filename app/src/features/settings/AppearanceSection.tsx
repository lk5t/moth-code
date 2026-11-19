import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
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
      <div className="mt-3">
        <Row title="Animations" desc="Smooth motion across the app. Always off when Windows has animations turned off.">
          <Switch checked={motion} onCheckedChange={setMotion} aria-label="Animations" />
        </Row>
      </div>
    </CardContent>
  </Card>;
}
