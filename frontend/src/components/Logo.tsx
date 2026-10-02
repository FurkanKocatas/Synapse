import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

/** The mark (for now): a page in front of another, on a tile in the action colour. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-6 shrink-0", className)}>
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <rect
        x="7.5"
        y="6.5"
        width="12"
        height="16"
        rx="2.2"
        fill="none"
        strokeWidth="1.6"
        className="stroke-primary-foreground/55"
      />
      <rect x="12" y="9.5" width="12.5" height="16" rx="2.2" className="fill-primary-foreground" />
      <path
        d="M15 14.5h6.5M15 17.5h6.5M15 20.5h4"
        strokeWidth="1.6"
        strokeLinecap="round"
        className="stroke-primary"
      />
    </svg>
  );
}

/** The mark and the name, as the sign-in pages show them. */
export function Wordmark({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "flex items-center gap-2.5 text-[15px] font-semibold tracking-tight",
        className,
      )}
    >
      <LogoMark className="size-7" />
      {m.app_name()}
    </span>
  );
}
