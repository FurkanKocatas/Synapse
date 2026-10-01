// Light, dark, or the operating system's choice. The choice is a convenience of this browser
// (localStorage), not an account setting; the class on <html> is what the styles read.

export type ThemeChoice = "system" | "light" | "dark";

const KEY = "synapse.theme";
const DARK = "(prefers-color-scheme: dark)";

export function storedTheme(): ThemeChoice {
  try {
    const value = window.localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function prefersDark(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(DARK).matches;
}

/** Puts the chosen theme on the page, and keeps following the system when that is the choice. */
export function applyTheme(choice: ThemeChoice = storedTheme()): void {
  const dark = choice === "dark" || (choice === "system" && prefersDark());
  document.documentElement.classList.toggle("dark", dark);
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
}

export function chooseTheme(choice: ThemeChoice): void {
  try {
    if (choice === "system") window.localStorage.removeItem(KEY);
    else window.localStorage.setItem(KEY, choice);
  } catch {
    // Private windows may refuse storage; the theme still changes for this page.
  }
  applyTheme(choice);
}

/** Re-applies the system's theme when it changes, while the choice is "system". */
export function followSystemTheme(): () => void {
  if (typeof window.matchMedia !== "function") return () => undefined;
  const media = window.matchMedia(DARK);
  const onChange = () => {
    if (storedTheme() === "system") applyTheme("system");
  };
  media.addEventListener("change", onChange);
  return () => {
    media.removeEventListener("change", onChange);
  };
}
