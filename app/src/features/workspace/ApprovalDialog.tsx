import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DiffView } from "./DiffView";

interface Change { path: string; before: string | null; after: string | null; before_truncated?: boolean; after_truncated?: boolean }

interface ApprovalRequest {
  id: string;
  kind: string;
  target: string;
  reason: string;
  risk: "low" | "medium" | "high";
  context: Record<string, unknown>;
}

/** Global approval prompt for destructive / external / out-of-workspace actions. */
export function ApprovalDialog() {
  const [queue, setQueue] = useState<ApprovalRequest[]>([]);
  useEffect(() => {
    get<ApprovalRequest[]>("/api/approvals").then(setQueue).catch(() => {});
  }, []);
  useEvent("approval", (e) => setQueue((q) => (q.some((r) => r.id === e.request.id) ? q : [...q, e.request])));

  const current = queue[0];
  const answer = async (approved: boolean) => {
    if (!current) return;
    setQueue((q) => q.slice(1));
    await post(`/api/approvals/${current.id}`, { approved }).catch(() => {});
  };

  const change = current?.context?.change as Change | undefined;
  if (current && change && change.after !== null) return (
    <Dialog open onOpenChange={(o) => !o && answer(false)}>
      <DialogContent className="w-[min(72rem,94vw)] max-w-none">
        <div className="flex items-center gap-2 pr-6">
          <ShieldAlert className="size-4 text-accent" />
          <DialogTitle>Review MOTH's change</DialogTitle>
          {queue.length > 1 && <span className="ml-auto text-[0.6875rem] text-muted">{queue.length - 1} more waiting</span>}
        </div>
        <DialogDescription>Check what changes in <span className="font-mono text-fg">{change.path}</span>, then apply it or reject it.</DialogDescription>
        <DiffView className="mt-3" path={change.path} before={change.before} after={change.after} />
        {(change.before_truncated || change.after_truncated) && <p className="mt-1 text-[0.6875rem] text-warning">This file is very large; only its start is shown.</p>}
        <div className="mt-3 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => answer(false)}>Reject</Button>
          <Button onClick={() => answer(true)}>Apply</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
  return (
    <Dialog open={!!current} onOpenChange={(o) => !o && answer(false)}>
      {current && (
        <DialogContent>
          <div className="flex items-center gap-2">
            <ShieldAlert className="size-4 text-accent" />
            <DialogTitle>MOTH needs your approval</DialogTitle>
            <Badge variant={current.risk === "high" ? "danger" : "warning"} className="ml-auto mr-6">{current.risk} risk</Badge>
          </div>
          <DialogDescription>{current.reason}</DialogDescription>
          <div className="mt-3 rounded-md border border-border bg-bg p-3">
            <div className="text-[0.6875rem] uppercase tracking-wider text-faint">{current.kind}</div>
            <pre className="selectable mt-1 whitespace-pre-wrap break-all font-mono text-xs text-fg">{current.target}</pre>
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="secondary" onClick={() => answer(false)}>Deny</Button>
            <Button onClick={() => answer(true)}>Approve</Button>
          </div>
        </DialogContent>
      )}
    </Dialog>
  );
}
