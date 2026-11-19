/** 2.0: "Apply" on code MOTH wrote in chat: see the before/after, then apply it to the file or reject it. */
import { useState } from "react";
import { FileDiff } from "lucide-react";
import { createStore } from "@/lib/store";
import { get, put } from "@/lib/backend";
import { appStore } from "@/lib/app-state";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ErrorNotice } from "@/components/ErrorNotice";
import { DiffView } from "./DiffView";
import { sounds } from "@/lib/sounds";

interface Proposal { projectId: number; path: string; before: string | null; after: string; onDecision?: (applied: boolean) => void }
const store = createStore<{ proposal: Proposal | null; error: string | null }>({ proposal: null, error: null });

export async function proposeChange(path: string, after: string, onDecision?: (applied: boolean) => void): Promise<void> {
  const project = appStore.getState().project;
  if (!project) throw new Error("Open a project first to apply code to a file.");
  let before: string | null = null;
  try {
    before = (await get<{ content: string }>(`/api/projects/${project.id}/file?path=${encodeURIComponent(path)}`)).content;
  } catch (e) {
    if (!/not found/i.test(String((e as Error).message))) throw e;
  }
  store.setState({ proposal: { projectId: project.id, path, before, after: after.endsWith("\n") ? after : after + "\n", onDecision }, error: null });
}

export function ChangeReviewDialog() {
  const proposal = store.useStore((s) => s.proposal), error = store.useStore((s) => s.error);
  const [busy, setBusy] = useState(false);
  const close = () => store.setState({ proposal: null, error: null });
  const reject = () => { proposal?.onDecision?.(false); close(); };
  const apply = async () => {
    if (!proposal) return;
    setBusy(true);
    try {
      await put(`/api/projects/${proposal.projectId}/file`, { path: proposal.path, content: proposal.after });
      appStore.setState((s) => ({ treeVersion: s.treeVersion + 1, openFiles: s.openFiles.map((f) => f.path === proposal.path ? { ...f, content: proposal.after, saved: proposal.after } : f) }));
      sounds.chime();
      proposal.onDecision?.(true);
      close();
    } catch (e) { store.setState({ error: (e as Error).message }); } finally { setBusy(false); }
  };
  return <Dialog open={!!proposal} onOpenChange={(o) => !o && reject()}>
    {proposal && <DialogContent className="w-[min(72rem,94vw)] max-w-none">
      <div className="flex items-center gap-2"><FileDiff className="size-4 text-accent" /><DialogTitle>Apply this code?</DialogTitle></div>
      <DialogDescription>{proposal.before === null ? "This creates a new file." : "This replaces the file with MOTH's version."} You can undo it from the Changes panel.</DialogDescription>
      <ErrorNotice error={error} />
      <DiffView className="mt-3" path={proposal.path} before={proposal.before} after={proposal.after} />
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="secondary" onClick={reject}>Reject</Button>
        <Button disabled={busy || proposal.before === proposal.after} onClick={apply}>{proposal.before === proposal.after ? "No changes" : "Apply"}</Button>
      </div>
    </DialogContent>}
  </Dialog>;
}
