import * as React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

export const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    className={cn(
      "peer inline-flex h-[18px] w-8 shrink-0 cursor-pointer items-center rounded-full border border-border bg-surface-3 transition-all",
      "data-[state=checked]:bg-accent data-[state=checked]:border-accent data-[state=checked]:shadow-glow disabled:opacity-40",
      className,
    )}
    {...props}
  >
    <SwitchPrimitive.Thumb className="pointer-events-none block h-3 w-3 translate-x-[3px] rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[15px]" />
  </SwitchPrimitive.Root>
));
Switch.displayName = "Switch";
