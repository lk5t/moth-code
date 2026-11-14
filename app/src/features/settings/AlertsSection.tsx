/**
 * 0.10.0: desktop alerts and the tray icon (lib/alerts.ts). Per computer, so they live in this app.
 */
import { useState } from "react";
import { BellRing } from "lucide-react";
import { alertPrefs, setAlertPrefs, type AlertPrefs } from "@/lib/alerts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Switch } from "@/components/ui/switch";

const ROWS: [keyof AlertPrefs, string, string][] = [
  ["notifications", "Desktop notifications", "When MOTH is promoted, finishes its successor or needs a look."],
  ["keepInTray", "Keep running in the tray when closed", "Closing the window hides MOTH Code next to the clock; alerts keep arriving. Quit from the tray icon."],
  ["infoAlerts", "Also notify about smaller news", "New training data, workers joining or leaving, finished cycles."],
  ["sounds", "Sounds", "A soft click when you send, a chime when MOTH finishes, a flourish when it gets smarter."],
];

export function AlertsSection() {
  const [p, setP] = useState(alertPrefs);
  const set = (k: keyof AlertPrefs, v: boolean) => { setAlertPrefs({ [k]: v }); setP(alertPrefs()); };
  return <Card><CardHeader><CardTitle className="flex items-center gap-2"><BellRing className="size-4 text-accent" />Alerts</CardTitle>
    <CardDescription>MOTH tells you when something worth seeing happens (Owner account).</CardDescription></CardHeader>
    <CardContent className="flex flex-col gap-3">{ROWS.map(([k, label, hint]) =>
      <label key={k} className="flex cursor-pointer items-start justify-between gap-4 text-xs">
        <span><span className="text-fg">{label}</span><span className="mt-0.5 block text-muted">{hint}</span></span>
        <Switch checked={p[k]} onCheckedChange={(v) => set(k, v)} aria-label={label} />
      </label>)}</CardContent></Card>;
}
