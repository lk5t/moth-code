import { createContext, Fragment, memo, useContext, useState, type ReactNode } from "react";
import { serverApi } from "@/lib/account";
import { Check, Copy, FileDiff } from "lucide-react";
import { TOKEN_CLASS, codeTarget, highlight } from "@/lib/highlight";
import { useApp } from "@/lib/app-state";
import { proposeChange } from "@/features/workspace/ChangeReview";
import { openExternal } from "@/lib/external";
import { cn } from "@/lib/utils";

export function CopyText({text,label="Copy code"}:{text:string;label?:string}) {
  const [result,setResult]=useState<string|null>(null);
  const done = result === "Copied";
  return <span className="inline-flex items-center gap-2"><button type="button" className={cn("inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[0.6875rem] text-muted transition-colors hover:border-border-strong hover:text-fg focus-visible:outline focus-visible:outline-accent", done && "border-success/50 text-success")} aria-label={label}
    onClick={async()=>{try {if(!navigator.clipboard) throw new Error("Clipboard unavailable");await navigator.clipboard.writeText(text);setResult("Copied");setTimeout(()=>setResult(null),1600);}catch {setResult("Could not copy. Select the text and copy it manually.");}}}>
    {done ? <Check className="size-3 animate-pop" /> : <Copy className="size-3" />}{done ? "Copied" : label}</button>{result && !done && <span role="status" className="text-[0.625rem] text-muted">{result}</span>}</span>;
}

/** 2.0: the answer a code block belongs to, so Apply/Reject can teach MOTH (feedback learning). */
export const AnswerContext = createContext<{ prompt?: string; answer?: string; model?: string; via?: string } | null>(null);

function learnFrom(answer: { prompt?: string; answer?: string; model?: string; via?: string } | null, applied: boolean) {
  if (!answer || answer.via !== "cloud") return;
  void serverApi("/v1/feedback", { method: "POST", json: { rating: applied ? 1 : -1, category: applied ? "" : "other",
    comment: applied ? "applied the code to the project" : "rejected the code change", prompt: answer.prompt, response: answer.answer, model: answer.model } }).catch(() => {});
}

function CodeBlock({ label, code, streaming }: { label: string; code: string; streaming?: boolean }) {
  const project = useApp((s) => s.project);
  const answer = useContext(AnswerContext);
  const [error, setError] = useState<string | null>(null);
  const lang = label.trim().split(/\s+/)[0];
  const target = codeTarget(label, code);
  const tokens = streaming && code.length > 20000 ? [{ k: "plain" as const, v: code }] : highlight(code, lang);
  return <div className="my-2 min-w-0 overflow-hidden rounded-lg border border-border bg-[#0d0d0d] animate-fade-in">
    <div className="flex items-center gap-2 border-b border-border bg-surface/60 px-2.5 py-1">
      <span className="text-[0.625rem] uppercase tracking-wider text-faint">{lang || "Code"}</span>
      {target && <span className="truncate font-mono text-[0.625rem] text-muted">{target}</span>}
      <span className="ml-auto flex items-center gap-1.5">
        {target && project && !streaming && <button type="button" className="inline-flex items-center gap-1 rounded border border-accent/40 px-1.5 py-0.5 text-[0.6875rem] text-fg transition-colors hover:bg-accent-soft"
          title={`See the change to ${target}, then apply or reject it`} onClick={() => { setError(null); proposeChange(target, code, (applied) => learnFrom(answer, applied)).catch((e) => setError((e as Error).message)); }}><FileDiff className="size-3 text-accent" />Apply</button>}
        <CopyText text={code} />
      </span>
    </div>
    {error && <div role="alert" className="border-b border-border px-2.5 py-1 text-[0.6875rem] text-danger">{error}</div>}
    <pre className="!m-0 !rounded-none !border-0"><code>{tokens.map((t, i) => t.k === "plain" ? <Fragment key={i}>{t.v}</Fragment> : <span key={i} className={TOKEN_CLASS[t.k]}>{t.v}</span>)}</code></pre>
  </div>;
}

/** Inline formatting: `code`, **bold**, *italic*, [links](https://…) — rendered as React nodes, never HTML. */
export function inline(text: string): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\s][^*\n]*\*)|\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g;
  let last = 0, k = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m.index > last) out.push(<Fragment key={k++}>{text.slice(last, m.index)}</Fragment>);
    if (m[1]) out.push(<code key={k++} className="rounded bg-surface-3 px-1 py-0.5 text-[#ff8a92]">{m[1].slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={k++} className="font-semibold text-fg">{m[2].slice(2, -2)}</strong>);
    else if (m[3]) out.push(<em key={k++}>{m[3].slice(1, -1)}</em>);
    else if (m[4]) { const url = m[5]; out.push(<a key={k++} href={url} onClick={(e) => { e.preventDefault(); void openExternal(url); }}>{m[4]}</a>); }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(<Fragment key={k++}>{text.slice(last)}</Fragment>);
  return out;
}

function Blocks({ text }: { text: string }) {
  const lines = text.split("\n");
  const out: ReactNode[] = [];
  let para: string[] = [];
  let k = 0;
  const flush = () => { if (para.length) { out.push(<p key={k++} className="whitespace-pre-wrap">{inline(para.join("\n"))}</p>); para = []; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const h = /^(#{1,4})\s+(.+)$/.exec(line);
    if (h) { flush(); const size = h[1].length <= 2 ? "text-sm" : "text-[0.8125rem]"; out.push(<div key={k++} role="heading" aria-level={h[1].length} className={cn("mb-1 mt-3 font-semibold text-fg first:mt-0", size)}>{inline(h[2])}</div>); continue; }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      flush();
      const ordered = /^\s*\d+[.)]/.test(line);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) { items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, "")); i++; }
      i--;
      const List = ordered ? "ol" : "ul";
      out.push(<List key={k++} className={cn("my-1.5 space-y-0.5 pl-5", ordered ? "list-decimal" : "list-disc marker:text-accent")}>{items.map((it, j) => <li key={j}>{inline(it)}</li>)}</List>);
      continue;
    }
    if (/^>\s?/.test(line)) { flush(); out.push(<blockquote key={k++} className="my-1.5 border-l-2 border-accent/60 pl-2.5 text-muted">{inline(line.replace(/^>\s?/, ""))}</blockquote>); continue; }
    if (!line.trim()) { flush(); continue; }
    para.push(line);
  }
  flush();
  return <>{out}</>;
}

/** Safe renderer for MOTH's replies: fenced code (highlighted, Copy, Apply), headings, lists, quotes, inline code,
 * bold, italic and links. No HTML is ever injected. */
export const Markdown = memo(function Markdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const parts = text.split(/```/);
  return (
    <div className="prose-moth selectable space-y-1.5">
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          const nl = part.indexOf("\n");
          const label = nl > 0 ? part.slice(0, nl).trim() : "";
          const code = (nl >= 0 ? part.slice(nl + 1) : part).replace(/\n$/, "");
          return <CodeBlock key={i} label={label} code={code} streaming={streaming && i === parts.length - 1} />;
        }
        return <Blocks key={i} text={part} />;
      })}
    </div>
  );
});
