/**
 * 1.0.18 Settings → Servers & engagements.
 *
 * Servers: saved SSH profiles the agent can run commands on (always with your approval). No passwords are
 * stored; the system's ssh uses your own keys or SSH agent.
 * Engagements: the authorized scope of a security test. While one is active, MOTH refuses any command that
 * targets something outside it, and logs every command it runs for the report.
 */
import { useEffect, useState } from "react";
import { Server, ShieldCheck, Trash2 } from "lucide-react";
import { del, get, post, put } from "@/lib/backend";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Label, Textarea } from "@/components/ui/input";
import { timeAgo } from "@/lib/utils";

type ServerRow = { name: string; host: string; user: string; port: number; key_path: string | null };
type Engagement = { id: string; name: string; scope: string[]; starts_at: number | null; ends_at: number | null; notes: string };
type LogRow = { at: number; where: string; command: string; ok: boolean; exit_code: number | null; output_tail: string };

export function parseScope(text: string): string[] {
  return text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
}

export function ServersSection() {
  const [servers, setServers] = useState<ServerRow[]>([]);
  const [engs, setEngs] = useState<{ engagements: Engagement[]; active: string | null }>({ engagements: [], active: null });
  const [err, setErr] = useState<string | null>(null);
  const [srv, setSrv] = useState({ name: "", host: "", user: "", port: "22", key_path: "" });
  const [eng, setEng] = useState({ name: "", scope: "", ends: "" });
  const [log, setLog] = useState<{ id: string; rows: LogRow[] } | null>(null);
  const load = () => {
    get<ServerRow[]>("/api/servers").then(setServers).catch((e) => setErr(e.message));
    get<{ engagements: Engagement[]; active: string | null }>("/api/engagements").then(setEngs).catch((e) => setErr(e.message));
  };
  useEffect(load, []);
  const act = (fn: () => Promise<unknown>) => { setErr(null); fn().then(load).catch((e) => setErr((e as Error).message)); };

  return <>
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Server className="size-4 text-accent" />Servers</CardTitle>
        <CardDescription>Servers MOTH's agent can work on over SSH. Every command is shown to you and needs your
          approval. No passwords are stored: your own SSH keys or SSH agent are used.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {servers.length ? <ul className="flex flex-col gap-1 text-xs">{servers.map((s) =>
          <li key={s.name} className="flex items-center justify-between gap-2 rounded-md border border-border px-2 py-1.5">
            <span><span className="font-medium text-fg">{s.name}</span> <span className="text-muted">{s.user}@{s.host}:{s.port}{s.key_path ? " · key file" : ""}</span></span>
            <Button size="icon-sm" variant="ghost" aria-label={`Remove server ${s.name}`} onClick={() => act(() => del(`/api/servers/${encodeURIComponent(s.name)}`))}><Trash2 /></Button>
          </li>)}</ul> : <p className="text-xs text-muted">No servers yet.</p>}
        <div className="grid gap-2 sm:grid-cols-5">
          <div><Label>Name</Label><Input aria-label="Server name" value={srv.name} onChange={(e) => setSrv({ ...srv, name: e.target.value })} placeholder="web-1" /></div>
          <div className="sm:col-span-2"><Label>Host</Label><Input aria-label="Server host" value={srv.host} onChange={(e) => setSrv({ ...srv, host: e.target.value })} placeholder="203.0.113.7" /></div>
          <div><Label>User</Label><Input aria-label="Server user" value={srv.user} onChange={(e) => setSrv({ ...srv, user: e.target.value })} placeholder="deploy" /></div>
          <div><Label>Port</Label><Input aria-label="Server port" value={srv.port} onChange={(e) => setSrv({ ...srv, port: e.target.value })} /></div>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-64 flex-1"><Label>SSH key file (optional)</Label><Input aria-label="SSH key file" value={srv.key_path} onChange={(e) => setSrv({ ...srv, key_path: e.target.value })} placeholder="~/.ssh/id_ed25519" /></div>
          <Button disabled={!srv.name || !srv.host || !srv.user} onClick={() => act(() => post("/api/servers", { ...srv, port: Number(srv.port) || 22, key_path: srv.key_path || null })
            .then(() => setSrv({ name: "", host: "", user: "", port: "22", key_path: "" })))}>Save server</Button>
        </div>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><ShieldCheck className="size-4 text-accent" />Engagements</CardTitle>
        <CardDescription>The authorized scope of a security test. While an engagement is active, MOTH refuses any
          command that targets a host, IP or domain outside it (or outside its time window), and logs every command
          it runs. With no engagement active, coding and server work run as usual.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {engs.engagements.length ? <ul className="flex flex-col gap-1.5 text-xs">{engs.engagements.map((e) => {
          const on = engs.active === e.id;
          return <li key={e.id} className="rounded-md border border-border px-2 py-1.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-fg">{e.name} {on && <Badge variant="accent">active</Badge>}</span>
              <span className="flex gap-1">
                <Button size="sm" variant={on ? "secondary" : "outline"} onClick={() => act(() => put("/api/engagements/active", { id: on ? null : e.id }))}>{on ? "Deactivate" : "Activate"}</Button>
                <Button size="sm" variant="outline" onClick={() => get<LogRow[]>(`/api/engagements/${e.id}/log?limit=100`).then((rows) => setLog({ id: e.id, rows }))}>Log</Button>
                <Button size="icon-sm" variant="ghost" aria-label={`Delete engagement ${e.name}`} onClick={() => confirm(`Delete engagement ${e.name}?`) && act(() => del(`/api/engagements/${e.id}`))}><Trash2 /></Button>
              </span>
            </div>
            <div className="mt-0.5 text-muted">Scope: {e.scope.join(", ")}{e.ends_at ? ` · ends ${new Date(e.ends_at * 1000).toLocaleString()}` : ""}</div>
            {log?.id === e.id && <pre className="mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap rounded border border-border bg-bg p-2 font-mono text-[10.5px] text-fg">
              {log.rows.length ? log.rows.map((r) => `${timeAgo(r.at)} · ${r.where} · ${r.ok ? "ok" : "refused/failed"} · ${r.command}`).join("\n") : "Nothing logged yet."}</pre>}
          </li>;
        })}</ul> : <p className="text-xs text-muted">No engagements yet.</p>}
        <div className="grid gap-2 sm:grid-cols-3">
          <div><Label>Name</Label><Input aria-label="Engagement name" value={eng.name} onChange={(e) => setEng({ ...eng, name: e.target.value })} placeholder="Acme web test" /></div>
          <div><Label>Ends (optional)</Label><Input aria-label="Engagement end" type="datetime-local" value={eng.ends} onChange={(e) => setEng({ ...eng, ends: e.target.value })} /></div>
        </div>
        <div><Label>Scope: hosts, IPs, ranges (CIDR) and domains (*.example.com includes subdomains)</Label>
          <Textarea aria-label="Engagement scope" rows={3} value={eng.scope} onChange={(e) => setEng({ ...eng, scope: e.target.value })} placeholder={"10.0.0.0/24\n*.acme-test.com"} /></div>
        <div><Button disabled={!eng.name || !parseScope(eng.scope).length} onClick={() => act(() => post("/api/engagements", {
          name: eng.name, scope: parseScope(eng.scope), ends_at: eng.ends ? new Date(eng.ends).getTime() / 1000 : null,
        }).then(() => setEng({ name: "", scope: "", ends: "" })))}>Create engagement</Button></div>
      </CardContent>
    </Card>
    {err && <p className="text-xs text-danger">{err}</p>}
  </>;
}
