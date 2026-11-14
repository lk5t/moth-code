import { useEffect, useState } from "react";
import { DownloadCloud, GitBranch, GitCommitHorizontal, GitPullRequest, History, RefreshCw, Undo2, UploadCloud, UserPlus } from "lucide-react";
import { gh } from "@/lib/github";
import { openExternal } from "@/lib/external";
import { get, post } from "@/lib/backend";
import { useApp } from "@/lib/app-state";
import { useEvent } from "@/lib/events";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty";
import { cn, timeAgo } from "@/lib/utils";

interface GitStatus {
  available: boolean;
  repo: boolean;
  branch?: string;
  entries: { path: string; status: string }[];
}

const tone: Record<string, "success" | "warning" | "danger" | "default"> = {
  added: "success", untracked: "success", modified: "warning", deleted: "danger", conflict: "danger",
};

function GitChanges() {
  const project = useApp((s) => s.project);
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [log, setLog] = useState<{ hash: string; subject: string; time: number }[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [diff, setDiff] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

  const [ghNote, setGhNote] = useState<string | null>(null);
  const github = async (what: "push" | "pr" | "pull" | "invite") => {  // 1.0 GitHub connection: always on the user's click
    if (!project) return;
    try {
      if (what === "pull") {
        await gh(`/api/projects/${project.id}/github/pull`, {});
        setGhNote("Up to date with GitHub."); void load(); return;
      }
      if (what === "invite") {
        const user = prompt("Your friend's GitHub username — they can then clone this project and work on it with their own MOTH");
        if (!user) return;
        const r = await gh<{ invited: string; repo: string }>(`/api/projects/${project.id}/github/invite`, { username: user });
        setGhNote(`Invited ${r.invited} to ${r.repo}. They accept the invite on GitHub, then use “Clone from GitHub” on MOTH's home screen.`); return;
      }
      if (what === "push") {
        const r = await gh<{ repo: string; branch: string }>(`/api/projects/${project.id}/github/push`, {});
        setGhNote(`Pushed ${r.branch} to ${r.repo}.`);
      } else {
        const title = prompt("Pull request title", message || status?.branch || "");
        if (!title) return;
        const r = await gh<{ number: number; url: string }>(`/api/projects/${project.id}/github/pr`, { title, body: "Opened from MOTH Code." });
        setGhNote(`Opened pull request #${r.number}.`);
        if (r.url) void openExternal(r.url);
      }
    } catch (e) { setGhNote(String((e as Error).message ?? e)); }
  };
  const load = async () => {
    if (!project) return;
    try {
      const st = await get<GitStatus>(`/api/projects/${project.id}/git/status`);
      setStatus(st);
      if (st.repo) setLog(await get(`/api/projects/${project.id}/git/log?limit=15`));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    load();
  }, [project?.id]);
  useEvent("files", load);

  useEffect(() => {
    if (!project || !selected) return setDiff("");
    get<{ diff: string }>(`/api/projects/${project.id}/git/diff?path=${encodeURIComponent(selected)}`)
      .then((d) => setDiff(d.diff || "(no diff — file is untracked or unchanged)"))
      .catch((e) => setDiff(String(e)));
  }, [selected, status]);

  if (!project) return <EmptyState title="No workspace open" />;
  if (status && !status.available) return <EmptyState icon={<GitBranch />} title="Git not found">Install Git for Windows to enable change tracking.</EmptyState>;
  if (status && !status.repo)
    return (
      <EmptyState icon={<GitBranch />} title="Not a Git repository">
        <Button className="mt-2" size="sm" variant="outline" onClick={() => post(`/api/projects/${project.id}/git/init`).then(load)}>
          Initialize repository
        </Button>
      </EmptyState>
    );

  const commit = async () => {
    try {
      await post(`/api/projects/${project.id}/git/commit`, { message });
      setMessage("");
      load();
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 items-center justify-between border-b border-border px-3">
        <span className="flex items-center gap-1.5 text-xs text-muted"><GitBranch className="size-3.5" />{status?.branch ?? "…"}</span>
        <span className="flex items-center gap-1">
          <Button variant="ghost" size="sm" title="Get your collaborators' latest changes" onClick={() => void github("pull")}><DownloadCloud /> Pull</Button>
          <Button variant="ghost" size="sm" title="Push this branch to GitHub" onClick={() => void github("push")}><UploadCloud /> Push</Button>
          <Button variant="ghost" size="sm" title="Invite a friend to work on this project with you" onClick={() => void github("invite")}><UserPlus /> Share</Button>
          <Button variant="ghost" size="sm" title="Open a pull request on GitHub" onClick={() => void github("pr")}><GitPullRequest /> PR</Button>
          <Button variant="ghost" size="icon-sm" onClick={load}><RefreshCw /></Button>
        </span>
      </div>
      {ghNote && <div role="status" className="px-3 py-1.5 text-[11px] text-muted">{ghNote}</div>}
      {error && <div className="px-3 py-1.5 text-[11px] text-danger">{error}</div>}
      <div className="flex gap-2 border-b border-border p-2">
        <Input placeholder="Commit message" value={message} onChange={(e) => setMessage(e.target.value)} />
        <Button size="default" disabled={!message.trim() || !status?.entries.length} onClick={commit}>
          <GitCommitHorizontal /> Commit
        </Button>
      </div>
      <div className="max-h-[40%] overflow-auto border-b border-border py-1">
        {status?.entries.length === 0 && <div className="px-3 py-2 text-xs text-muted">Working tree clean</div>}
        {status?.entries.map((e) => (
          <div
            key={e.path}
            onClick={() => setSelected(e.path)}
            className={cn("flex h-6 cursor-pointer items-center justify-between px-3 text-xs text-muted hover:bg-surface-2", selected === e.path && "bg-accent-soft text-fg")}
          >
            <span className="truncate">{e.path}</span>
            <Badge variant={tone[e.status] ?? "default"}>{e.status}</Badge>
          </div>
        ))}
      </div>
      <pre className="selectable min-h-0 flex-1 overflow-auto p-3 font-mono text-[11.5px] leading-relaxed">
        {diff.split("\n").map((l, i) => (
          <div key={i} className={cn(l.startsWith("+") && !l.startsWith("+++") && "text-success", l.startsWith("-") && !l.startsWith("---") && "text-[#ff6b75]", l.startsWith("@@") && "text-faint")}>
            {l || " "}
          </div>
        ))}
        {!selected && log.length > 0 && (
          <div className="font-sans">
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Recent commits</div>
            {log.map((c) => (
              <div key={c.hash} className="flex justify-between gap-3 py-0.5 text-xs">
                <span className="truncate text-fg"><span className="mr-2 font-mono text-faint">{c.hash.slice(0, 7)}</span>{c.subject}</span>
                <span className="shrink-0 text-faint">{timeAgo(c.time)}</span>
              </div>
            ))}
          </div>
        )}
      </pre>
    </div>
  );
}


interface Checkpoint { task_id: string; goal: string; status: string; at: number; files: string[] }

/** 1.0 undo anything: every MOTH task that changed files is a point you can go back to (with or without Git). */
function Checkpoints() {
  const project = useApp((s) => s.project);
  const [points, setPoints] = useState<Checkpoint[]>([]);
  const [note, setNote] = useState<string | null>(null);
  const load = () => { if (project) get<Checkpoint[]>(`/api/checkpoints?project_id=${project.id}`).then(setPoints).catch(() => setPoints([])); };
  useEffect(load, [project?.id]);
  useEvent("task", (e) => { if (e.kind === "status") load(); });
  if (!project || !points.length) return null;
  const restore = async (p: Checkpoint) => {
    if (!confirm(`Go back to before “${p.goal.slice(0, 80)}”? This undoes that task and every later MOTH change.`)) return;
    try {
      const r = await post<{ restored: string[] }>("/api/checkpoints/restore", { project_id: project.id, task_id: p.task_id });
      setNote(`Restored ${r.restored.length} file(s).`); load();
    } catch (e) { setNote(String((e as Error).message ?? e)); }
  };
  return <section aria-label="MOTH checkpoints" className="border-b border-border px-3 py-2 text-xs">
    <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted"><History className="size-3.5" /> MOTH's changes</div>
    {note && <p role="status" className="mb-1 text-muted">{note}</p>}
    <ul className="stagger max-h-40 space-y-1 overflow-auto">{points.slice(0, 20).map((p) => <li key={p.task_id}
      className="lift flex items-center gap-2 rounded border border-border px-2 py-1">
      <span className="min-w-0 flex-1 truncate" title={p.files.join(", ")}>{p.goal}</span>
      <span className="shrink-0 text-faint">{timeAgo(p.at)} · {p.files.length} file(s)</span>
      <button className="shrink-0 cursor-pointer text-muted hover:text-fg" title="Go back to before this change" onClick={() => void restore(p)}><Undo2 className="size-3.5" /></button>
    </li>)}</ul>
  </section>;
}

export function ChangesPanel() {
  return <div className="flex min-h-0 flex-1 flex-col"><Checkpoints /><GitChanges /></div>;
}
