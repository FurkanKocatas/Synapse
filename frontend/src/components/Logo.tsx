import { cn } from "@/lib/utils";

import { m } from "@/paraglide/messages.js";

/** The mark: a page in front of another, with lines of text on it. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className={cn("size-6", className)}>
      <rect
        x="3.5"
        y="2.5"
        width="12"
        height="16"
        rx="2.5"
        fill="none"
        strokeWidth="1.5"
        className="stroke-muted-foreground/60"
      />
      <rect x="8" y="5.5" width="12.5" height="16" rx="2.5" className="fill-primary" />
      <path
        d="M11 10.5h6.5M11 13.5h6.5M11 16.5h4"
        strokeWidth="1.5"
        strokeLinecap="round"
        className="stroke-primary-foreground"
      />
    </svg>
  );
}

/** The mark and the name, as the navigation and the sign-in pages show them. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn("flex items-center gap-2 text-[15px] font-semibold tracking-tight", className)}
    >
      <LogoMark className="size-[22px]" />
      {m.app_name()}
    </span>
  );
}
