import { useState } from "react";
import { Wrench } from "lucide-react";
import { setServerUrl, useAccount } from "@/lib/account";
import { checkNow, useConnection } from "@/lib/connection";
import { MOTH_ENV, developerMode, developerOverride, officialServer, setDeveloperMode } from "@/lib/endpoint";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Row } from "./SettingsView";

/** Hidden by default: connection details and the developer-only server override. */
export function AdvancedSection() {
  const [open, setOpen] = useState(false);
  const [dev, setDev] = useState(developerMode());
  const [override, setOverride] = useState(developerOverride() ?? "");
  const [msg, setMsg] = useState<string | null>(null);
  const serverUrl = useAccount((s) => s.serverUrl);
  const conn = useConnection((s) => s);
  if (!open) {
    return (
      <button className="cursor-pointer self-start text-xs text-faint hover:text-fg" onClick={() => setOpen(true)}>
        Show advanced settings
      </button>
    );
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Wrench className="size-4 text-accent" />Advanced</CardTitle>
        <CardDescription>Connection details. You don't need to change anything here.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 text-xs">
        <Row title="MOTH Cloud" desc={`${serverUrl || "not configured"} · ${MOTH_ENV}`}>
          <span className="text-muted">{conn.status}{conn.serverVersion ? ` · server ${conn.serverVersion}` : ""}{conn.latencyMs != null ? ` · ${conn.latencyMs} ms` : ""}</span>
        </Row>
        {MOTH_ENV === "production" && (
          <Row title="Developer mode" desc="Allows connecting to a test server. For MOTH developers only.">
            <Switch checked={dev} onCheckedChange={(v) => { setDeveloperMode(v); setDev(v); if (!v) { setServerUrl(""); setOverride(""); } }} />
          </Row>
        )}
        {dev && (
          <div className="flex items-end gap-2 py-2">
            <Input className="h-8 flex-1 text-xs" placeholder={officialServer() || "http://127.0.0.1:8900"} value={override}
              onChange={(e) => setOverride(e.target.value)} />
            <Button size="sm" variant="secondary" onClick={() => {
              try {
                setServerUrl(override.trim());
                setMsg(override.trim() ? "Using the test server." : "Back to the official MOTH Cloud.");
                checkNow();
              } catch (e) {
                setMsg((e as Error).message);
              }
            }}>Use</Button>
          </div>
        )}
        {msg && <span className="text-muted">{msg}</span>}
      </CardContent>
    </Card>
  );
}
