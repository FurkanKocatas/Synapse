import { m } from "../paraglide/messages.js";
import { getLocale, locales, setLocale, type Locale } from "../paraglide/runtime.js";

// Language names are shown in their own language, so a user can always find theirs.
const languageNames: Record<Locale, () => string> = {
  tr: m.language_name_tr,
  en: m.language_name_en,
};

export function LanguageSwitch() {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span>{m.language_switch_label()}</span>
      <select
        className="rounded border px-2 py-1"
        value={getLocale()}
        onChange={(event) => {
          // Changing the locale reloads the page so every compiled message is re-rendered.
          void setLocale(event.target.value as Locale);
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
