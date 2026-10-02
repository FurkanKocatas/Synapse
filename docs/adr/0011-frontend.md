# 0011. Frontend: static React SPA with compile-time checked translations

- Status: accepted
- Date: 2026-09-28

## Context

The app sits behind a login, so server-side rendering buys nothing. On a 16 GB box, a Node server costs 150 to 400 MB and is another surface to patch. Common problems in large dashboards: very large component files, XSS through user-controlled values placed in inline scripts, and translation keys present in one language but missing in the other. The UI must switch between Turkish and English with proper translations from the first release.

Research: [04-architecture.md, section 5](../research/04-architecture.md).

## Decision

- **Vite + React 19 + TypeScript**, built to static files and served by Caddy on the same origin as the API. No Node process in production.
- TypeScript 6.0 until `typescript-eslint` supports 7.x.
- **TanStack Router** (typed routes) and **TanStack Query** (server state). No global state library unless a real need appears.
- **shadcn/ui** (Radix primitives, Tailwind CSS 4), components copied into the repo. Design tokens in one place; no hard-coded colours in components.
- Light and dark themes from the same tokens, following the operating system setting (`prefers-color-scheme`) in CSS alone, so there is no flash of the wrong theme on load. An in-app switch can come later.
- **Paraglide JS 2** for i18n: messages compile to typed functions, so a missing key is a build error. CI also checks that `tr` and `en` have the same keys. Default locale Turkish; the user can switch, and the choice is stored on the account.
- **Words a thirteen-year-old understands** (added 2026-10-02). The people using Synapse are not technical, administrators included: someone of thirteen should see what everything on a screen is. No internal state, model or technical term on screen: a collection is a "folder", a document being parsed, read by OCR or embedded is "reading" or "almost ready", one searchable by its words is "ready". Every button says what it does (a label, or a tooltip on an icon), an empty screen says what to do next, and an error says what happened and what to do about it ("the file is locked with a password: remove the password and upload it again"). The code, the API and these documents keep the technical names.
- Turkish text handling: `<html lang>` follows the locale; user-visible casing uses `toLocaleUpperCase(locale)` and `toLocaleLowerCase(locale)` (a lint rule bans the plain variants); sorting with `Intl.Collator`; numbers and dates with `Intl.NumberFormat` and `Intl.DateTimeFormat`.
- **Security:** strict CSP with no `unsafe-inline` scripts; no `dangerouslySetInnerHTML` (lint rule); model output rendered as Markdown with raw HTML disabled; no inline bootstrapping scripts built from user data.
- **Streaming chat:** the API streams Server-Sent Events; the client reads them with `fetch` and `ReadableStream` (so it can send POST bodies and the CSRF header), and cancels with `AbortController`. Event types: `sources`, `token`, `citation`, `done`, `error`.
- Optional modules register their routes through the module registry ([0012](0012-installer-modules-licensing.md)); the SPA lazy-loads only enabled modules.
- Size budget: no component file over 400 lines, enforced in CI.

## Consequences

- A smaller attack surface and footprint.
- Everything the UI needs comes from the API; there is no server-side data fetching layer.

## Alternatives considered

- **Next.js:** Node server in production, a recurring source of CVEs (middleware, server actions), no need for SSR.
- **SvelteKit:** fine technically, smaller ecosystem and hiring pool.
- **MUI:** heavy, and its theming layer adds indirection; major upgrades are costly.
- **react-i18next:** a missing key is a runtime fallback, not a build error.
