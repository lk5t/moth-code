import { Fragment } from "react";

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
            <div key={i} className="relative my-2">
              {lang && <span className="absolute right-2 top-1.5 text-[10px] uppercase text-faint">{lang}</span>}
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
