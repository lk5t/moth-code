/** 2.4: "Report a problem" (anyone) and the reports list (Owner). The app gathers its own recent logs and
 * status so the Owner sees what happened; nothing is sent until you press Send. */
import { useState } from "react";
import { Bug, Send } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { fetchBackendInfo, get } from "@/lib/backend";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { timeAgo } from "@/lib/utils";

type Any = Record<string, any>;
const APP_VERSION = (import.meta.env.VITE_APP_VERSION as string | undefined) ?? "dev";

async function gather(): Promise<Any> {
  const out: Any = { app_version: APP_VERSION, platform: navigator.userAgent, screen: `${window.innerWidth}×${window.innerHeight}` };
  try { const b = await fetchBackendInfo(); out.backend_status = b.status; out.backend_logs = (b.logs ?? []).slice(-200); } catch (e) { out.backend_error = String(e); }
  try { out.participant = await get<Any>("/api/participant"); } catch { /* not available */ }
  try { out.recent_activity = (await get<Any[]>("/api/activity")).slice(0, 30); } catch { /* not available */ }
  return out;
}

export function ReportProblem() {
  const signedIn = useAccount((s) => !!s.token);
  const [text, setText] = useState(""), [busy, setBusy] = useState(false), [note, setNote] = useState<string | null>(null);
  const send = async () => {
    setBusy(true); setNote(null);
    try {
      const details = await gather();
      await serverApi("/v1/problem-reports", { method: "POST", json: { message: text.trim(), app_version: APP_VERSION, details } });
      setText(""); setNote("Sent. Thank you, the Owner can see it with this app's recent logs.");
    } catch (e) { setNote((e as Error).message); } finally { setBusy(false); }
  };
  return <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2"><Bug className="size-4 text-accent" />Report a problem</CardTitle>
      <CardDescription>Say what went wrong. The report includes this app's version, its recent logs and training status (no chats, no files).</CardDescription>
    </CardHeader>
    <CardContent className="space-y-2">
      <Textarea aria-label="What went wrong" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Training stopped at round 1 and the chat froze when I attached a screenshot."
        className="rounded-md border border-border bg-bg px-2.5 py-2 text-xs" />
      <div className="flex items-center gap-2">
        <Button size="sm" disabled={!signedIn || busy || !text.trim()} onClick={() => void send()}><Send />{busy ? "Sending…" : "Send report"}</Button>
        {!signedIn && <span className="text-xs text-muted">Sign in to send a report.</span>}
        {note && <span role="status" className="text-xs text-muted">{note}</span>}
      </div>
    </CardContent>
  </Card>;
}

export function ProblemReportsList() {
  const server = useAccount((s) => s.serverUrl), token = useAccount((s) => s.token);
  const { data } = useResource<Any[]>("/v1/admin/problem-reports", [], [], server + "\0" + token, (u) => serverApi<Any[]>(u));
  const [open, setOpen] = useState<Any | null>(null);
  return <Card>
    <CardHeader><CardTitle>Problem reports</CardTitle><CardDescription>Sent from the app by your users (newest first).</CardDescription></CardHeader>
    <CardContent className="space-y-1 text-xs">
      {(data ?? []).map((r) => <button key={r.id} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-2"
        onClick={() => serverApi<Any>(`/v1/admin/problem-reports/${r.id}`).then(setOpen).catch(() => {})}>
        <span className="min-w-0 flex-1 truncate text-fg">{r.message}</span>
        <span className="shrink-0 text-faint">{r.username} · {r.app_version ?? "?"} · {timeAgo(r.at)}</span></button>)}
      {!data?.length && <p className="text-muted">No reports.</p>}
      {open && <div className="mt-2 rounded-md border border-border p-2">
        <div className="mb-1 flex justify-between"><span className="text-fg">{open.message}</span><button className="text-muted hover:text-fg" onClick={() => setOpen(null)}>Close</button></div>
        <pre className="selectable max-h-80 overflow-auto whitespace-pre-wrap font-mono text-[0.6875rem] text-muted">{JSON.stringify(open.details, null, 2)}</pre>
      </div>}
    </CardContent>
  </Card>;
}
