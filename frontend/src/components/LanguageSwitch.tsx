import { useQueryClient } from "@tanstack/react-query";
import { Languages } from "lucide-react";

import { accountApi } from "@/features/account/accountApi";
import type { Session } from "@/features/auth/authApi";
import { sessionQuery } from "@/features/auth/session";
import { cn } from "@/lib/utils";

import { m } from "../paraglide/messages.js";
import { getLocale, locales, setLocale, type Locale } from "../paraglide/runtime.js";

// Language names are shown in their own language, so a user can always find theirs.
const languageNames: Record<Locale, () => string> = {
  tr: m.language_name_tr,
  en: m.language_name_en,
};

/** ``compact``: an icon in place of the visible label, for the title bar. */
export function LanguageSwitch({ compact = false }: { compact?: boolean }) {
  const queryClient = useQueryClient();

  async function choose(locale: Locale) {
    // Signed-in users keep their choice on the account, so it follows them to other browsers.
    const session = queryClient.getQueryData<Session | null>(sessionQuery.queryKey);
    if (session?.auth_level === "full") {
      try {
        await accountApi.setLocale(locale);
      } catch {
        // The language still changes in this browser; the account keeps the old preference.
      }
    }
    // Changing the locale reloads the page so every compiled message is re-rendered.
    await setLocale(locale);
  }

  return (
    <label
      className={cn(
        "flex items-center gap-2 text-sm",
        compact && "rounded-lg border bg-card py-1 pr-1 pl-2 text-muted-foreground",
      )}
    >
      {compact && <Languages className="size-4" aria-hidden="true" />}
      <span className={cn(compact && "sr-only")}>{m.language_switch_label()}</span>
      <select
        className={cn(
          "rounded border px-2 py-1",
          compact && "border-0 bg-transparent py-0.5 pl-0 text-foreground outline-none",
        )}
        value={getLocale()}
        onChange={(event) => {
          void choose(event.target.value as Locale);
        }}
      >
        {locales.map((locale) => (
          <option key={locale} value={locale}>
            {languageNames[locale]()}
          </option>
        ))}
      </select>
    </label>
  );
}
