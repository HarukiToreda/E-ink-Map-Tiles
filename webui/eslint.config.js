import eslint from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import globals from "globals";
import typescript from "typescript-eslint";

export default typescript.config(
  {
    ignores: ["dist/**", "electron-dist/**", "electron-stage/**", "node_modules/**"],
  },
  eslint.configs.recommended,
  ...typescript.configs.recommended,
  {
    files: ["public/**/*.js"],
    languageOptions: { globals: globals.serviceworker },
  },
  {
    files: ["electron/**/*.cjs", "scripts/**/*.mjs"],
    languageOptions: { globals: globals.node },
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.worker,
      },
    },
    plugins: {
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
    },
    rules: {
      ...reactHooks.configs.flat.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      "@typescript-eslint/no-unused-vars": ["error", { argsIgnorePattern: "^_" }],
    },
  },
);
