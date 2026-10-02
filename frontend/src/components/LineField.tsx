import { useEffect, useRef } from "react";

const LINES = 14;
const STEP = 8;
// How often the colour is read again, so a theme change shows (milliseconds).
const REREAD_MS = 1000;

/** Faint lines in the action colour, slowly waving: the sign-in page's background. Drawn
 * once, without motion, when the user asks for less of it; not at all while hidden. */
export function LineField({ className }: { className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = canvas.current;
    if (element === null) return;
    const still =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    let colour = "";
    let read = -REREAD_MS;

    function draw(canvas: HTMLCanvasElement, time: number) {
      const ratio = window.devicePixelRatio || 1;
      const width = Math.floor(canvas.clientWidth * ratio);
      const height = Math.floor(canvas.clientHeight * ratio);
      // Hidden (a narrow window, or a test without layout): nothing to draw.
      const context = width > 0 && height > 0 ? canvas.getContext("2d") : null;
      if (context === null) return;
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      if (time - read > REREAD_MS) {
        colour = getComputedStyle(canvas).getPropertyValue("--primary").trim();
        read = time;
      }
      context.clearRect(0, 0, width, height);
      context.strokeStyle = colour;
      context.lineWidth = ratio;
      const t = time / 4000;
      for (let line = 0; line < LINES; line += 1) {
        context.globalAlpha = 0.05 + 0.12 * Math.sin((line / LINES) * Math.PI);
        context.beginPath();
        for (let x = 0; x <= width; x += STEP * ratio) {
          const k = x / width;
          const y =
            height * (0.32 + line * 0.024) +
            Math.sin(k * 5 + t + line * 0.35) * height * 0.05 * (1 + line / LINES) +
            Math.sin(k * 11 - t * 1.4) * height * 0.012;
          if (x === 0) context.moveTo(x, y);
          else context.lineTo(x, y);
        }
        context.stroke();
      }
    }

    function tick(time: number) {
      if (element === null) return;
      draw(element, time);
      if (!still) frame = requestAnimationFrame(tick);
    }

    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
    };
  }, []);

  return <canvas ref={canvas} aria-hidden="true" className={className} />;
}
