# Browser UI development

The browser UI is a static React and TypeScript application. It has no application backend: source fetching, rendering, tile planning, conversion, compression, persistence, and downloads all run in the browser.

## Commands

Run commands from `webui/`:

```bash
npm ci
npm run dev
npm run check
npm run build
```

`npm run check` is the local quality gate: strict TypeScript, ESLint, Prettier, and Vitest. `npm run build` writes the production application to the ignored `webui/dist/` directory. Generated bundles are deployment output and are not committed.
The version shown in the UI is injected from `package.json` at build time.

## Cloudflare Workers deployment

The production Web UI can be deployed as a Cloudflare Workers application with static assets. `wrangler.jsonc` points Cloudflare at the Vite output in `dist/` and enables single-page-application fallback routing.

When connecting this repository in **Workers & Pages → Create application**, use these build settings:

| Setting         | Value                  |
| --------------- | ---------------------- |
| Root directory  | `webui`                |
| Build command   | `npm run build`        |
| Deploy command  | `npx wrangler deploy`  |
| Preview command | `npx wrangler preview` |

Cloudflare installs the locked npm dependencies before running the build. The build command performs TypeScript compilation and creates the production assets; Wrangler then uploads the generated `dist/` directory described by `wrangler.jsonc`. No server-side Worker entry point is required for this browser-only application.

The Wrangler `name` is `eink-map-tiles`. Use the same name when creating the Cloudflare Worker, or update the name in `wrangler.jsonc` to match an existing Worker before connecting the repository.

From the repository root, `./scripts/eink-map-tiles.sh --ui=web` on Unix-like systems or `.\scripts\eink-map-tiles.ps1 --ui=web` on Windows installs locked dependencies when `node_modules/` is absent, builds this application, and serves `dist/` through Node/Vite. Python is not involved in the Web UI runtime. Use `npm run dev` directly when you want Vite’s development server and hot-module replacement.

## Electron desktop build

The same production Web UI can run in a sandboxed Electron shell:

```bash
npm run desktop
npm run desktop:package
```

`desktop:package` writes an ignored, platform-specific application bundle under `electron-dist/`. Tagged releases build zipped Electron bundles for Windows, Linux, and macOS alongside the existing Python desktop artifacts.

The Electron build streams every export format through temporary files and moves the completed artifact to the selected destination. ZIP uses ZIP64, PMTiles spools tile bodies before writing its sorted directory, and both InkHUD formats stream compressed payloads without collecting the complete artifact in renderer memory. The InkHUD schema itself uses 32-bit payload offsets, so those formats report an error rather than producing a corrupt file if compressed payload data exceeds 4 GiB.

## Structure

- `src/App.tsx` coordinates search, imports, exports, reset, and top-level UI state.
- `src/BrowserMap.tsx` owns viewport interaction and draws the current browser preview.
- `src/components/` contains presentation-oriented UI sections.
- `src/hooks/` owns persisted project state and asynchronous tile estimates.
- `src/browser/` contains framework-independent domain services, workers, renderers, format writers, and shared geometry/math helpers.
- `src/browser/mapConfig.ts` is the single authority for source zoom limits, attribution, and MUI style names.
- `src/browser/session.ts` defines defaults and validates the only supported persisted-session schema.
- `src/browser/workerProtocol.ts` defines the shared request/response contracts for every worker.
- `src/models.ts` is the persisted session and application model.
- `public/service-worker.js` caches fetched source assets for repeat use.

## Data flow

`ProjectSession` is the single source of truth. UI edits pass through `useProject`, which serializes IndexedDB writes so rapid edits cannot overwrite newer state. Map movement checkpoints only the view; it does not restart tile planning.

Use `save` for view, coverage, and metadata changes. Use `saveRender` only when an edit changes exported pixels; it advances the render cache namespace. This distinction prevents selection-range edits from invalidating rendered source tiles.

Enabled geographic selections are the single source of export coverage. `useTileEstimate` sends their geometry and zoom ranges to a worker, stores exact plans in IndexedDB, and reuses matching plans during export. Preview rendering is intentionally independent from export planning.

Coverage planning and output sizing are separate. Geometry or zoom-range changes recalculate touched tiles; changing MTB depth only summarizes the existing tile plan with a different number of bytes per tile.

Source assets are cached without modification. The renderer composes vector or raster source data, markers, and visible GeoJSON. E-ink conversion is a final pixel step shared by preview and export. Selection outlines are editor-only and are drawn after conversion.

## Invariants

- A search result changes export coverage only when the user chooses **Add area**.
- Every export tile comes from an enabled selection; overlapping selections produce one tile.
- Imported geometry stays exact when it becomes a selection.
- Native source zoom and derived display zoom are distinct. Derived zoom rerenders vector data; it is not a stretched screenshot.
- Marker and selection IDs are stable and never depend on array position.
- Reset removes only this application's storage and caches.
- Session validation happens at the storage boundary so the rest of the app only handles the current schema.
- Version 3 is the only accepted session schema; deliberately add a new version only when the persisted shape truly changes.

When adding behavior, prefer a small pure function in `src/browser/` with a focused test. Keep network, worker, and persistence boundaries explicit; keep React components concerned with user interaction and rendering.

For deeper maintenance guidance, see the repository [developer handbook](../docs/README.md), especially [Architecture](../docs/architecture.md), [Rendering](../docs/rendering.md), [State and caching](../docs/state-and-caching.md), and [Contributing](../docs/contributing.md).
