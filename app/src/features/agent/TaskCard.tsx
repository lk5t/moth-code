import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Play, RotateCcw, Square, Undo2, XCircle } from "lucide-react";
import { get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/input";
import { MothEmblem } from "@/components/MothEmblem";

interface Step { i: number; thought: string; tool: string; args: Record<string, any>; ok: boolean; result: string }
interface Report {
  status: string;
  model_summary: string | null;
  changes: { type: string; path?: string; hash?: string }[];
  commands: { command: string; ok: boolean }[];
  verification: { ran: boolean; reason?: string; command?: string; passed?: boolean; exit_code?: number; output_tail?: string } | null;
  error: string | null;
  notes: string[];
}
interface Task { id: string; goal: string; status: string; plan: string[]; steps: Step[]; report: Report | null; error: string | null; notes: string[] }

const tone: Record<string, "accent" | "success" | "warning" | "danger" | "default"> = {
  running: "accent", queued: "accent", completed: "success", needs_review: "warning", incomplete: "warning",
  cancelled: "default", interrupted: "warning", model_incapable: "danger", failed: "danger", reverted: "default",
  plan_ready: "accent",
};
const label: Record<string, string> = { model_incapable: "beyond current model", needs_review: "needs review",
  plan_ready: "plan ready — approve to start" };
const RESUMABLE = ["interrupted", "cancelled", "incomplete", "model_incapable", "failed", "needs_review"];  // plan_ready uses "Approve"

/** 2.5.2: a task inside the chat, like Claude's tool use: live progress, the plan (when MOTH asks first), every
 * step it took, and a report of what really changed — with Cancel, Resume and Undo right on the card. */
export function TaskCard({ taskId, onAnswerInstead }: { taskId: string; onAnswerInstead?: () => void }) {
  const [task, setTask] = useState<Task | null>(null);
  const [live, setLive] = useState<{ phase: string; output: string }>({ phase: "", output: "" });
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [open, setOpen] = useState(true);
  const load = () => get<Task>(`/api/tasks/${taskId}`).then(setTask).catch(() => {});
  useEffect(() => { void load(); }, [taskId]);

  useEvent("task", (e) => {
    if (e.task_id !== taskId) return;
    if (e.kind === "planning") setLive({ phase: "Planning…", output: "" });
    if (e.kind === "thinking") setLive({ phase: `Choosing step ${e.step}…`, output: "" });
    if (e.kind === "tool_call") setLive({ phase: `Running ${e.tool}…`, output: "" });
    if (e.kind === "command_output") setLive((l) => ({ ...l, output: (l.output + e.data).slice(-8000) }));
    if (e.kind === "verifying") setLive({ phase: `Checking with ${e.command}…`, output: "" });
    if (e.kind === "test_fix") setLive({ phase: `Tests failed — fixing it (attempt ${e.attempt})…`, output: "" });
    if (e.kind === "approval_wait") setLive({ phase: `Waiting for your OK: ${e.action} ${e.target}`, output: "" });
    if (e.kind === "invalid_output") setLive((l) => ({ ...l, phase: `MOTH produced an unusable action (${e.count}): ${e.error}` }));
    if (["status", "plan", "tool_result"].includes(e.kind)) void load();
    if (e.kind === "status" && !["running", "queued"].includes(e.status)) setLive({ phase: "", output: "" });
  });

  const act = async (fn: () => Promise<any>) => {
    setError(null);
    try { await fn(); await load(); } catch (e) { setError(String((e as Error).message ?? e)); }
  };
  if (!task) return <div className="flex items-center gap-2 text-xs text-muted"><MothEmblem motion="working" className="size-4" />Starting…</div>;
  const running = ["running", "queued"].includes(task.status);
  const changed = task.report?.changes.filter((c) => c.path).length ?? 0;
  return (
    <div className={cn("w-full overflow-hidden rounded-xl border bg-surface text-xs transition-colors animate-pop", running ? "border-accent/50 shadow-glow" : "border-border")}>
      <button className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen(!open)} aria-expanded={open}>
        <MothEmblem motion={running ? "working" : "none"} className="size-4 shrink-0" />
        <span className="min-w-0 flex-1 truncate font-medium">{running ? live.phase || "Working…" : task.status === "completed" ? `Done${changed ? ` · ${changed} file${changed === 1 ? "" : "s"} changed` : ""}` : label[task.status] ?? task.status}</span>
        <span className="text-faint">{task.steps.length} step{task.steps.length === 1 ? "" : "s"}</span>
        <Badge variant={tone[task.status]}>{label[task.status] ?? task.status}</Badge>
        {open ? <ChevronDown className="size-3.5 text-faint" /> : <ChevronRight className="size-3.5 text-faint" />}
      </button>
      {running && <div className="h-0.5 overflow-hidden bg-surface-3"><div className="h-full w-1/3 animate-[indeterminate_1.4s_ease-in-out_infinite] rounded-full bg-accent" /></div>}
      {open && <div className="flex flex-col gap-2 border-t border-border p-3">
        {error && <div className="rounded border border-danger/30 bg-danger/10 px-2 py-1.5 text-danger">{error}</div>}
        {task.status === "plan_ready" && (
          <div className="animate-pop rounded-lg border border-accent/50 bg-accent-soft p-3">
            <div className="mb-1.5 font-medium">MOTH's plan — change anything, then approve to start</div>
            <Textarea rows={Math.min(10, task.plan.length + 1)} className="font-mono text-xs"
              value={draft ?? task.plan.map((p, i) => `${i + 1}. ${p}`).join("\n")} onChange={(e) => setDraft(e.target.value)} />
            <div className="mt-2 flex gap-2">
              <Button size="sm" onClick={() => act(async () => {
                const plan = (draft ?? task.plan.join("\n")).split("\n").map((l) => l.replace(/^\s*\d+[.)]\s*/, "").trim()).filter(Boolean);
                await post(`/api/tasks/${task.id}/plan`, { plan }); setDraft(null);
              })}><Play /> Approve and start</Button>
              <Button size="sm" variant="ghost" onClick={() => act(() => post(`/api/tasks/${task.id}/cancel`))}>Cancel</Button>
            </div>
          </div>
        )}
        {task.plan.length > 0 && task.status !== "plan_ready" && (
          <ol className="space-y-0.5 rounded-lg bg-bg/60 p-2">{task.plan.map((p, i) => <li key={i} className="flex gap-2"><span className="text-faint">{i + 1}.</span>{p}</li>)}</ol>
        )}
        {task.notes.map((n, i) => <div key={i} className="text-[0.6875rem] text-muted">{n}</div>)}
        <div className="stagger flex flex-col gap-1.5">{task.steps.map((s) => <StepCard key={s.i} step={s} />)}</div>
        {running && live.output && <pre className="selectable max-h-48 overflow-auto rounded-lg bg-bg p-2 font-mono text-[0.6875rem] text-muted">{live.output}</pre>}
        {task.report && <ReportCard report={task.report} />}
        <div className="flex flex-wrap gap-2">
          {running && <Button size="sm" variant="secondary" onClick={() => act(() => post(`/api/tasks/${task.id}/cancel`))}><Square className="text-accent" /> Stop</Button>}
          {RESUMABLE.includes(task.status) && <Button size="sm" variant="secondary" onClick={() => act(() => post(`/api/tasks/${task.id}/resume`))}><RotateCcw /> Keep going</Button>}
          {!running && changed > 0 && task.status !== "reverted" && (
            <Button size="sm" variant="ghost" onClick={() => confirm("Undo every file change this task made?") && act(() => post(`/api/tasks/${task.id}/revert`))}><Undo2 /> Undo changes</Button>
          )}
          {onAnswerInstead && !running && task.steps.length === 0 && <Button size="sm" variant="ghost" onClick={onAnswerInstead}>Just answer instead</Button>}
        </div>
      </div>}
    </div>
  );
}

function StepCard({ step }: { step: Step }) {
  const [open, setOpen] = useState(false);
  const arg = step.args.path ?? step.args.command ?? step.args.query ?? step.args.message ?? "";
  return (
    <div className="rounded-lg border border-border bg-surface animate-rise">
      <button className="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left" onClick={() => setOpen(!open)}>
        {step.ok ? <CheckCircle2 className="size-3.5 shrink-0 text-success" /> : <XCircle className="size-3.5 shrink-0 text-danger" />}
        <span className="font-mono text-xs text-[#ff6b75]">{step.tool}</span>
        <span className="truncate font-mono text-xs text-muted">{String(arg)}</span>
        <span className="ml-auto text-faint">{open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}</span>
      </button>
      {step.thought && <div className="px-3 pb-2 text-xs italic text-muted">{step.thought}</div>}
      {open && <pre className="selectable max-h-72 overflow-auto border-t border-border px-3 py-2 font-mono text-[0.6875rem] text-muted">{step.result}</pre>}
    </div>
  );
}

function ReportCard({ report }: { report: Report }) {
  const v = report.verification;
  return (
    <div className="rounded-lg border border-border bg-surface p-3 text-xs">
      <div className="mb-2 text-[0.6875rem] font-semibold uppercase tracking-wider text-muted">Report</div>
      {report.error && <div className="mb-2 flex gap-2 text-warning"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{report.error}</div>}
      {report.model_summary && (
        <div className="mb-2">
          <div className="text-[0.6875rem] text-faint">MOTH's summary (its own words, not verified)</div>
          <div className="selectable mt-0.5">{report.model_summary}</div>
        </div>
      )}
      <div className="text-[0.6875rem] text-faint">Changes actually made</div>
      {report.changes.length ? (
        <ul className="mb-2 mt-0.5 space-y-0.5 font-mono">{report.changes.map((c, i) => <li key={i}>{c.type} {c.path ?? c.hash?.slice(0, 10)}</li>)}</ul>
      ) : <div className="mb-2 mt-0.5 text-muted">No files were changed.</div>}
      {report.commands.length > 0 && (
        <>
          <div className="text-[0.6875rem] text-faint">Commands</div>
          <ul className="mb-2 mt-0.5 space-y-0.5 font-mono">{report.commands.map((c, i) => <li key={i} className={c.ok ? "" : "text-danger"}>{c.ok ? "✓" : "✗"} {c.command}</li>)}</ul>
        </>
      )}
      <div className="text-[0.6875rem] text-faint">Verification</div>
      <div className="mt-0.5 flex items-center gap-1.5">
        {!v ? <><CircleDashed className="size-3.5 text-faint" /> Not needed (no file changes).</>
          : !v.ran ? <><CircleDashed className="size-3.5 text-faint" /> Not run: {v.reason}</>
          : v.passed ? <><CheckCircle2 className="size-3.5 text-success" /> <span className="font-mono">{v.command}</span> passed</>
          : <><XCircle className="size-3.5 text-danger" /> <span className="font-mono">{v.command}</span> failed (exit {v.exit_code})</>}
      </div>
      {v?.ran && !v.passed && v.output_tail && <pre className="selectable mt-2 max-h-48 overflow-auto font-mono text-[0.6875rem] text-muted">{v.output_tail}</pre>}
    </div>
  );
}

