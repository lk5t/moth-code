import { useEffect, useState } from "react";
import { GitBranch, GitCommitHorizontal, RefreshCw } from "lucide-react";
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

export function ChangesPanel() {
  const project = useApp((s) => s.project);
  const [status, setStatus] = useState<GitStatus | null>(null);
  const [log, setLog] = useState<{ hash: string; subject: string; time: number }[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [diff, setDiff] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);

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
        <Button variant="ghost" size="icon-sm" onClick={load}><RefreshCw /></Button>
      </div>
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
