import { cn } from "@/lib/utils";

/** The mark: two nodes and the link between them. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("size-8", className)}>
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M10 21.5c3.2 0 4.6-2.2 6-5.5s2.8-5.5 6-5.5"
        fill="none"
        strokeWidth="2.4"
        strokeLinecap="round"
        className="stroke-primary-foreground"
      />
      <circle cx="9.5" cy="21.5" r="3" className="fill-highlight" />
      <circle cx="22.5" cy="10.5" r="3" className="fill-primary-foreground" />
    </svg>
  );
}
