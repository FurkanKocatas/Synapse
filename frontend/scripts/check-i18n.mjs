// Fails when the Turkish and English message files do not have exactly the same keys,
// or when a message is empty. Paraglide already fails the build on a key missing from the
// base locale; this check also catches keys missing from the other locales (ADR 0011).
import { readFileSync } from "node:fs";

const locales = ["tr", "en"];
const catalogs = Object.fromEntries(
  locales.map((locale) => {
    const raw = JSON.parse(readFileSync(new URL(`../messages/${locale}.json`, import.meta.url)));
    delete raw.$schema;
    return [locale, raw];
  }),
);

const problems = [];
const allKeys = new Set(locales.flatMap((locale) => Object.keys(catalogs[locale])));
for (const key of [...allKeys].sort()) {
  for (const locale of locales) {
    const value = catalogs[locale][key];
    if (value === undefined) problems.push(`${locale}: missing "${key}"`);
    else if (typeof value === "string" && value.trim() === "")
      problems.push(`${locale}: empty "${key}"`);
  }
}

if (problems.length > 0) {
  console.error(problems.join("\n"));
  process.exit(1);
}
console.log(`i18n: ${allKeys.size} keys, identical in ${locales.join(", ")}`);
