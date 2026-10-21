import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import packageJson from "./package.json";

export default defineConfig({
  base: "./",
  define: {
    __APP_VERSION__: JSON.stringify(packageJson.version),
  },
  plugins: [react()],
  build: {
    outDir: "dist",
  },
  test: {
    include: ["src/**/*.test.ts"],
  },
  server: { port: 8765 },
});
