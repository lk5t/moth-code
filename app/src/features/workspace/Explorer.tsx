import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, FilePlus, FolderOpen, FolderPlus, RefreshCw, Trash2 } from "lucide-react";
import { get, post, put } from "@/lib/backend";
import { appStore, useApp } from "@/lib/app-state";
import { useEvent } from "@/lib/events";
import { Button } from "@/components/ui/button";
import { Tip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { openFile, refreshOpenFile } from "./workspace-actions";

interface Entry {
  path: string;
  dir: boolean;
}

interface Node {
  name: string;
  path: string;
  dir: boolean;
  children: Node[];
}

function buildTree(entries: Entry[]): Node[] {
  const root: Node = { name: "", path: "", dir: true, children: [] };
  const index = new Map<string, Node>([["", root]]);
  for (const e of entries) {
    const parts = e.path.split("/");
    const name = parts[parts.length - 1];
    const parent = index.get(parts.slice(0, -1).join("/")) ?? root;
    const node: Node = { name, path: e.path, dir: e.dir, children: [] };
    parent.children.push(node);
    if (e.dir) index.set(e.path, node);
  }
  const sort = (n: Node) => {
    n.children.sort((a, b) => (a.dir === b.dir ? a.name.localeCompare(b.name) : a.dir ? -1 : 1));
    n.children.forEach(sort);
  };
  sort(root);
  return root.children;
}

export function Explorer({ onOpenProject }: { onOpenProject: () => void }) {
  const project = useApp((s) => s.project);
  const activeFile = useApp((s) => s.activeFile);
  const version = useApp((s) => s.treeVersion);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    if (!project) return;
    try {
      setEntries(await get<Entry[]>(`/api/projects/${project.id}/tree`));
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  };

  useEffect(() => {
    load();
  }, [project?.id, version]);

  useEvent("files", (e) => {
    if (e.project_id === project?.id) {
      load();
      if (e.path) refreshOpenFile(e.path);
    }
  });

  const tree = useMemo(() => buildTree(entries), [entries]);

  const toggle = (p: string) =>
    setExpanded((s) => {
      const n = new Set(s);
      n.has(p) ? n.delete(p) : n.add(p);
      return n;
    });

  const parentDir = () => {
    if (!selected) return "";
    const entry = entries.find((e) => e.path === selected);
    return entry?.dir ? selected : selected.split("/").slice(0, -1).join("/");
  };

  const create = async (dir: boolean) => {
    if (!project) return;
    const name = window.prompt(dir ? "New folder name" : "New file name");
    if (!name) return;
    const path = [parentDir(), name].filter(Boolean).join("/");
    if (dir) await post(`/api/projects/${project.id}/fs`, { op: "mkdir", path });
    else {
      await put(`/api/projects/${project.id}/file`, { path, content: "" });
      await openFile(path);
    }
    load();
  };

  const remove = async () => {
    if (!project || !selected) return;
    if (!window.confirm(`Delete ${selected}? This cannot be undone.`)) return;
    await post(`/api/projects/${project.id}/fs`, { op: "delete", path: selected });
    setSelected(null);
  };

  if (!project) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 p-4 text-center">
        <FolderOpen className="size-6 text-faint" />
        <div className="text-xs text-muted">No workspace open</div>
        <Button size="sm" variant="outline" onClick={onOpenProject}>
          Open folder
        </Button>
      </div>
    );
  }

  const renderNode = (n: Node, depth: number): React.ReactNode => {
    const isOpen = expanded.has(n.path);
    return (
      <div key={n.path}>
        <div
          className={cn(
            "group flex h-[22px] cursor-pointer items-center gap-1 pr-2 text-[12.5px] text-muted hover:bg-surface-2 hover:text-fg",
            (selected === n.path || activeFile === n.path) && "bg-accent-soft text-fg",
          )}
          style={{ paddingLeft: 8 + depth * 12 }}
          onClick={() => {
            setSelected(n.path);
            n.dir ? toggle(n.path) : openFile(n.path).catch((e) => setError(String(e)));
          }}
        >
          {n.dir ? (
            isOpen ? <ChevronDown className="size-3 shrink-0" /> : <ChevronRight className="size-3 shrink-0" />
          ) : (
            <span className="w-3 shrink-0" />
          )}
          <span className="truncate">{n.name}</span>
        </div>
        {n.dir && isOpen && n.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 items-center justify-between border-b border-border pl-3 pr-1">
        <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-muted" title={project.path}>
          {project.name}
        </span>
        <div className="flex">
          <Tip label="New file" side="bottom">
            <Button variant="ghost" size="icon-sm" onClick={() => create(false)}><FilePlus /></Button>
          </Tip>
          <Tip label="New folder" side="bottom">
            <Button variant="ghost" size="icon-sm" onClick={() => create(true)}><FolderPlus /></Button>
          </Tip>
          <Tip label="Delete selected" side="bottom">
            <Button variant="ghost" size="icon-sm" onClick={remove} disabled={!selected}><Trash2 /></Button>
          </Tip>
          <Tip label="Refresh" side="bottom">
            <Button variant="ghost" size="icon-sm" onClick={() => appStore.setState((s) => ({ treeVersion: s.treeVersion + 1 }))}><RefreshCw /></Button>
          </Tip>
        </div>
      </div>
      {error && <div className="px-3 py-2 text-[11px] text-danger">{error}</div>}
      <div className="flex-1 overflow-auto py-1">{tree.map((n) => renderNode(n, 0))}</div>
    </div>
  );
}
