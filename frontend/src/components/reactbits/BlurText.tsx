// Adapted from React Bits' BlurText (https://reactbits.dev/text-animations/blur-text),
// MIT + Commons Clause; the review is in docs/licences.md. Changes: it plays once when shown
// (no intersection observer), a shorter rise, and plain text when the user asks for less motion.

import { motion, useReducedMotion } from "motion/react";
import { Fragment } from "react";

const FROM = { filter: "blur(10px)", opacity: 0, y: 8 };
const TO = {
  filter: ["blur(10px)", "blur(4px)", "blur(0px)"],
  opacity: [0, 0.6, 1],
  y: [8, -1, 0],
};

/** Words that come into focus one after another: for a greeting. */
export function BlurText({
  text,
  delay = 90,
  stepDuration = 0.3,
}: {
  text: string;
  // Milliseconds between one word and the next.
  delay?: number;
  stepDuration?: number;
}) {
  const reduced = useReducedMotion() ?? false;
  if (reduced) return text;
  // The spaces stay between the words' boxes, so the text reads (and is named) as written.
  return text.split(" ").map((word, index) => (
    // The words of one text do not move, so their position is their identity.
    <Fragment key={index}>
      {index > 0 && " "}
      <motion.span
        className="inline-block will-change-[transform,filter,opacity]"
        initial={FROM}
        animate={TO}
        transition={{
          duration: stepDuration * 2,
          times: [0, 0.5, 1],
          delay: (index * delay) / 1000,
        }}
      >
        {word}
      </motion.span>
    </Fragment>
  ));
}
