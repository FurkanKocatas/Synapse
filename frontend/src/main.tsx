import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./index.css";
import { applyTheme, followSystemTheme } from "./lib/theme";
import { getLocale } from "./paraglide/runtime.js";

// Locale-sensitive CSS (text-transform, hyphenation) and screen readers depend on this.
document.documentElement.lang = getLocale();
// Before the first render, so the page does not flash in the other theme.
applyTheme();
followSystemTheme();

const root = document.getElementById("root");
if (!root) {
  throw new Error("Root element #root is missing from index.html");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
