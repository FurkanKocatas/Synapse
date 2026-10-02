import { TranslateIcon } from "@phosphor-icons/react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";

import { accountApi } from "@/features/account/accountApi";
import type { Session } from "@/features/auth/authApi";
import { sessionQuery } from "@/features/auth/session";

import { m } from "../paraglide/messages.js";
import { getLocale, locales, setLocale, type Locale } from "../paraglide/runtime.js";

// Language names are shown in their own language, so a user can always find theirs.
export const languageNames: Record<Locale, () => string> = {
  tr: m.language_name_tr,
  en: m.language_name_en,
};

/** Switches the interface language; signed-in users keep the choice on their account, so it
 * follows them to other browsers. */
export async function chooseLocale(queryClient: QueryClient, locale: Locale) {
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

/** A small select with an icon, for the sign-in pages' corner. */
export function LanguageSwitch() {
  const queryClient = useQueryClient();
  return (
    <label className="flex h-8 items-center gap-1.5 rounded-lg border bg-card pr-1 pl-2 text-sm text-muted-foreground shadow-raised">
      <TranslateIcon className="size-4" aria-hidden="true" />
      <span className="sr-only">{m.language_switch_label()}</span>
      <select
        className="bg-transparent py-0.5 text-foreground outline-none"
        value={getLocale()}
        onChange={(event) => {
          void chooseLocale(queryClient, event.target.value as Locale);
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
