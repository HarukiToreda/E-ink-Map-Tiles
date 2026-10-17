# Contributing

This guide is the shortest safe path from checkout to a reviewable change. Read [Architecture](architecture.md) first if the change crosses more than one subsystem.

## Prerequisites

- Python 3.10 or newer; CI uses Python 3.12.
- Node.js 22 or newer.
- A modern browser with Canvas, Web Workers, IndexedDB, Cache Storage, and service-worker support.
- Network access only for live map/search use. Automated tests are network-independent.

## Setup

From the repository root:

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
cd webui
npm ci
```

Run the frontend during development:

```bash
./scripts/eink-map-tiles.sh --ui=web
```

The Bash and PowerShell launchers install locked npm dependencies when `webui/node_modules/` is absent, build the production application, start Vite’s preview server on port 8765, and let Vite select a nearby port when it is occupied. For hot-module replacement while developing, run `npm run dev` from `webui/` instead.

## Development loop

```mermaid
flowchart LR
    Understand[Identify authority and invariant] --> Small[Make the smallest cohesive change]
    Small --> Focused[Run focused test]
    Focused --> Check[npm run check]
    Check --> Build[npm run build]
    Build --> Smoke[Inspect production build when wiring changed]
    Smoke --> Docs[Update docs and plan]
    Docs --> Review[Review source diff]
```

Prefer pure functions for math, parsing, validation, and encoding. Keep network and storage operations at explicit boundaries. Avoid adding an abstraction until at least two real callers need the same policy.

## Repository map

```mermaid
flowchart TD
    Root[Repository] --> Web[webui/]
    Root --> Py[src/eink_map_tiles/]
    Root --> Docs[docs/]
    Root --> Launch[scripts/eink-map-tiles.sh]
    Root --> WinLaunch[scripts/eink-map-tiles.ps1]

    Web --> Components[webui/src/components/]
    Web --> Hooks[webui/src/hooks/]
    Web --> Browser[webui/src/browser/]
    Web --> Models[webui/src/models.ts]

    Py --> Desktop[original desktop code]
    Py --> Tests[tests/]
    Web --> Dist[dist/ generated and ignored]
    Launch --> Web
    Launch --> Py
    WinLaunch --> Web
    WinLaunch --> Py
```

The original Tk application is preserved. Browser-only work should not move rendering or export logic into Python.

## Choosing a state mutation

```mermaid
flowchart TD
    Mutation[Session mutation] --> Pixel{Could exported pixels for the same z/x/y change?}
    Pixel -->|Yes| Render[Use saveRender]
    Pixel -->|No| Camera{Only center/zoom?}
    Camera -->|Yes| View[Use updateView]
    Camera -->|No| Save[Use save]
```

This decision is part of render-cache correctness. See [State and caching](state-and-caching.md) for examples.

## Adding a persisted field

```mermaid
flowchart TD
    Model[Add field to models.ts] --> Default[Add default in session.ts]
    Default --> Normalize[Validate/normalize unknown input]
    Normalize --> Copy[Update editable copy if nested/mutable]
    Copy --> UI[Add UI and correct save path]
    UI --> Tests[Add schema and behavior tests]
    Tests --> Docs[Update session documentation]
```

Do not read imported JSON with a type cast and trust it. All external session data enters as `unknown` and must be normalized. Version 3 is currently the only accepted schema.

## Adding a map source

```mermaid
flowchart TD
    Need[New source] --> Terms[Confirm offline/export terms and attribution]
    Terms --> Capability[Define kind, scope, native max, controls]
    Capability --> Config[Add mapConfig definition]
    Config --> Fetch[Implement source fetch/decode]
    Fetch --> Render[Integrate shared renderer]
    Render --> Cache[Add service-worker host only if appropriate]
    Cache --> Test[Test failure, native max, derived zoom]
    Test --> Docs[Update provider/render docs]
```

Checklist:

- Browser CORS works without a secret embedded in the client.
- Offline/export use is permitted for the intended deployment.
- Attribution is exact and included in the footer and artifacts.
- Native maximum zoom is verified from the service, not guessed.
- Derived zoom semantics are explicit.
- Source failures are visible unless the layer is optional.
- Element controls are offered only when the renderer can honor them.

## Changing vector style or labels

Keep schema knowledge and declarative policy distinguishable from Canvas mechanics. A style change normally belongs in `nativeRenderer.ts` today; if policy is extracted, use one `vectorStyle.ts` authority rather than scattered constants.

```mermaid
flowchart LR
    SourceLayer[OpenMapTiles layer] --> Classify[Feature class policy]
    Classify --> Paint[Color/width/visibility policy]
    Paint --> Canvas[Shared Canvas mechanics]
    Canvas --> Convert[Full color or e-ink conversion]
```

Verify low zoom, the source-native maximum, and at least one derived zoom. Roads and labels must remain legible in MTB1, not merely attractive in color.

## Adding a provider

Provider-specific response shapes must stop at `search.ts` or a small adjacent adapter. React receives normalized `SearchResult` values only.

```mermaid
flowchart LR
    JSON[Unknown provider JSON] --> Guard[Runtime decoder]
    Guard --> Normalize[Domain normalization]
    Normalize --> SearchResult[SearchResult]
    SearchResult --> React[UI]
```

Document fallback position, timeout, scope, public-service policy, and attribution. Add mocked tests; never use the live service in CI.

## Adding an export kind

```mermaid
flowchart TD
    Consumer[Identify authoritative consumer] --> Contract[Write byte/path contract]
    Contract --> Kind[Add ExportKind]
    Kind --> UI[Expose only in compatible mode]
    UI --> Writer[Implement focused writer]
    Writer --> Exporter[Connect shared tile plan/render loop]
    Exporter --> Tests[Structural and independent-reader tests]
    Tests --> Target[Validate actual downstream consumer]
    Target --> Docs[Document destination and compatibility]
```

Do not duplicate map rendering inside a format writer. Writers receive rendered pixels or packed tiles from the shared pipeline.

## Adding or changing a worker

1. Define request and discriminated response unions in `workerProtocol.ts`.
2. Keep one long-lived worker only when work is naturally reusable; otherwise create one per calculation and terminate it.
3. Include an explicit error response and an `onerror` path.
4. Transfer large completed buffers rather than cloning them.
5. Decide what cancellation means and reject pending callers predictably.
6. Throttle progress messages so they do not become the workload.

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Running: request
    Running --> Running: throttled progress
    Running --> Complete: result
    Running --> Failed: error
    Running --> Cancelled: terminate or abort
    Complete --> [*]
    Failed --> [*]
    Cancelled --> [*]
```

## Generated frontend assets

`npm run build` writes to `webui/dist/`. That directory contains deployable content-hashed bundles and is deliberately ignored. Never copy generated Web UI files into the Python package or commit them.

```mermaid
flowchart LR
    Source[webui source] --> TSC[TypeScript build]
    TSC --> Vite[Vite production build]
    Vite --> Dist[webui/dist]
    Dist --> Deploy[Static hosting or release artifact]
    Dist --> Preview[Vite preview server]
    Preview --> Launcher[scripts/eink-map-tiles.sh --ui=web]
    Source --> Dev[npm run dev with HMR]
```

After a build:

- Do not commit `dist/`, `node_modules`, `*.tsbuildinfo`, or emitted `vite.config.js`/`.d.ts` files.
- Confirm `dist/index.html` references files present in the same build.
- Deploy the complete `dist/` directory atomically; do not combine output from separate builds.
- Commit source assets from `webui/public/` when they intentionally change.

## Required checks

From `webui/`:

```bash
npm run check
npm run build
```

From the repository root:

```bash
.venv/bin/python -m pytest -q
git diff --check
```

Run a fresh-browser production-build smoke when changing bootstrap, persistence, workers, service-worker behavior, generated asset paths, or the launcher. See [Testing strategy](testing.md).

## Review checklist

```mermaid
flowchart TD
    Review[Review change] --> Scope{One cohesive responsibility?}
    Scope -->|No| Split[Split or explain coupling]
    Scope -->|Yes| Authority{One source of truth?}
    Authority -->|No| Centralize[Remove duplicated policy]
    Authority -->|Yes| Boundary{External data validated?}
    Boundary -->|No| Guard[Add runtime guard]
    Boundary -->|Yes| Cache{Invalidation correct?}
    Cache -->|No| Fix[Fix save/cache key]
    Cache -->|Yes| Tests{Tests describe contract?}
    Tests -->|No| Add[Add focused readable tests]
    Tests -->|Yes| Ready[Ready for review]
```

Before handing off:

- The change has a single clear authority for new policy.
- Preview and export still share rendering/conversion.
- Selection coverage remains independent from the viewport.
- New external JSON is treated as unknown.
- Errors are visible at the correct boundary.
- Cache invalidation is no broader than necessary and never too narrow.
- Tests explain the expected behavior without opaque snapshots or data-only golden files.
- Documentation names any downstream or provider assumption.
- `npm run check`, production build, Python tests, and `git diff --check` pass.

## Commit hygiene

Do not mix personal editor configuration into a project change. Preserve unrelated working-tree changes. Commit frontend source and public assets, but leave generated `dist/` bundles, local caches, and compiler metadata ignored.
