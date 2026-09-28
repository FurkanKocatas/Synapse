// Paraglide compiler options, shared by the Vite plugin and scripts/compile-i18n.mjs so the two
// can never disagree. (Files inside project.inlang/ other than settings.json are git-ignored by
// inlang itself, so options must not live there.)

/** @type {import("@inlang/paraglide-js").CompilerOptions} */
export const paraglideOptions = {
  project: "./project.inlang",
  outdir: "./src/paraglide",
  // The chosen language is remembered in the browser until user accounts store it (ADR 0011);
  // otherwise the browser's preferred language; otherwise Turkish.
  strategy: ["localStorage", "preferredLanguage", "baseLocale"],
  emitTsDeclarations: true,
};
