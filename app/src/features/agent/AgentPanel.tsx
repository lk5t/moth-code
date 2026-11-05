import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Loader2, Play, RotateCcw, Square, Undo2, XCircle } from "lucide-react";
import { get, post } from "@/lib/backend";
import { useEvent } from "@/lib/events";
import { useApp } from "@/lib/app-state";
import { useResource } from "@/lib/hooks";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty";
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
interface TaskRow { id: string; goal: string; status: string; created_at: number }

const tone: Record<string, "accent" | "success" | "warning" | "danger" | "default"> = {
  running: "accent", queued: "accent", completed: "success", needs_review: "warning", incomplete: "warning",
  cancelled: "default", interrupted: "warning", model_incapable: "danger", failed: "danger", reverted: "default",
};
const label: Record<string, string> = { model_incapable: "beyond current model", needs_review: "needs review" };
const RESUMABLE = ["interrupted", "cancelled", "incomplete", "model_incapable", "failed", "needs_review"];

export function AgentPanel() {
  const project = useApp((s) => s.project);
  const { data: tasks, reload } = useResource<TaskRow[]>(project ? `/api/tasks?project_id=${project.id}` : null, [], []);
  const [selected, setSelected] = useState<string | null>(null);
  const [task, setTask] = useState<Task | null>(null);
  const [goal, setGoal] = useState("");
  const [live, setLive] = useState<{ phase: string; output: string }>({ phase: "", output: "" });
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const load = (id: string) => get<Task>(`/api/tasks/${id}`).then(setTask).catch(() => {});
  useEffect(() => {
    if (selected) load(selected);
    else setTask(null);
  }, [selected]);
  useEffect(() => {
    setSelected(null);
  }, [project?.id]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [task?.steps.length, live.output.length]);

  useEvent("task", (e) => {
    if (e.task_id !== selected) {
      if (e.kind === "status") reload();
      return;
    }
    if (e.kind === "planning") setLive({ phase: "Planning…", output: "" });
    if (e.kind === "thinking") setLive({ phase: `MOTH is choosing step ${e.step}…`, output: "" });
    if (e.kind === "tool_call") setLive({ phase: `Running ${e.tool}…`, output: "" });
    if (e.kind === "command_output") setLive((l) => ({ ...l, output: (l.output + e.data).slice(-8000) }));
    if (e.kind === "verifying") setLive({ phase: `Verifying with ${e.command}…`, output: "" });
    if (e.kind === "approval_wait") setLive({ phase: `Waiting for your approval: ${e.action} ${e.target}`, output: "" });
    if (e.kind === "invalid_output") setLive((l) => ({ ...l, phase: `MOTH produced an unusable action (${e.count}): ${e.error}` }));
    if (["status", "plan", "tool_result"].includes(e.kind)) load(selected!);
    if (e.kind === "status") {
      reload();
      if (!["running", "queued"].includes(e.status)) setLive({ phase: "", output: "" });
    }
  });

  const act = async (fn: () => Promise<any>) => {
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const start = () =>
    act(async () => {
      const t = await post<Task>("/api/tasks", { project_id: project!.id, goal });
      setGoal("");
      setSelected(t.id);
      setTask(t);
      reload();
    });

  if (!project) return <EmptyState title="Open a workspace">MOTH works autonomously only inside a folder you open and authorise.</EmptyState>;
  const running = task && ["running", "queued"].includes(task.status);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
        <Select className="h-7 min-w-0 flex-1 text-xs" value={selected ?? ""} onChange={(e) => setSelected(e.target.value || null)}>
          <option value="">New task</option>
          {tasks?.map((t) => <option key={t.id} value={t.id}>[{label[t.status] ?? t.status}] {t.goal.slice(0, 70)}</option>)}
        </Select>
      </div>
      {error && <div className="mx-3 mt-2 rounded border border-danger/30 bg-danger/10 px-2 py-1.5 text-xs text-danger">{error}</div>}

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        {!task ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <MothEmblem className="size-12" />
            <div className="text-sm">Give MOTH a task in {project.name}</div>
            <div className="max-w-sm text-xs leading-relaxed text-muted">
              MOTH plans, reads and edits files, runs commands and tests, and reports exactly what it did. Destructive or
              external actions always ask first. If the current model cannot do the task, MOTH says so.
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-3">
            <div className="flex items-start justify-between gap-3">
              <div className="selectable text-[13px] font-medium">{task.goal}</div>
              <Badge variant={tone[task.status]}>{label[task.status] ?? task.status}</Badge>
            </div>
            <div className="flex gap-2">
              {running && <Button size="sm" variant="secondary" onClick={() => act(() => post(`/api/tasks/${task.id}/cancel`))}><Square className="text-accent" /> Cancel</Button>}
              {RESUMABLE.includes(task.status) && <Button size="sm" variant="secondary" onClick={() => act(() => post(`/api/tasks/${task.id}/resume`).then(() => load(task.id)))}><RotateCcw /> Resume</Button>}
              {!running && task.report?.changes.some((c) => c.path) && task.status !== "reverted" && (
                <Button size="sm" variant="ghost" onClick={() => confirm("Undo every file change this task made?") && act(() => post(`/api/tasks/${task.id}/revert`).then(() => load(task.id)))}><Undo2 /> Revert changes</Button>
              )}
            </div>

            {task.plan.length > 0 && (
              <div className="rounded-lg border border-border bg-surface p-3">
                <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted">Plan (by MOTH)</div>
                <ol className="space-y-1 text-xs">
                  {task.plan.map((p, i) => <li key={i} className="flex gap-2"><span className="text-faint">{i + 1}.</span>{p}</li>)}
                </ol>
              </div>
            )}
            {task.notes.map((n, i) => <div key={i} className="text-[11px] text-muted">{n}</div>)}

            {task.steps.map((s) => <StepCard key={s.i} step={s} />)}

            {running && (
              <div className="flex flex-col gap-2 rounded-lg border border-accent/30 bg-accent-soft p-3">
                <div className="flex items-center gap-2 text-xs"><Loader2 className="size-3.5 animate-spin text-accent" />{live.phase || "Working…"}</div>
                {live.output && <pre className="selectable max-h-48 overflow-auto font-mono text-[11px] text-muted">{live.output}</pre>}
              </div>
            )}
            {task.report && <ReportCard report={task.report} />}
            <div ref={bottom} />
          </div>
        )}
      </div>

      <div className="shrink-0 p-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-xl border border-border bg-surface p-2 focus-within:border-accent/50 focus-within:shadow-glow">
          <Textarea rows={2} value={goal} placeholder="Describe a task, e.g. “Add input validation to parse_config and run the tests”"
            className="border-0 bg-transparent focus:shadow-none" onChange={(e) => setGoal(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && goal.trim()) start(); }} />
          <Button disabled={!goal.trim() || !!running} onClick={start}><Play /> Start</Button>
        </div>
      </div>
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
      {open && <pre className="selectable max-h-72 overflow-auto border-t border-border px-3 py-2 font-mono text-[11px] text-muted">{step.result}</pre>}
    </div>
  );
}

function ReportCard({ report }: { report: Report }) {
  const v = report.verification;
  return (
    <div className="rounded-lg border border-border bg-surface p-3 text-xs">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Report</div>
      {report.error && <div className="mb-2 flex gap-2 text-warning"><AlertTriangle className="mt-0.5 size-3.5 shrink-0" />{report.error}</div>}
      {report.model_summary && (
        <div className="mb-2">
          <div className="text-[11px] text-faint">MOTH's summary (its own words, not verified)</div>
          <div className="selectable mt-0.5">{report.model_summary}</div>
        </div>
      )}
      <div className="text-[11px] text-faint">Changes actually made</div>
      {report.changes.length ? (
        <ul className="mb-2 mt-0.5 space-y-0.5 font-mono">{report.changes.map((c, i) => <li key={i}>{c.type} {c.path ?? c.hash?.slice(0, 10)}</li>)}</ul>
      ) : <div className="mb-2 mt-0.5 text-muted">No files were changed.</div>}
      {report.commands.length > 0 && (
        <>
          <div className="text-[11px] text-faint">Commands</div>
          <ul className="mb-2 mt-0.5 space-y-0.5 font-mono">{report.commands.map((c, i) => <li key={i} className={c.ok ? "" : "text-danger"}>{c.ok ? "✓" : "✗"} {c.command}</li>)}</ul>
        </>
      )}
      <div className="text-[11px] text-faint">Verification</div>
      <div className="mt-0.5 flex items-center gap-1.5">
        {!v ? <><CircleDashed className="size-3.5 text-faint" /> Not needed (no file changes).</>
          : !v.ran ? <><CircleDashed className="size-3.5 text-faint" /> Not run: {v.reason}</>
          : v.passed ? <><CheckCircle2 className="size-3.5 text-success" /> <span className="font-mono">{v.command}</span> passed</>
          : <><XCircle className="size-3.5 text-danger" /> <span className="font-mono">{v.command}</span> failed (exit {v.exit_code})</>}
      </div>
      {v?.ran && !v.passed && v.output_tail && <pre className="selectable mt-2 max-h-48 overflow-auto font-mono text-[11px] text-muted">{v.output_tail}</pre>}
    </div>
  );
}

