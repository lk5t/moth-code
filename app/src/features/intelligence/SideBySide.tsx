/** 2.3: the same prompts answered by the previous model and by this one. */
export function SideBySide({ rows }: { rows: { prompt: string; before: string; after: string }[] }) {
  return <div className="mt-2 overflow-hidden rounded-md border border-border">
    <div className="grid grid-cols-[1fr_1fr] bg-surface-2 px-2 py-1 text-[0.6875rem] text-faint"><span>Before (the model it was compared with)</span><span>This version</span></div>
    {rows.map((r) => <div key={r.prompt} className="border-t border-border px-2 py-1.5 text-[0.6875rem]">
      <div className="mb-1 text-muted">“{r.prompt}”</div>
      <div className="grid grid-cols-[1fr_1fr] gap-3 font-mono"><span className="whitespace-pre-wrap break-words text-faint">{r.before.trim() || "(no reply)"}</span>
        <span className="whitespace-pre-wrap break-words text-fg">{r.after.trim() || "(no reply)"}</span></div>
    </div>)}
  </div>;
}
