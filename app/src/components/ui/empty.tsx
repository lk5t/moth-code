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
  tip = true,
  action,
}: {
  icon?: React.ReactNode;
  title: string;
  children?: React.ReactNode;
  className?: string;
  /** 2.2: a random tip fits idle screens, not sign-in prompts or errors */
  tip?: boolean;
  action?: React.ReactNode;
}) {
  const [tipIndex] = React.useState(() => Math.floor(Math.random() * TIPS.length));
  return (
    <div className={cn("flex h-full flex-col items-center justify-center gap-2 p-6 text-center animate-fade-in", className)}>
      {icon ? <div className="mb-1 text-faint [&_svg]:size-6">{icon}</div> : <MothEmblem motion="idle" className="mb-1 size-10 opacity-90" />}
      <div className="text-[0.8125rem] font-medium text-fg">{title}</div>
      {children && <div className="max-w-sm text-xs leading-relaxed text-muted">{children}</div>}
      {action && <div className="mt-2">{action}</div>}
      {tip && <div className="mt-2 max-w-sm text-[0.6875rem] text-faint">Tip: {TIPS[tipIndex]}</div>}
    </div>
  );
}
