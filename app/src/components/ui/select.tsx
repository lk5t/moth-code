import * as React from "react";
import { cn } from "@/lib/utils";

/** Native select styled for MOTH (native keeps keyboard + accessibility behaviour on Windows). */
export const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <select
      ref={ref}
      className={cn(
        "h-8 rounded-md border border-border bg-bg px-2 text-[13px] text-fg focus:border-accent/70 focus:outline-none cursor-pointer",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  ),
);
Select.displayName = "Select";
