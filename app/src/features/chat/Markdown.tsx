import { Fragment, useState } from "react";

export function CopyText({text,label="Copy code"}:{text:string;label?:string}) {
  const [result,setResult]=useState<string|null>(null);
  return <span className="inline-flex items-center gap-2"><button type="button" className="rounded border border-border px-2 py-1 text-[11px] text-muted hover:text-fg focus-visible:outline focus-visible:outline-accent" aria-label={label}
    onClick={async()=>{try {if(!navigator.clipboard) throw new Error("Clipboard unavailable");await navigator.clipboard.writeText(text);setResult("Copied");}catch {setResult("Could not copy. Select the text and copy it manually.");}}}>{label}</button>{result && <span role="status" className="text-[10px] text-muted">{result}</span>}</span>;
}

/** Minimal, safe renderer: fenced code blocks + inline code + paragraphs (no HTML injection). */
export function Markdown({ text }: { text: string }) {
  const parts = text.split(/```/);
  return (
    <div className="prose-moth selectable">
      {parts.map((part, i) => {
        if (i % 2 === 1) {
          const nl = part.indexOf("\n");
          const lang = nl > 0 ? part.slice(0, nl).trim() : "";
          const code = nl >= 0 ? part.slice(nl + 1) : part;
          return (
            <div key={i} className="my-2 min-w-0">
              <div className="mb-1 flex items-center justify-between gap-2"><span className="text-[10px] uppercase text-faint">{lang || "Code"}</span><CopyText text={code.replace(/\n$/, "")} /></div>
              <pre>
                <code>{code.replace(/\n$/, "")}</code>
              </pre>
            </div>
          );
        }
        return part
          .split(/\n{2,}/)
          .filter((p) => p.length)
          .map((p, j) => (
            <p key={`${i}-${j}`} className="whitespace-pre-wrap">
              {p.split(/(`[^`\n]+`)/).map((seg, k) =>
                seg.startsWith("`") && seg.endsWith("`") && seg.length > 2 ? (
                  <code key={k} className="rounded bg-surface-3 px-1 py-0.5 text-[#ff8a92]">{seg.slice(1, -1)}</code>
                ) : (
                  <Fragment key={k}>{seg}</Fragment>
                ),
              )}
            </p>
          ));
      })}
    </div>
  );
}
