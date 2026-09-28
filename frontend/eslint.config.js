import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "src/paraglide"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strictTypeChecked],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-syntax": [
        "error",
        {
          // Turkish casing: "i".toUpperCase() is "I", but in Turkish it must be "İ" (ADR 0011).
          selector: "CallExpression[callee.property.name=/^to(Upper|Lower)Case$/]",
          message: "Use toLocaleUpperCase(locale) or toLocaleLowerCase(locale) instead.",
        },
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: "Raw HTML is not allowed; render Markdown with HTML disabled (ADR 0011).",
        },
      ],
    },
  },
  {
    files: ["scripts/**/*.mjs", "paraglide.options.js"],
    extends: [js.configs.recommended],
    languageOptions: { globals: globals.node },
  },
);
