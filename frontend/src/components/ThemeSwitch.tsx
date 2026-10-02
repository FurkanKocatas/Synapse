import { DesktopIcon, MoonIcon, SunIcon, type Icon } from "@phosphor-icons/react";
import { useState } from "react";

import { chooseTheme, storedTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

export const THEMES: [ThemeChoice, Icon, () => string][] = [
  ["light", SunIcon, m.theme_light],
  ["dark", MoonIcon, m.theme_dark],
  ["system", DesktopIcon, m.theme_system],
];

/** Swaps the theme with a short cross-fade where the browser can, instantly where it cannot. */
export function switchTheme(choice: ThemeChoice) {
  const reduced =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (typeof document.startViewTransition === "function" && !reduced) {
    document.startViewTransition(() => {
      chooseTheme(choice);
    });
  } else chooseTheme(choice);
}

/** Three small buttons: light, dark, or what the system uses (for the sign-in pages). */
export function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  return (
    <div
      role="group"
      aria-label={m.theme_label()}
      className="flex h-8 items-center rounded-lg border bg-card p-0.5 shadow-raised"
    >
      {THEMES.map(([value, IconFor, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={choice === value}
          title={label()}
          onClick={() => {
            switchTheme(value);
            setChoice(value);
          }}
          className={cn(
            "rounded-md p-1.5 text-muted-foreground transition-colors hover:text-foreground",
            choice === value && "bg-muted text-foreground",
          )}
        >
          <IconFor className="size-3.5" aria-hidden="true" />
          <span className="sr-only">{label()}</span>
        </button>
      ))}
    </div>
  );
}
