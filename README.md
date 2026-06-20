# E-ink Map Tiles

Version 1.1.0

Local-only Windows desktop app for generating e-paper-friendly offline map tiles for InkHUD in the Meshtastic firmware repo.

Exports normal XYZ tile folders with attribution and a manifest, and InkHUD firmware headers (`map_tile.h`) with LZ4-compressed column-major tiles ready for ESP32-S3 and nRF52840 targets.

## What It Does

- Pan and zoom an interactive map preview with cursor-anchored scroll wheel zoom.
- Export the visible map area as e-paper-ready PNG tiles rendered locally from OpenFreeMap vector data.
- Export InkHUD firmware headers (`map_tile.h`) with LZ4-compressed tiles for direct inclusion in Meshtastic firmware.
- Configurable InkHUD grid sizes (2×2, 3×3, 4×4) to fit flash budgets on nRF52840.
- InkHUD2 mode for sparse per-tile selection across multiple zoom levels.
- Coverage overlay showing the exact tile footprint per zoom level before export.
- Flash usage bars showing how much of the available firmware flash the tiles will consume on ESP32-S3 and nRF52840.
- Map element toggles: land, water, roads, highways, paths, buildings, boundaries, labels, POI, transit.
- Grayscale, mono, palette, and original output modes.
- Regular map overzoom and a topo style with hillshade and contour lines.

The workflow is fully local and does not require a separate tile server.

## Basic Flow

1. Run `EinkMapTiles.exe`.
2. Pan and zoom the map preview to your area of interest.
3. Check the attribution checkbox in **Map Source**.
4. In **Export Settings**, choose zoom range, mode, style, and grid size.
5. Click **Estimate** to see tile count and flash usage.
6. Click **Export Tiles** for a normal PNG tile bundle, or **⬡ Export for InkHUD** for a firmware header.
7. Click **Folder** when done to open the output directory.

## Map Preview

The preview uses the same local vector renderer and e-paper conversion as exports — what you see matches the exported tiles.

Controls:

- **Drag** to pan.
- **Scroll wheel** zooms in or out, re-centering on the cursor position.
- **Refresh** re-renders the preview at the current view.
- The bullseye marker shows the current map center, which is used as the InkHUD export anchor.

The visible map area is the export area for normal tile exports. For InkHUD exports, the center marker position and the configured grid size determine which tiles are exported.

## Map Source

The only built-in source is **OpenFreeMap open vector tiles**. The app downloads those vector tiles and renders local e-paper PNG output — no raster tile server or separate download tool needed.

Check **I will keep required map attribution with exported tiles** before exporting. The generated `ATTRIBUTION.txt` and `manifest.json` must travel with any shared tile bundle.

## Export Settings

| Setting | Default | Notes |
|---|---|---|
| Min zoom | 4 | |
| Max zoom | 8 | |
| Mode | `grayscale` | |
| Style | `osm-eink` | |
| Grid | `4×4` | InkHUD/InkHUD2 only |
| Brightness | 0.99 | InkHUD defaults to 1.03 |
| Contrast | 1.15 | InkHUD defaults to 2.41 |
| Mono threshold | 120 | `mono` mode only, hidden otherwise |

**Output modes:**

- `grayscale` — 8-bit grayscale PNGs.
- `mono` — 1-bit black/white PNGs.
- `inkhud` — Bayer-dithered 1-bit processing matching the InkHUD firmware pipeline. Brightness and contrast default to InkHUD values when sliders are unchanged. Use **⬡ Export for InkHUD** to generate `map_tile.h`.
- `inkhud2` — Same pipeline as `inkhud`, but tiles are selected individually by clicking on the map instead of using a fixed grid. Use **⬡ Export for InkHUD** to export the selected set.
- `palette` — Indexed-color PNGs.
- `original` — Rendered PNGs with no e-paper conversion.

**Map styles:**

- `osm-eink` — Clean e-paper map. Exports through zoom 16 by clipping and redrawing zoom-14 vector data into deeper tiles — stays sharp but adds no new detail beyond zoom 14.
- `osm-eink-topo` — Topo map with hillshade and contour lines from Mapzen Terrain Tiles on AWS Open Data. Roads, buildings, POI, and transit are off by default; boundaries can be re-enabled in **Map Elements**.

## Map Elements

Toggle which layers appear in the preview and exported tiles:

| Element | Default |
|---|---|
| Land | On |
| Water | On |
| Roads | On |
| Highways | On |
| Paths | On |
| Buildings | **Off** |
| Boundaries | On |
| Labels | On |
| POI | **Off** |
| Transit | On |

Buildings and POI are off by default to reduce clutter on e-paper.

## Export Panel

The **Export** section contains:

- Tile count and flash estimate label (updates live in InkHUD mode).
- Flash usage bars for ESP32-S3 and nRF52840 targets. Bars turn yellow above 60% and red above 85%.
- **Estimate** — updates tile count and flash bars on demand (non-InkHUD modes).
- **Export Tiles** — downloads and renders the tile bundle to the output folder.
- **Folder** — opens the output folder.
- **About** — license and attribution summary.
- **⬡ Export for InkHUD** — generates `map_tile.h` for firmware inclusion.
- **Coverage** checkbox — draws dashed per-zoom bounding boxes on the map preview showing the exact InkHUD tile footprint.
- Progress bar and **Cancel** button (appear during export).
- Export log showing downloaded tile paths and progress.

## Area

The **Area** section lets you navigate to a specific location:

- Enter **Center lat**, **Center lon**, and **Radius km**, then click **Fit Center Area** to jump the map to that location.
- **Visible BBox** shows the current west/south/east/north bounds of the map view (read-only).

For InkHUD exports, only the center lat/lon matters — the grid of tiles is always centered on the bullseye.

## Output

Normal exports are saved to:

```
%USERPROFILE%\Downloads\EinkMapTiles\{export-name}\
```

Each normal export produces:

```
tiles/{style}/{z}/{x}/{y}.png
manifest.json
ATTRIBUTION.txt
{export-name}.zip
```

InkHUD exports save a single file to the chosen path:

```
map_tile.h
```

## InkHUD Firmware Export

**⬡ Export for InkHUD** generates a `map_tile.h` C header for direct inclusion in the Meshtastic firmware. Each 256×256 tile is stored as a raw LZ4 block using column-major byte layout (`[bx][y]` instead of row-major), which makes vertical map features (roads, building edges) contiguous in memory — LZ4 compresses these ~30% better than row-major layout.

Typical compression on dense urban areas: 128 KB per 4×4 zoom uncompressed → 53–57 KB after column-major LZ4.

The header uses parallel arrays:

```c
map_tile_count      // total number of tiles
map_tile_zooms[]    // zoom level for each tile
map_tile_tx[]       // tile X index
map_tile_ty[]       // tile Y index
map_tile_sizes[]    // compressed byte count for each tile
map_tile_data[]     // pointers to per-tile LZ4 byte arrays
```

The firmware decompresses tiles on demand into a 2-entry LRU cache using an inline LZ4 decompressor (~25 lines, no external dependencies). Pixel read from a decompressed buffer: `buf[(px/8)*256 + py] & (1 << (px%8))`.

**Grid size** controls how many tiles are exported per zoom level, centered on the map bullseye:

| Grid | Tiles/zoom | Uncompressed | Typical LZ4 |
|---|---|---|---|
| 2×2 | 4 | 32 KB | ~15 KB |
| 3×3 | 9 | 72 KB | ~32 KB |
| 4×4 | 16 | 128 KB | ~56 KB |

nRF52840 has approximately 85 KB available for tile data. Example combinations that fit:

- z12 2×2 + z13 2×2 + z14 4×4 ≈ 81 KB (3 zoom levels)
- z13 4×4 + z14 4×4 ≈ 112 KB (fits ESP32-S3, tight for nRF)

**Coverage overlay** — enable the **Coverage** checkbox to see dashed per-zoom bounding boxes on the map preview showing the exact tile footprint before exporting.

**InkHUD2 mode** — instead of a fixed grid, click individual tiles on the map to build a sparse, non-contiguous tile set across any combination of zoom levels. Useful when you want detailed coverage of specific areas without a uniform grid.

## Legal Map Sources

A local tool does not make every map source legal. The source must allow offline export, bulk tile generation, and redistribution if you share the output.

Good:

- OpenFreeMap vector tiles with required attribution.
- OpenMapTiles data under their license and attribution terms.
- Protomaps PMTiles extracts under their license.
- A provider API only when the provider explicitly permits bulk/offline use.

Avoid:

- `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles.
- Scraping public raster tile servers.
- Assuming "free to view" means "free to bulk download."

This is a practical checklist, not legal advice.

## Attribution

Generated bundles include `manifest.json` and `ATTRIBUTION.txt` with attribution guidance.

Baseline attribution for OSM-derived sources:

```
(c) OpenStreetMap contributors — ODbL 1.0
(c) OpenMapTiles, if using OpenMapTiles schema/data
Terrain Tiles from https://registry.opendata.aws/terrain-tiles/ — if using topo style
```
