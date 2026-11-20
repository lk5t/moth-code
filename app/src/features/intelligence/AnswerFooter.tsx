/** Under every answer: cited sources (MOTH Cloud) and a quick rating (feedback learning; 2.4: on-device answers too). */
import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { serverApi } from "@/lib/account";
import { cn } from "@/lib/utils";

export interface AnswerMeta {
  model?: string;
  via?: string;
  sources?: { n: number; title: string; source?: string; shared?: boolean }[];
  prompt?: string;
  model_version?: number | null;
}

const PROBLEMS: [string, string][] = [["wrong", "Wrong"], ["unhelpful", "Not helpful"], ["code_error", "Code doesn't work"],
  ["reasoning_error", "Bad reasoning"], ["unsafe", "Unsafe"], ["other", "Other"]];

export function AnswerFooter({ meta, answer, prompt }: { meta: AnswerMeta; answer: string; prompt?: string }) {
  const [rated, setRated] = useState<1 | -1 | null>(null);
  const [asking, setAsking] = useState(false);
  const [correction, setCorrection] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const send = async (rating: 1 | -1, category = "") => {
    try {
      const r = await serverApi<{ stored_conversation: boolean }>("/v1/feedback", {
        method: "POST", json: { rating, category, correction, prompt: meta.prompt ?? prompt, response: answer, model: meta.model },
      });
      setRated(rating);
      setAsking(false);
      setNote(r.stored_conversation ? "Thanks — this helps MOTH learn." : "Thanks. Only the rating was saved (training use is off in Settings).");
    } catch (e) {
      const msg = (e as Error).message;
      setNote(/401|sign in|not signed/i.test(msg) ? "Sign in to MOTH Cloud to rate answers." : msg);
    }
  };
  return (
    <div className="mt-1.5 flex flex-col gap-1.5">
      {meta.via === "cloud" && !!meta.sources?.length && (
        <div className="flex flex-wrap gap-1.5 text-[0.65625rem] text-muted">
          Sources:{meta.sources.map((s) => (
            <span key={s.n} className="rounded bg-surface-2 px-1.5 py-0.5" title={s.source || s.title}>[{s.n}] {s.title}</span>
          ))}
        </div>
      )}
      <div className="flex items-center gap-1 text-faint">
        <button aria-label="Good answer" disabled={rated !== null} onClick={() => send(1)}
          className={cn("cursor-pointer rounded p-1 hover:text-fg disabled:cursor-default", rated === 1 && "text-success")}><ThumbsUp className="size-3.5" /></button>
        <button aria-label="Bad answer" disabled={rated !== null} onClick={() => setAsking(!asking)}
          className={cn("cursor-pointer rounded p-1 hover:text-fg disabled:cursor-default", rated === -1 && "text-danger")}><ThumbsDown className="size-3.5" /></button>
        {note && <span className="text-[0.65625rem] text-muted">{note}</span>}
      </div>
      {asking && (
        <div className="flex flex-col gap-1.5 rounded-md border border-border p-2 text-xs">
          <div className="text-muted">What went wrong?</div>
          <textarea className="rounded border border-border bg-surface p-1.5 text-xs" rows={2} placeholder="A better answer (optional)"
            value={correction} onChange={(e) => setCorrection(e.target.value)} />
          <div className="flex flex-wrap gap-1">
            {PROBLEMS.map(([k, label]) => (
              <button key={k} onClick={() => send(-1, k)} className="cursor-pointer rounded border border-border px-2 py-0.5 hover:bg-surface-2">{label}</button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
