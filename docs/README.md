# Developer handbook

This directory explains how E-ink Map Tiles works, why it is built this way, and how to change it without accidentally breaking preview/export parity or a device format.

The root [README](../README.md) is the user guide. The [Web UI README](../webui/README.md) is the short frontend setup reference. These documents are the deeper engineering reference.

## Documents

- [Architecture](architecture.md) — runtime boundaries, module ownership, data flow, and invariants.
- [Rendering pipeline](rendering.md) — source decoding, styling, derived zoom, labels, overlays, and e-ink conversion.
- [State and caching](state-and-caching.md) — project revisions, `save` versus `saveRender`, IndexedDB, localStorage, Cache Storage, and memory caches.
- [Location providers](location-providers.md) — search and boundary-resolution order, provider response contracts, failure behavior, and public-service responsibilities.
- [Output formats](output-formats.md) — MUI XYZ, PMTiles v3, `MapTile.h`, `MapTile.bin`, MTB pixels, packing, and compression.
- [Testing strategy](testing.md) — deterministic test boundaries, inline fixtures, browser smoke testing, and release checks.
- [Contributing](contributing.md) — setup, change recipes, verification, build output, and review checklists.
- [Architecture decisions](architecture-decisions.md) — the durable reasons behind the browser-only design and its important constraints.

## Source-of-truth map

| Concern                                             | Authority                                                                                                                                      |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Preserved Python/Tk application                     | [`src/eink_map_tiles/`](../src/eink_map_tiles/)                                                                                                |
| Persisted model                                     | [`webui/src/models.ts`](../webui/src/models.ts)                                                                                                |
| Session defaults and validation                     | [`webui/src/browser/session.ts`](../webui/src/browser/session.ts)                                                                              |
| Map sources, native zooms, style paths, attribution | [`webui/src/browser/mapConfig.ts`](../webui/src/browser/mapConfig.ts)                                                                          |
| Geographic and tile math                            | [`webui/src/browser/mercator.ts`](../webui/src/browser/mercator.ts), [`webui/src/browser/tiles.ts`](../webui/src/browser/tiles.ts)             |
| Browser persistence                                 | [`webui/src/browser/storage.ts`](../webui/src/browser/storage.ts)                                                                              |
| Worker messages                                     | [`webui/src/browser/workerProtocol.ts`](../webui/src/browser/workerProtocol.ts)                                                                |
| Tile appearance                                     | [`webui/src/browser/nativeRenderer.ts`](../webui/src/browser/nativeRenderer.ts), [`webui/src/browser/eink.ts`](../webui/src/browser/eink.ts)   |
| Export orchestration                                | [`webui/src/browser/exporter.ts`](../webui/src/browser/exporter.ts)                                                                            |
| MTB formats                                         | [`webui/src/browser/mtb.ts`](../webui/src/browser/mtb.ts)                                                                                      |
| MUI PNG and PMTiles                                 | [`webui/src/browser/muiPng.ts`](../webui/src/browser/muiPng.ts), [`webui/src/browser/pmtilesWriter.ts`](../webui/src/browser/pmtilesWriter.ts) |
