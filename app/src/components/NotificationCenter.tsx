/** 2.0 notification centre: one bell for everything — agent tasks, scans, training news and (for the Owner)
 * MOTH Cloud's notifications. Only promotions and problems pop up by themselves (quiet alerts). */
import { Bell, CheckCheck, Trash2 } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { clearInbox, markInboxRead, useInbox, type InboxTone } from "@/lib/inbox";
import { useOwnerNotices } from "./ActivityNotices";
import { navigate } from "@/lib/navigation";
import type { View } from "@/lib/app-state";

const DOT: Record<InboxTone, string> = { promoted: "bg-accent shadow-[0_0_8px_var(--color-accent)]", problem: "bg-warning", success: "bg-success", info: "bg-faint" };
const ago = (ts: number) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 60 ? "now" : s < 3600 ? `${Math.floor(s / 60)} min` : s < 86400 ? `${Math.floor(s / 3600)} h` : new Date(ts * 1000).toLocaleDateString();
};

export function NotificationCenter() {
  const local = useInbox((s) => s.items);
  const owner = useOwnerNotices();
  const rows = [
    ...local.map((n) => ({ key: n.id, ts: n.ts, tone: n.tone, title: n.title, message: n.message, unread: !n.read, view: n.view })),
    ...owner.items.map((n) => ({ key: `owner:${n.id}`, ts: n.ts, tone: (n.level === "error" || n.level === "warning" ? "problem" : n.category === "promotion" ? "promoted" : "info") as InboxTone,
      title: n.title, message: n.message, unread: n.unread, view: "activity" })),
  ].sort((a, b) => b.ts - a.ts).slice(0, 80);
  const unread = local.filter((n) => !n.read).length + (owner.data?.unread ?? 0);
  return <Popover onOpenChange={(open) => { if (!open) { markInboxRead(); owner.markRead(); } }}>
    <PopoverTrigger aria-label={unread ? `${unread} unread notifications` : "Notifications"}
      className="relative rounded-md p-1 text-muted transition-colors hover:bg-surface-2 hover:text-fg focus-visible:outline">
      <Bell className={cn("size-4", unread > 0 && "text-fg")} />
      {unread > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-3.5 rounded-full bg-accent px-0.5 text-center text-[0.5625rem] leading-3.5 text-white animate-pop">{unread > 9 ? "9+" : unread}</span>}
    </PopoverTrigger>
    <PopoverContent className="w-80 p-0 animate-spring" align="start">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="flex-1 text-xs font-medium">Notifications</span>
        <button title="Mark all read" aria-label="Mark all read" className="rounded p-0.5 text-muted hover:text-fg" onClick={() => { markInboxRead(); owner.markRead(); }}><CheckCheck className="size-3.5" /></button>
        <button title="Clear" aria-label="Clear notifications" className="rounded p-0.5 text-muted hover:text-fg" onClick={clearInbox}><Trash2 className="size-3.5" /></button>
      </div>
      {rows.length ? <ul className="stagger max-h-96 overflow-auto">{rows.map((n) =>
        <li key={n.key}><button onClick={() => n.view && navigate(n.view as View)} className={cn("flex w-full gap-2 border-b border-border px-3 py-2 text-left text-xs transition-colors last:border-0 hover:bg-surface-2", n.unread && "bg-accent-soft/60")}>
          <span className={cn("mt-1 size-1.5 shrink-0 rounded-full", DOT[n.tone])} />
          <span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="truncate font-medium text-fg">{n.title}</span>
            <time className="shrink-0 text-[0.625rem] text-faint">{ago(n.ts)}</time></span>
            <span className="mt-0.5 block text-muted">{n.message}</span></span>
        </button></li>)}</ul>
        : <p className="px-3 py-6 text-center text-xs text-muted">All quiet. Finished tasks, scans and MOTH's progress show up here.</p>}
    </PopoverContent>
  </Popover>;
}
