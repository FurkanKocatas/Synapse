// Adapted from React Bits' CountUp (https://reactbits.dev/text-animations/count-up),
// MIT + Commons Clause; the review is in docs/licences.md. Changes: it counts once when shown
// (no intersection observer), formats in the interface's locale, keeps the final number for
// screen readers, and shows it at once when the user asks for less motion.

import { useMotionValue, useReducedMotion, useSpring } from "motion/react";
import { useEffect, useEffectEvent, useRef } from "react";

import { getLocale } from "@/paraglide/runtime.js";

function grouped(value: number): string {
  return new Intl.NumberFormat(getLocale()).format(value);
}

/** A number that counts up to ``to`` when it appears. */
export function CountUp({
  to,
  duration = 1.2,
  format = grouped,
}: {
  to: number;
  // Seconds, roughly: the spring settles about then.
  duration?: number;
  // How the number is written (the locale's grouping by default).
  format?: (value: number) => string;
}) {
  const reduced = useReducedMotion() ?? false;
  const shown = useRef<HTMLSpanElement>(null);
  const value = useMotionValue(0);
  const spring = useSpring(value, { damping: 20 + 40 / duration, stiffness: 100 / duration });
  const write = useEffectEvent((latest: number) => {
    if (shown.current !== null) shown.current.textContent = format(Math.round(latest));
  });

  useEffect(() => {
    value.set(to);
  }, [to, value]);

  useEffect(() => spring.on("change", write), [spring]);

  if (reduced) return format(to);
  return (
    <>
      <span ref={shown} aria-hidden="true">
        {format(0)}
      </span>
      <span className="sr-only">{format(to)}</span>
    </>
  );
}
