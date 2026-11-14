import * as React from "react";
import { cn } from "@/lib/utils";
import { MothEmblem } from "@/components/MothEmblem";

/** 1.0: friendly tips under empty screens (one per screen, changing each visit). */
const TIPS = ["Press Ctrl+Alt+I to jump to MOTH's live training.", "Say “remember that …” in chat and MOTH keeps it in mind.",
  "Select an error in the terminal and press “Fix this”.", "Every change MOTH makes can be undone from Changes.",
  "Turn on “Show me the plan first” to approve MOTH's plan before it edits anything."];

export function EmptyState({
  icon,
  title,
  children,
  className,
}: {
  icon?: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const [tip] = React.useState(() => Math.floor(Math.random() * TIPS.length));
  return (
    <div className={cn("flex h-full flex-col items-center justify-center gap-2 p-6 text-center animate-fade-in", className)}>
      {icon ? <div className="mb-1 text-faint [&_svg]:size-6">{icon}</div> : <MothEmblem motion="idle" className="mb-1 size-10 opacity-90" />}
      <div className="text-[13px] font-medium text-fg">{title}</div>
      {children && <div className="max-w-sm text-xs leading-relaxed text-muted">{children}</div>}
      <div className="mt-2 max-w-sm text-[11px] text-faint">Tip: {TIPS[tip]}</div>
    </div>
  );
}
