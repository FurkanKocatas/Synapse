// Adapted from React Bits' SpotlightCard (https://reactbits.dev/components/spotlight-card),
// MIT + Commons Clause; the review is in docs/licences.md. Changes: the light is in the action
// colour from the theme, follows the pointer through CSS variables (no re-render per move),
// and the card's look is the caller's.

import type { CSSProperties, MouseEvent, ReactNode } from "react";

import { cn } from "@/lib/utils";

/** A card with a soft light under the pointer. */
export function SpotlightCard({
  className,
  style,
  children,
}: {
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  function follow(event: MouseEvent<HTMLDivElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--spot-x", `${String(event.clientX - box.left)}px`);
    event.currentTarget.style.setProperty("--spot-y", `${String(event.clientY - box.top)}px`);
  }

  return (
    <div
      onMouseMove={follow}
      style={style}
      className={cn("group/spot relative isolate", className)}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 rounded-[inherit] opacity-0 transition-opacity duration-500 group-hover/spot:opacity-100 [background:radial-gradient(260px_circle_at_var(--spot-x,50%)_var(--spot-y,50%),color-mix(in_oklch,var(--primary)_14%,transparent),transparent_70%)]"
      />
      {children}
    </div>
  );
}
