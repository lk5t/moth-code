import { Activity } from "lucide-react";
import { useResource } from "@/lib/hooks";
import { useApp } from "@/lib/app-state";
import { useEvent } from "@/lib/events";
import { EmptyState } from "@/components/ui/empty";
import { timeAgo } from "@/lib/utils";

interface Item {
  id: number;
  ts: number;
  kind: string;
  message: string;
}

export function ActivityPanel({ all = false }: { all?: boolean }) {
  const project = useApp((s) => s.project);
  const {data:items=[],error,reload:load}=useResource<Item[]>(`/api/activity${!all && project ? `?project_id=${project.id}` : ""}`,["files","activity"],[]);
  useEvent("task", (e) => {
    if (e.kind === "status") load();
  });

  if(error)return <p role="alert" className="p-3 text-xs">Activity could not be loaded: {error}</p>;
  if (!items.length) return <EmptyState icon={<Activity />} title="No activity yet" />;
  return (
    <div className="h-full overflow-auto p-2">
      {items.map((i) => (
        <div key={i.id} className="flex items-start gap-2 rounded px-2 py-1.5 text-xs hover:bg-surface-2">
          <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-accent/70" />
          <div className="min-w-0 flex-1">
            <div className="truncate text-fg" title={i.message}>{i.message}</div>
            <div className="text-[11px] text-faint">{i.kind} · {timeAgo(i.ts)}</div>
          </div>
        </div>
      ))}
    </div>
  );
}
