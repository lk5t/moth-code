/**
 * Sidebar conversation list with management: open, rename, delete one, select several and delete
 * them, or clear all (typed confirmation). Nothing is deleted without an explicit action.
 */
import { useState } from "react";
import { CheckSquare, MessageSquare, MoreHorizontal, Pencil, Square, Trash2, X } from "lucide-react";
import { appStore, useApp } from "@/lib/app-state";
import { clearConversations, deleteConversations, describeDelete, renameConversation } from "@/lib/conversations";
import { Popover, PopoverClose, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { requestChat } from "./SidebarCollections";

type Chat = { id: number; title: string };

export function ConversationList({ chats, searching, reload }: { chats: Chat[]; searching: boolean; reload: () => void }) {
  const session = useApp((s) => s.chatSession);
  const [selecting, setSelecting] = useState(false), [selected, setSelected] = useState<number[]>([]);
  const [renaming, setRenaming] = useState<number | null>(null), [name, setName] = useState("");
  const [confirm, setConfirm] = useState<null | { kind: "some"; ids: number[] } | { kind: "all" }>(null), [phrase, setPhrase] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);

  const afterDelete = (deleted: number[]) => {
    // The chat panel hears the backend's "conversations" event and clears an open, deleted conversation.
    setSelected((ids) => ids.filter((id) => !deleted.includes(id)));
    reload();
  };
  const run = async (action: () => Promise<{ deleted: number[]; missing: number[]; failed: { id: number; error: string }[] }>, ids: number[] | "all") => {
    const open = appStore.getState().chatSession;
    if (open.busy && open.conversationId !== null && (ids === "all" || ids.includes(open.conversationId))) {
      setError("MOTH is still answering in the open chat. Wait for the reply or stop it, then delete."); setConfirm(null); return;
    }
    setBusy(true); setError(null);
    try { const r = await action(); setError(describeDelete(r)); afterDelete([...r.deleted, ...r.missing]); setConfirm(null); setPhrase(""); if (!r.failed.length) setSelecting(false); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const saveName = async (id: number) => {
    const title = name.trim();
    if (!title) { setRenaming(null); return; }
    setBusy(true); setError(null);
    try { await renameConversation(id, title); setRenaming(null); reload(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const toggle = (id: number) => setSelected((ids) => ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]);

  return <section aria-label="Recent conversations">
    <div className="mb-1 flex h-6 items-center justify-between">
      <h2 className="text-[10px] uppercase tracking-wider text-faint">{searching ? "Search results" : "Chats"}</h2>
      {chats.length > 0 && (selecting
        ? <button className="flex items-center gap-1 rounded px-1 text-[11px] text-muted hover:text-fg" onClick={() => { setSelecting(false); setSelected([]); }}><X className="size-3" />Done</button>
        : <Popover><PopoverTrigger asChild><button aria-label="Manage chats" className="rounded p-1 text-muted hover:text-fg"><MoreHorizontal className="size-3.5" /></button></PopoverTrigger>
          <PopoverContent align="end" className="w-48 text-xs">
            <PopoverClose asChild><button className="flex w-full items-center gap-2 rounded px-2 py-1.5 hover:bg-surface-2" onClick={() => setSelecting(true)}><CheckSquare className="size-3.5" />Select chats</button></PopoverClose>
            <PopoverClose asChild><button className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-danger hover:bg-surface-2" onClick={() => setConfirm({ kind: "all" })}><Trash2 className="size-3.5" />Clear all chats…</button></PopoverClose>
          </PopoverContent></Popover>)}
    </div>
    {selecting && <div className="mb-1 flex items-center justify-between gap-2 rounded-md bg-surface-2 px-2 py-1 text-[11px]">
      <button className="text-muted hover:text-fg" onClick={() => setSelected(selected.length === chats.length ? [] : chats.map((c) => c.id))}>{selected.length === chats.length ? "Select none" : "Select all"}</button>
      <button disabled={!selected.length || busy} className="flex items-center gap-1 text-danger disabled:opacity-40" onClick={() => setConfirm({ kind: "some", ids: selected })}><Trash2 className="size-3" />Delete {selected.length || ""}</button>
    </div>}
    <ul className="space-y-0.5">
      {chats.map((chat) => {
        const current = session.conversationId === chat.id;
        if (renaming === chat.id) return <li key={chat.id}><form onSubmit={(e) => { e.preventDefault(); void saveName(chat.id); }}>
          <input autoFocus aria-label="Conversation name" value={name} maxLength={120} disabled={busy} onChange={(e) => setName(e.target.value)}
            onBlur={() => void saveName(chat.id)} onKeyDown={(e) => { if (e.key === "Escape") setRenaming(null); }}
            className="h-8 w-full rounded border border-accent/60 bg-bg px-2 text-xs text-fg outline-none" /></form></li>;
        return <li key={chat.id} className="group flex items-center rounded hover:bg-surface-2 has-[[aria-current=true]]:bg-surface-2">
          {selecting
            ? <button role="checkbox" aria-checked={selected.includes(chat.id)} aria-label={`Select ${chat.title}`} onClick={() => toggle(chat.id)} className="flex h-8 min-w-0 flex-1 items-center gap-2 px-2 text-left text-muted hover:text-fg">
                {selected.includes(chat.id) ? <CheckSquare className="size-3.5 shrink-0 text-accent" /> : <Square className="size-3.5 shrink-0" />}<span className="truncate">{chat.title}</span></button>
            : <button disabled={session.busy} aria-current={current ? "true" : undefined} onClick={() => requestChat(chat.id, chat.title)} title={chat.title}
                className="flex h-8 min-w-0 flex-1 items-center gap-2 px-2 text-left text-muted hover:text-fg aria-[current=true]:text-fg disabled:opacity-50"><MessageSquare className="size-3 shrink-0" /><span className="truncate">{chat.title}</span></button>}
          {!selecting && <Popover><PopoverTrigger asChild><button aria-label={`Options for ${chat.title}`} className="mr-1 rounded p-1 text-faint opacity-0 hover:text-fg focus-visible:opacity-100 group-hover:opacity-100 aria-expanded:opacity-100"><MoreHorizontal className="size-3.5" /></button></PopoverTrigger>
            <PopoverContent align="start" className="w-40 text-xs">
              <PopoverClose asChild><button className="flex w-full items-center gap-2 rounded px-2 py-1.5 hover:bg-surface-2" onClick={() => { setRenaming(chat.id); setName(chat.title); }}><Pencil className="size-3.5" />Rename</button></PopoverClose>
              <PopoverClose asChild><button className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-danger hover:bg-surface-2" onClick={() => setConfirm({ kind: "some", ids: [chat.id] })}><Trash2 className="size-3.5" />Delete</button></PopoverClose>
            </PopoverContent></Popover>}
        </li>;
      })}
    </ul>
    {error && <p role="alert" className="px-2 py-1 text-danger">{error}</p>}
    <Dialog open={!!confirm} onOpenChange={(open) => { if (!open) { setConfirm(null); setPhrase(""); } }}><DialogContent>
      {confirm?.kind === "all" ? <>
        <DialogTitle>Clear all chats?</DialogTitle>
        <DialogDescription>Every conversation on this computer and its messages are deleted permanently. Projects and settings are kept. Type DELETE ALL to confirm.</DialogDescription>
        <Input className="mt-3" aria-label="Clear all confirmation" value={phrase} onChange={(e) => setPhrase(e.target.value)} placeholder="DELETE ALL" autoComplete="off" spellCheck={false} />
        <div className="mt-4 flex justify-end gap-2"><Button size="sm" variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button size="sm" disabled={busy || phrase !== "DELETE ALL"} onClick={() => void run(() => clearConversations(phrase), "all")}>Delete all chats</Button></div>
      </> : confirm && <>
        <DialogTitle>{confirm.ids.length === 1 ? "Delete this chat?" : `Delete ${confirm.ids.length} chats?`}</DialogTitle>
        <DialogDescription>{confirm.ids.length === 1 ? `“${chats.find((c) => c.id === confirm.ids[0])?.title ?? "This conversation"}” and its messages are` : "The selected conversations and their messages are"} deleted permanently from this computer.</DialogDescription>
        <div className="mt-4 flex justify-end gap-2"><Button size="sm" variant="secondary" onClick={() => setConfirm(null)}>Cancel</Button>
          <Button size="sm" disabled={busy} onClick={() => void run(() => deleteConversations(confirm.ids), confirm.ids)}>Delete</Button></div>
      </>}
    </DialogContent></Dialog>
  </section>;
}
