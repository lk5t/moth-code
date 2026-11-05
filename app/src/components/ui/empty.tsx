import * as React from "react";
import { cn } from "@/lib/utils";

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
  return (
    <div className={cn("flex h-full flex-col items-center justify-center gap-2 p-6 text-center animate-fade-in", className)}>
      {icon && <div className="mb-1 text-faint [&_svg]:size-6">{icon}</div>}
      <div className="text-[13px] font-medium text-fg">{title}</div>
      {children && <div className="max-w-sm text-xs leading-relaxed text-muted">{children}</div>}
    </div>
  );
}
