/** 2.4: saved prompts — reuse your common requests in one click; save the current message for later. */
import { useState } from "react";
import { BookmarkPlus, Bookmark, X } from "lucide-react";
import { removePrompt, savePrompt, useSavedPrompts } from "@/lib/saved-prompts";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export function SavedPrompts({ current, onPick, disabled }: { current: string; onPick: (text: string) => void; disabled?: boolean }) {
  const prompts = useSavedPrompts();
  const [open, setOpen] = useState(false);
  const canSave = current.trim().length > 0 && !prompts.includes(current.trim());
  return <Popover open={open} onOpenChange={setOpen}>
    <PopoverTrigger asChild>
      <Button size="icon-sm" variant="ghost" title="Saved prompts" aria-label="Saved prompts" disabled={disabled}><Bookmark /></Button>
    </PopoverTrigger>
    <PopoverContent align="start" side="top" className="w-80">
      <div className="mb-1 flex items-center justify-between px-2 pt-0.5 text-[0.6875rem] text-faint">Saved prompts
        <button disabled={!canSave} onClick={() => savePrompt(current)} className="flex items-center gap-1 text-accent disabled:text-faint" title="Save what you typed">
          <BookmarkPlus className="size-3.5" />Save current</button></div>
      <ul className="max-h-72 overflow-auto">
        {prompts.map((p) => <li key={p} className="group flex items-center rounded-md hover:bg-surface-2">
          <button className="min-w-0 flex-1 truncate px-2 py-1.5 text-left text-xs text-muted group-hover:text-fg" title={p}
            onClick={() => { onPick(p); setOpen(false); }}>{p}</button>
          <button aria-label={`Remove “${p.slice(0, 30)}”`} className="mr-1 rounded p-1 text-faint opacity-0 hover:text-fg group-hover:opacity-100" onClick={() => removePrompt(p)}><X className="size-3" /></button>
        </li>)}
        {!prompts.length && <li className="px-2 py-2 text-xs text-faint">Nothing saved yet. Type a message and press “Save current”.</li>}
      </ul>
    </PopoverContent>
  </Popover>;
}
