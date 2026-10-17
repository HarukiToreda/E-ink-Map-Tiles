# Architecture

E-ink Map Tiles has two independent applications behind small platform launchers: Bash on Unix-like systems and PowerShell on Windows. Node/Vite starts the browser application; Python starts the preserved Tk desktop application. The browser owns search, map rendering, tile planning, conversion, persistence, compression, and downloads. There is no application API and no Python processing backend.

## Runtime boundary

```mermaid
flowchart LR
    User[User] --> UI[React UI]
    UI --> Project[Project state]
    UI --> Preview[Canvas preview]
    UI --> Estimate[Coverage estimate worker]
    UI --> Export[Export coordinator]

    Project <--> IDB[(IndexedDB)]
    Project --> Checkpoint[(localStorage view checkpoint)]

    Preview --> Renderer[Native tile renderer]
    Export --> Renderer
    Renderer --> Sources[Map source requests]
    Sources <--> SW[(Service Worker Cache Storage)]

    Estimate --> Plans[(IndexedDB tile plans)]
    Export --> Plans
    Export --> Convert[Conversion worker]
    Export --> Writers[ZIP / PMTiles / MTB writers]
    Writers --> Download[Browser download]

    Search[Search and boundary providers] --> UI
    Bash[Bash launcher] --> Mode{UI mode}
    PowerShell[PowerShell launcher] --> Mode
    Mode -->|web| Node[Node / Vite]
    Node --> UI
    Mode -->|tkinter| Python[Python / Tk]
```

## Module ownership

```mermaid
flowchart TD
    Main[main.tsx<br/>bootstrap and fatal boundary] --> App[App.tsx<br/>workflow coordinator]
    App --> Sidebar[components/<br/>controls and presentation]
    App --> Map[BrowserMap.tsx<br/>viewport and preview]
    App --> Hooks[hooks/<br/>project and estimate lifecycles]

    Sidebar --> Models[models.ts<br/>shared domain model]
    Map --> Browser[browser/<br/>domain and infrastructure]
    Hooks --> Browser
    App --> Browser

    Browser --> Workers[Web Workers]
    Browser --> Storage[IndexedDB / localStorage]
    Browser --> Network[External source providers]
    Browser --> Files[Download artifacts]
```

Ownership rules:

- `App.tsx` coordinates user workflows; it should not contain binary encoding, map math, or provider-specific parsing.
- Components render controls and report user intent. They do not own durable project state.
- Hooks own asynchronous React lifecycles and connect React to browser services.
- `webui/src/browser/` contains framework-independent logic, browser infrastructure, workers, renderers, and writers.
- `models.ts` describes the current in-memory and persisted application model.
- Worker request and response shapes live in one place so both sides compile against the same contract.

## Principal data flow

```mermaid
sequenceDiagram
    actor User
    participant Component
    participant App
    participant Project as useProject
    participant DB as IndexedDB
    participant Map as BrowserMap
    participant Estimate as Estimate worker

    User->>Component: Change a setting
    Component->>App: Report intent
    App->>Project: save or saveRender mutation
    Project->>Project: Clone editable containers
    Project-->>Component: Publish optimistic snapshot
    Project->>DB: Queue serialized write

    alt Pixel-affecting edit
        Project-->>Map: New render revision
        Map->>Map: Render visible tiles
    else Coverage-only edit
        Project-->>Estimate: New selection geometry/range
        Estimate-->>Project: Exact tile plan and progress
    else View-only edit
        Project->>Project: Checkpoint view immediately
        Project-->>Map: New center/zoom
    end
```

## Selection and export authority

```mermaid
flowchart TD
    SearchResult[Search result] -->|View| Viewport[Viewport only]
    SearchResult -->|Add area| Selection[Area selection]
    GeoJSON[Imported GeoJSON] --> Layer[Visible editor layer]
    Layer -->|Add visible layers| Selection

    Selection -->|enabled + zoom range + geometry| Planner[Exact coverage planner]
    Planner --> Deduplicate[Deduplicate z/x/y]
    Deduplicate --> Export[Export tiles]

    Viewport -. does not control .-> Export
    Layer -. visibility alone does not control .-> Export
```

Enabled selections are the only authority for export coverage. The viewport is an editor camera, not an export rectangle. A visible GeoJSON layer affects rendered pixels but does not become coverage until explicitly converted into a selection.

## Asynchronous work

```mermaid
flowchart LR
    Main[Main thread] -->|coverage + cached plans| EW[Estimate worker]
    EW -->|progress| Main
    EW -->|tiles + cache writes| Main

    Main -->|RGBA + depth| CW[Conversion worker]
    CW -->|grayscale or packed bytes| Main

    Main -->|coverage| PW[Export planning worker]
    PW -->|deduplicated tiles| Main
```

- Geometry intersection is isolated from rendering and can be terminated by destroying its worker.
- Pixel conversion runs in a reusable worker client and transfers buffers instead of cloning completed results.
- Export rendering remains on the main thread because the renderer uses DOM Canvas APIs. Network and rendering concurrency is bounded.

## Error boundaries

```mermaid
flowchart TD
    Failure[Failure] --> Kind{Where?}
    Kind -->|React render| Fatal[AppErrorBoundary<br/>reload screen]
    Kind -->|Search/import/save| Status[Visible toolbar error]
    Kind -->|Estimate worker| EstimateError[Export estimate error]
    Kind -->|Export| ExportJob[Failed or cancelled job]
    Kind -->|Optional terrain| BaseMap[Continue with base vector map]
    Kind -->|Cache write| Continue[Continue without cache]
```

Optional caches and topography degrade gracefully. Format generation, primary map-source failures, invalid sessions, and durable-save failures remain visible because silently continuing could produce an incorrect artifact.

## Non-negotiable invariants

1. Preview and export use the same native tile renderer and e-ink conversion.
2. Selection outlines are editor chrome and never enter an export.
3. Source responses are cached unchanged; conversion happens after rendering.
4. Search never adds coverage without an explicit **Add area** action.
5. Every exported tile comes from at least one enabled selection.
6. Overlapping selections emit a tile only once.
7. Imported session data is normalized at the storage boundary.
8. Geometry payloads are immutable after import so large objects can be retained by reference.
9. A source/style/marker/visible-overlay edit must advance `render_revision`.
10. A selection zoom-range edit must not invalidate rendered pixels.

## Where a change belongs

| Change                               | Primary location                                             | Required coverage                                         |
| ------------------------------------ | ------------------------------------------------------------ | --------------------------------------------------------- |
| Persisted session shape              | `models.ts` and `session.ts`                                 | Session normalization and persistence tests               |
| Rendered map pixels                  | `nativeRenderer.ts`, `eink.ts`, or related rendering modules | Focused renderer or conversion tests                      |
| Tile coverage                        | `tiles.ts`, the planning workers, and `workerProtocol.ts`    | Tile-planning and worker-contract tests                   |
| Download encoding                    | The corresponding format writer                              | Byte-level tests and an independent reader where possible |
| Search or boundary-provider behavior | `search.ts`                                                  | Mocked provider success, fallback, and failure tests      |
| Interface behavior only              | The responsible component, hook, or `App.tsx` workflow       | Component logic plus browser inspection                   |

See [Contributing](contributing.md) for the corresponding verification checklist.
