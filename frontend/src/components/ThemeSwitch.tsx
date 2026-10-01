import { Monitor, Moon, Sun } from "lucide-react";
import { useState } from "react";

import { chooseTheme, storedTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

const CHOICES: [ThemeChoice, typeof Sun, () => string][] = [
  ["light", Sun, m.theme_light],
  ["dark", Moon, m.theme_dark],
  ["system", Monitor, m.theme_system],
];

/** Three small buttons: light, dark, or what the system uses. */
export function ThemeSwitch() {
  const [choice, setChoice] = useState<ThemeChoice>(storedTheme);
  return (
    <div role="group" aria-label={m.theme_label()} className="flex rounded-lg border bg-card p-0.5">
      {CHOICES.map(([value, Icon, label]) => (
        <button
          key={value}
          type="button"
          aria-pressed={choice === value}
          title={label()}
          onClick={() => {
            chooseTheme(value);
            setChoice(value);
          }}
          className={cn(
            "rounded-md p-1.5 text-muted-foreground hover:text-foreground",
            choice === value && "bg-accent text-accent-foreground",
          )}
        >
          <Icon className="size-4" aria-hidden="true" />
          <span className="sr-only">{label()}</span>
        </button>
      ))}
    </div>
  );
}
