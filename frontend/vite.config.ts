import { paraglideVitePlugin } from "@inlang/paraglide-js";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { paraglideOptions } from "./paraglide.options.js";

export default defineConfig({
  plugins: [react(), tailwindcss(), paraglideVitePlugin(paraglideOptions)],
  server: {
    // The API runs separately in development; in production Caddy serves both on one origin.
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
