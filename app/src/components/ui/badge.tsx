import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva("inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-medium", {
  variants: {
    variant: {
      default: "bg-surface-3 text-muted",
      accent: "bg-accent-soft text-[#ff5a64] border border-accent/30",
      success: "bg-success/12 text-success border border-success/25",
      warning: "bg-warning/12 text-warning border border-warning/25",
      danger: "bg-danger/12 text-danger border border-danger/25",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
