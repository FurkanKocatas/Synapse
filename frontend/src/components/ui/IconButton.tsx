import { Tooltip } from "@base-ui/react/tooltip";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A square button with only an icon; its label is the accessible name and the tooltip. */
export function IconButton({
  label,
  className,
  children,
  ...props
}: { label: string; children: ReactNode } & Omit<ComponentProps<"button">, "aria-label">) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger
        render={
          <button
            type="button"
            aria-label={label}
            className={cn(
              "inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-subtle-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-40 aria-pressed:text-secondary-foreground [&_svg]:size-4",
              className,
            )}
            {...props}
          />
        }
      >
        {children}
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Positioner sideOffset={6} className="z-50">
          <Tooltip.Popup className="rounded-md bg-foreground px-2 py-1 text-xs text-background shadow-floating transition-opacity duration-100 data-[ending-style]:opacity-0 data-[starting-style]:opacity-0">
            {label}
          </Tooltip.Popup>
        </Tooltip.Positioner>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
