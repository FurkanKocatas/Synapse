import type { SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

/** The browser's own select, styled like the other inputs: accessible and native on phones. */
export function NativeSelect({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 rounded-lg border border-input bg-card px-2.5 text-sm transition-[border-color,box-shadow] outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/20 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
