import { useEffect, useRef, useState } from "react";
import { KeyRound, Monitor, UserRound } from "lucide-react";
import { accountStore, refreshMe, serverApi, useAccount } from "@/lib/account";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { timeAgo } from "@/lib/utils";
import { Avatar } from "./Avatar";
import { openAccountDialog } from "./AccountDialog";

interface SessionRow { id: number; device_name: string | null; user_agent: string; ip: string; created_at: number; last_used_at: number; current: boolean }

export function AccountSection() {
  const user = useAccount((s) => s.user);
  const [displayName, setDisplayName] = useState("");
  const [pw, setPw] = useState({ current: "", next: "" });
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const loadSessions = () => serverApi<SessionRow[]>("/v1/auth/sessions").then(setSessions).catch(() => {});
  useEffect(() => {
    setDisplayName(user?.display_name ?? "");
    if (user) loadSessions();
  }, [user?.id]);

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(null);
    try {
      await fn();
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><UserRound className="size-4 text-accent" />MOTH account</CardTitle>
        <CardDescription>
          Your MOTH account lives in MOTH Cloud. You stay signed in on this computer (the session is kept in Windows
          Credential Manager and renewed automatically). The editor, terminal and Git work without signing in.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {!user ? (
          <div className="flex gap-2">
            <Button onClick={() => openAccountDialog("login")}>Sign in</Button>
            <Button variant="secondary" onClick={() => openAccountDialog("register")}>Create account</Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-4 rounded-lg border border-border p-3">
              <button className="cursor-pointer rounded-full hover:shadow-glow" title="Change avatar" onClick={() => file.current?.click()}>
                <Avatar name={user.username} url={user.avatar_url} size={56} />
              </button>
              <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                const form = new FormData();
                form.append("file", f);
                run(async () => accountStore.setState({ user: await serverApi("/v1/me/avatar", { method: "PUT", body: form }) }), "Avatar updated.");
              }} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 text-sm font-medium">@{user.username} {user.role === "owner" && <Badge variant="accent">Owner</Badge>}</div>
                <div className="text-xs text-muted">{user.email} · {user.email_verified ? "verified" : "not verified"} · plan {user.plan}</div>
              </div>
            </div>
            <div className="flex items-end gap-2">
              <div className="flex-1"><Label>Display name</Label><Input className="mt-1" value={displayName} onChange={(e) => setDisplayName(e.target.value)} /></div>
              <Button variant="secondary" onClick={() => run(async () => { await serverApi("/v1/me", { method: "PATCH", json: { display_name: displayName } }); await refreshMe(); }, "Profile saved.")}>Save</Button>
            </div>
            <div>
              <Label className="flex items-center gap-1.5"><KeyRound className="size-3" />Change password</Label>
              <div className="mt-1 flex gap-2">
                <Input type="password" placeholder="Current password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
                <Input type="password" placeholder="New password (10+ characters)" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" />
                <Button variant="secondary" disabled={!pw.current || !pw.next} onClick={() => run(async () => {
                  await serverApi("/v1/me/password", { method: "POST", json: { current_password: pw.current, new_password: pw.next } });
                  setPw({ current: "", next: "" });
                  loadSessions();
                }, "Password changed. Other sessions were signed out.")}>Update</Button>
              </div>
            </div>
            <div>
              <div className="flex items-center justify-between">
                <Label className="flex items-center gap-1.5"><Monitor className="size-3" />Active sessions</Label>
                <button className="cursor-pointer text-[11px] text-muted hover:text-fg" onClick={() => run(async () => { await serverApi("/v1/auth/sessions/revoke-others", { method: "POST" }); loadSessions(); }, "Signed out everywhere else.")}>Sign out other sessions</button>
              </div>
              <div className="mt-1 space-y-1">
                {sessions.map((s) => (
                  <div key={s.id} className="flex items-center justify-between rounded-md border border-border px-2.5 py-1.5 text-xs">
                    <span className="truncate">{s.device_name || s.user_agent || "Unknown device"} <span className="text-faint">· {s.ip} · active {timeAgo(s.last_used_at)}</span></span>
                    {s.current ? <Badge variant="success">this device</Badge> : (
                      <button className="cursor-pointer text-muted hover:text-danger" onClick={() => serverApi(`/v1/auth/sessions/${s.id}`, { method: "DELETE" }).then(loadSessions)}>Revoke</button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
        {msg && <div className={msg.ok ? "text-xs text-success" : "text-xs text-danger"}>{msg.text}</div>}
      </CardContent>
    </Card>
  );
}
