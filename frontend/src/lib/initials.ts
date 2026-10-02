import { getLocale } from "@/paraglide/runtime.js";

/** Up to two capital letters from a name, for an avatar ("Ayşe Yılmaz": "AY"). */
export function initials(name: string): string {
  const letters = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word.charAt(0).toLocaleUpperCase(getLocale()));
  return letters.join("") || "?";
}
