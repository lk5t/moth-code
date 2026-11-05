import { useState } from "react";
import { BookMarked, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { del, post } from "@/lib/backend";
import { useApp } from "@/lib/app-state";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input, Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty";
import { timeAgo } from "@/lib/utils";

interface Memory { id: number; kind: string; title: string; content: string; verified: number; updated_at: number }

/** Local, per-project memory MOTH uses as context. Never uploaded. */
export function MemoryPanel() {
  const project = useApp((s) => s.project);
  const [kind, setKind] = useState("");
  const { data, reload } = useResource<Memory[]>(project ? `/api/memory?project_id=${project.id}${kind ? `&kind=${kind}` : ""}` : null, ["task"], []);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ kind: "preference", title: "", content: "" });
  if (!project) return <EmptyState title="No workspace open" />;

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-9 items-center gap-2 border-b border-border px-2">
        <Select className="h-7 text-xs" value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">All memory</option>
          {["architecture", "preference", "solution", "error", "note"].map((k) => <option key={k} value={k}>{k}</option>)}
        </Select>
        <div className="flex-1" />
        <Button size="sm" variant="ghost" onClick={() => setAdding(!adding)}><Plus /> Add</Button>
      </div>
      {adding && (
        <div className="flex flex-col gap-2 border-b border-border p-2">
          <div className="flex gap-2">
            <Select className="h-8 text-xs" value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
              {["preference", "architecture", "note"].map((k) => <option key={k}>{k}</option>)}
            </Select>
            <Input placeholder="Title (e.g. Code style)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </div>
          <Textarea rows={3} placeholder="e.g. Use type hints and pytest; keep functions small." value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} />
          <Button size="sm" disabled={!form.title || !form.content} onClick={async () => {
            await post("/api/memory", { project_id: project.id, ...form });
            setForm({ kind: "preference", title: "", content: "" });
            setAdding(false);
            reload();
          }}>Save memory</Button>
        </div>
      )}
      <div className="flex-1 overflow-auto p-2">
        {!data?.length && <EmptyState icon={<BookMarked />} title="No memories yet">MOTH records the project overview, verified solutions and errors here. Add your coding preferences too.</EmptyState>}
        {data?.map((m) => (
          <div key={m.id} className="group mb-1.5 rounded-md border border-border p-2 text-xs hover:border-border-strong">
            <div className="flex items-center gap-1.5">
              <Badge variant={m.kind === "error" ? "danger" : m.kind === "solution" ? "success" : "default"}>{m.kind}</Badge>
              {!!m.verified && <span title="verified"><ShieldCheck className="size-3 text-success" /></span>}
              <span className="truncate font-medium">{m.title}</span>
              <span className="ml-auto shrink-0 text-[10px] text-faint">{timeAgo(m.updated_at)}</span>
              <button className="hidden cursor-pointer text-muted hover:text-danger group-hover:block" onClick={() => del(`/api/memory/${m.id}`).then(reload)}><Trash2 className="size-3" /></button>
            </div>
            <div className="selectable mt-1 line-clamp-4 whitespace-pre-wrap text-muted">{m.content}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
