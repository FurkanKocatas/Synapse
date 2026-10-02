// Adapted from React Bits' ShinyText (https://reactbits.dev/text-animations/shiny-text),
// MIT + Commons Clause; the review is in docs/licences.md. Changes: theme tokens for the
// colours, no pause or yoyo options, and still text when the user asks for less motion.

import {
  motion,
  useAnimationFrame,
  useMotionValue,
  useReducedMotion,
  useTransform,
} from "motion/react";
import { useRef } from "react";

import { cn } from "@/lib/utils";

/** Text with a band of light passing over it: for a step that is under way. */
export function ShinyText({
  text,
  speed = 1.8,
  className,
}: {
  text: string;
  // Seconds for one pass.
  speed?: number;
  className?: string;
}) {
  const reduced = useReducedMotion() ?? false;
  const progress = useMotionValue(0);
  const elapsed = useRef(0);
  const last = useRef<number | null>(null);
  const duration = speed * 1000;

  useAnimationFrame((time) => {
    if (reduced) return;
    if (last.current === null) {
      last.current = time;
      return;
    }
    elapsed.current += time - last.current;
    last.current = time;
    progress.set(((elapsed.current % duration) / duration) * 100);
  });

  // 0: the band is off to the right; 100: off to the left.
  const backgroundPosition = useTransform(progress, (p) => `${String(150 - p * 2)}% center`);

  if (reduced) return <span className={className}>{text}</span>;
  return (
    <motion.span
      className={cn(
        "inline-block bg-[linear-gradient(110deg,var(--muted-foreground)_35%,var(--foreground)_50%,var(--muted-foreground)_65%)] bg-[length:200%_auto] bg-clip-text text-transparent",
        className,
      )}
      style={{ backgroundPosition }}
    >
      {text}
    </motion.span>
  );
}
