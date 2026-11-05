import { useEffect, useState } from "react";
import { ShieldAlert } from "lucide-react";
import { get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

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
            <div className="text-[11px] uppercase tracking-wider text-faint">{current.kind}</div>
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
