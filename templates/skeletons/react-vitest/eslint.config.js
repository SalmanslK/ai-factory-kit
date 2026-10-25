import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "coverage", "node_modules"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx}"],
    languageOptions: { ecmaVersion: 2020, globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // The rules CLAUDE.md marks enforced, named here so devtools/checks/check-rules.py can see them on.
      "@typescript-eslint/no-explicit-any": "error",
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // Prove a value is there with a check; never assert it with `!`.
      "@typescript-eslint/no-non-null-assertion": "error",
      // Log nothing in passing; console.warn and console.error report a fault.
      "no-console": ["error", { allow: ["warn", "error"] }],
      // An empty catch hides the fault: handle the failure you expect, or let it surface.
      "no-empty": ["error", { allowEmptyCatch: false }],
      // Named for what it is or does, never a Helper or a Utility.
      "@typescript-eslint/naming-convention": [
        "error",
        {
          selector: ["class", "interface", "typeAlias", "enum", "function", "variable"],
          format: null,
          custom: { regex: "(Helper|Utility|Utilities|Utils)$", match: false },
        },
      ],
    },
  },
  {
    // The time comes from src/clock.ts; a test sets it with vi.setSystemTime.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/clock.ts", "src/**/*.test.{ts,tsx}", "src/test-setup.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        {
          selector: "CallExpression[callee.object.name='Date'][callee.property.name='now']",
          message: "Take the time from now() in src/clock.ts, never Date.now().",
        },
        {
          selector: "NewExpression[callee.name='Date'][arguments.length=0]",
          message: "Take the time from now() in src/clock.ts, never new Date().",
        },
      ],
    },
  },
);
