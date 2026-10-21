import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const stage = path.join(root, "electron-stage");
const packageJson = JSON.parse(readFileSync(path.join(root, "package.json"), "utf8"));

rmSync(stage, { recursive: true, force: true });
mkdirSync(stage, { recursive: true });
cpSync(path.join(root, "dist"), path.join(stage, "dist"), { recursive: true });
cpSync(path.join(root, "electron"), path.join(stage, "electron"), { recursive: true });
rmSync(path.join(stage, "electron", "streaming-writers.test.cjs"), { force: true });
writeFileSync(
  path.join(stage, "package.json"),
  `${JSON.stringify(
    {
      name: "eink-map-tiles",
      productName: "E-ink Map Tiles",
      version: packageJson.version,
      private: true,
      main: "electron/main.cjs",
      dependencies: { archiver: packageJson.dependencies.archiver },
    },
    null,
    2,
  )}\n`,
);
