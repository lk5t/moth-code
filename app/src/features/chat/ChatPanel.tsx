import { MothEmblem } from "@/components/MothEmblem";

/** Phase 1 placeholder: the chat is wired to the MOTH model in Phase 2. */
export function ChatPanel() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <MothEmblem className="size-16 opacity-80" />
      <div className="text-sm text-fg">MOTH chat</div>
      <div className="max-w-xs text-xs text-muted">No MOTH model exists yet. Model training and inference are added in the next phase.</div>
    </div>
  );
}
