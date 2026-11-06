import { useEffect, useState } from "react";
import { Globe, RotateCcw } from "lucide-react";
import { probeServer, switchServer, useAccount, type ServerProbe } from "@/lib/account";
import { checkNow, useConnection } from "@/lib/connection";
import { MOTH_ENV, officialServer, userServer } from "@/lib/endpoint";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/** Settings → Connection: which MOTH Cloud server this app uses. Changing it needs no rebuild. */
export function ConnectionSection() {
  const serverUrl = useAccount((s) => s.serverUrl);
  const conn = useConnection((s) => s);
  const [value, setValue] = useState(serverUrl);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const builtIn = officialServer();
  const custom = !!userServer() && userServer() !== builtIn;
  useEffect(() => setValue(serverUrl), [serverUrl]);

  const apply = async (target: string) => {
    setBusy(true);
    setMsg(null);
    try {
      const probe: ServerProbe = await probeServer(target || builtIn);
      if (!probe.ok) {
        setMsg({ ok: false, text: probe.error ?? "That address can't be used." });
        return;
      }
      const { keptSession } = await switchServer(target);
      checkNow();
      setMsg({ ok: true, text: `Connected to MOTH Cloud ${probe.version} at ${probe.url}. ` +
        (keptSession ? "You're still signed in." : "Sign in to continue on this server.") });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const statusText = {
    online: `connected${conn.serverVersion ? ` · MOTH Cloud ${conn.serverVersion}` : ""}${conn.latencyMs != null ? ` · ${conn.latencyMs} ms` : ""}`,
    connecting: "connecting…", reconnecting: "reconnecting…", offline: "can't reach the server — retrying automatically",
    unconfigured: "no server address set",
  }[conn.status];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Globe className="size-4 text-accent" />Connection</CardTitle>
        <CardDescription>
          The MOTH Cloud server this app uses for your account, chat, the agent and updates.
          {builtIn ? ` The built-in address is ${builtIn}.` : ""} You can switch to another address at any time; it is
          checked before it is used.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs">
        <div className="flex items-center gap-2">
          <span className={cn("size-2 rounded-full", conn.status === "online" ? "bg-success" : conn.status === "offline" ? "bg-danger" : "bg-warning")} />
          <span className="text-muted">{serverUrl || "—"} · {statusText}</span>
        </div>
        <form className="flex items-center gap-2" onSubmit={(e) => { e.preventDefault(); apply(value.trim()); }}>
          <Input className="h-8 flex-1 text-xs" placeholder="https://moth.example.com" value={value}
            onChange={(e) => setValue(e.target.value)} aria-label="MOTH Cloud server address" />
          <Button size="sm" type="submit" disabled={busy || !value.trim()}>{busy ? "Checking…" : "Test & use"}</Button>
          {custom && builtIn && (
            <Button size="sm" variant="ghost" type="button" disabled={busy} onClick={() => apply("")}><RotateCcw /> Use default</Button>
          )}
        </form>
        {msg && <span className={msg.ok ? "text-success" : "text-danger"}>{msg.text}</span>}
        {MOTH_ENV !== "production" && <span className="text-faint">Build environment: {MOTH_ENV}</span>}
      </CardContent>
    </Card>
  );
}
