/** 2.0: before/after view of a file change. */
import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { diffLines, diffStats, folded, sideBySide, type DiffRow } from "@/lib/diff";

function Cell({ row, side }: { row?: DiffRow; side: "left" | "right" }) {
  if (!row) return <><td className="w-10 select-none bg-surface/40" /><td className="bg-surface/40" /></>;
  const n = row.t === "same" ? (side === "left" ? row.a : row.b) : row.t === "del" ? row.a : row.b;
  const tone = row.t === "del" ? "bg-danger/12 text-[#ffb3b8]" : row.t === "add" ? "bg-success/12 text-[#b8f0d4]" : "text-muted";
  return <>
    <td className={cn("w-10 select-none border-r border-border/50 px-1.5 text-right align-top text-faint", side === "right" && "border-l border-l-border", tone)}>{n}</td>
    <td className={cn("whitespace-pre-wrap break-all px-2 align-top", tone)}><span className="mr-1 select-none opacity-60">{row.t === "del" ? "−" : row.t === "add" ? "+" : " "}</span>{row.text || " "}</td>
  </>;
}

export function DiffView({ before, after, path, className }: { before: string | null; after: string; path: string; className?: string }) {
  const rows = useMemo(() => diffLines(before ?? "", after), [before, after]);
  const stats = diffStats(rows);
  const [full, setFull] = useState(false);
  const pairs = useMemo(() => sideBySide(rows), [rows]);
  const shown = full ? pairs : folded(pairs);
  return <div className={cn("overflow-hidden rounded-lg border border-border bg-bg", className)}>
    <div className="flex items-center gap-2 border-b border-border bg-surface px-2.5 py-1.5 text-[0.6875rem]">
      <span className="truncate font-mono text-fg">{path}</span>
      {before === null && <span className="rounded bg-success/15 px-1.5 text-success">new file</span>}
      <span className="ml-auto text-success">+{stats.added}</span><span className="text-danger">−{stats.removed}</span>
      {pairs.length > shown.length && <button className="text-muted hover:text-fg" onClick={() => setFull(true)}>Show whole file</button>}
    </div>
    <div className="max-h-[55vh] overflow-auto">
      <table className="selectable w-full table-fixed border-collapse font-mono text-[0.6875rem] leading-5">
        <colgroup><col className="w-10" /><col /><col className="w-10" /><col /></colgroup>
        <thead className="sticky top-0 z-10 bg-surface text-[0.625rem] uppercase tracking-wider text-faint">
          <tr><th colSpan={2} className="border-b border-border px-2 py-1 text-left font-medium">Before</th><th colSpan={2} className="border-b border-l border-border px-2 py-1 text-left font-medium">After</th></tr>
        </thead>
        <tbody>
          {shown.map((p, i) => "skip" in p
            ? <tr key={i}><td colSpan={4} className="bg-surface-2/60 py-0.5 text-center text-[0.625rem] text-faint">··· {p.skip} unchanged lines ···</td></tr>
            : <tr key={i} className="animate-fade-in"><Cell row={p.left} side="left" /><Cell row={p.right} side="right" /></tr>)}
          {!rows.length && <tr><td colSpan={4} className="p-3 text-center text-muted">Empty file</td></tr>}
        </tbody>
      </table>
    </div>
  </div>;
}
