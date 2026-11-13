/**
 * Owner notifications (0.7.1): promotions, verified improvements, rollbacks, deployment problems,
 * failed experiments, worker failures and infrastructure problems — read from MOTH Cloud's
 * `/v1/admin/notifications`, which answers only the Owner (HTTP 403 for anyone else). Other accounts
 * see nothing here.
 */
import { useCallback, useEffect, useState } from "react";
import { Bell } from "lucide-react";
import { serverApi, useAccount } from "@/lib/account";
import { navigate } from "@/lib/navigation";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

type Notice = { id: number; ts: number; title: string; message: string; level: string; category: string; unread: boolean };
type Data = { items: Notice[]; unread: number };

export function ActivityNotices() {
  const owner = useAccount((s) => s.user?.role === "owner");
  const token = useAccount((s) => s.token), server = useAccount((s) => s.serverUrl);
  const [data, setData] = useState<Data | null>(null);
  const load = useCallback(() => {
    if (!owner || !token || (typeof document !== "undefined" && document.hidden)) return;
    serverApi<Data>("/v1/admin/notifications?limit=30").then(setData).catch(() => setData(null));
  }, [owner, token, server]);
  useEffect(() => {
    setData(null);
    if (!owner || !token) return;
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, [load]);
  if (!owner || !token) return null;
  const items = data?.items ?? [];
  const markRead = () => {
    if (!items.length || !data?.unread) return;
    serverApi<Data>("/v1/admin/notifications/read", { method: "POST", json: { up_to_id: items[0].id } }).then(setData).catch(() => undefined);
  };
  return <Popover onOpenChange={(open) => { if (!open) markRead(); }}>
    <PopoverTrigger aria-label={data?.unread ? `${data.unread} unread notifications` : "Notifications"}
      className="relative rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline">
      <Bell className="size-4" />
      {!!data?.unread && <span className="absolute -right-0.5 -top-0.5 min-w-3.5 rounded-full bg-accent px-0.5 text-center text-[9px] leading-3.5 text-white">{data.unread > 9 ? "9+" : data.unread}</span>}
    </PopoverTrigger>
    <PopoverContent className="w-80 p-0" align="start">
      <div className="flex items-center justify-between border-b border-border px-3 py-2"><span className="text-xs font-medium">Notifications</span>
        <button className="text-[11px] text-accent" onClick={() => navigate("activity")}>All activity</button></div>
      {items.length ? <ul className="max-h-80 overflow-auto">{items.map((n) => <li key={n.id} className={cn("border-b border-border px-3 py-2 text-xs last:border-0", n.unread && "bg-accent-soft")}>
        <div className="flex items-center justify-between gap-2"><span className={cn("font-medium", n.level === "error" ? "text-danger" : n.level === "warning" ? "text-warning" : "text-fg")}>{n.title}</span>
          <time className="shrink-0 text-[10px] text-faint">{new Date(n.ts * 1000).toLocaleString()}</time></div>
        <p className="mt-0.5 text-muted">{n.message}</p>
      </li>)}</ul> : <p className="px-3 py-4 text-xs text-muted">{data ? "Nothing needs your attention." : "Notifications are unavailable right now."}</p>}
    </PopoverContent>
  </Popover>;
}
