# E-ink Map Tiles

Version 1.1.0

Local-only Windows desktop app for generating e-paper-friendly offline map tiles for InkHUD in the Meshtastic firmware repo.

Exports normal XYZ tile folders with attribution and a manifest, and InkHUD firmware headers (`map_tile.h`) with LZ4-compressed column-major tiles ready for ESP32-S3 and nRF52840 targets.

## What It Does

- Pan and zoom an interactive map preview with cursor-anchored scroll wheel zoom.
- Export the visible map area as e-paper-ready PNG tiles rendered locally from OpenFreeMap vector data.
- Export InkHUD firmware headers (`map_tile.h`) with LZ4-compressed tiles for direct inclusion in Meshtastic firmware.
- Configurable InkHUD grid sizes (2×2, 3×3, 4×4, 5×5, 6×6, 8×8) to fit flash budgets on nRF52840 and ESP32-S3.
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

The **Map Source** dropdown selects where tiles come from:

**OpenFreeMap open vector tiles** (default)
- Downloads OpenFreeMap vector tiles and renders e-paper PNG output locally.
- No API key or separate tile server needed.
- Supports `osm-eink` and `osm-eink-topo` styles up to zoom 16.

**USGS National Map Topo (US only)**
- Downloads pre-rendered topo tiles directly from the USGS National Map REST API.
- Public domain, no API key required, US coverage only.
- Supports up to zoom 16.
- Same style as USGS 7.5-minute quad maps: dense contour lines, hillshade, elevation labels, roads, and boundaries.
- Works with all export modes including InkHUD.

Check **I will keep required map attribution with exported tiles** before exporting. The generated `ATTRIBUTION.txt` and `manifest.json` must travel with any shared tile bundle.

## Export Settings

| Setting | Default | Notes |
|---|---|---|
| Min zoom | 4 (8 in InkHUD/InkHUD2 mode) | |
| Max zoom | 8 (13 in InkHUD/InkHUD2 mode) | |
| Mode | `grayscale` | |
| Style | `osm-eink` | |
| Grid | `4×4` | InkHUD/InkHUD2 only. Options: 2×2, 3×3, 4×4, 5×5, 6×6, 8×8 |
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

This section is only shown when **OpenFreeMap** is selected as the map source. It is hidden when USGS National Map Topo is selected, since USGS tiles are pre-rendered and layer composition cannot be changed.

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
- **Coverage** checkbox — draws solid per-zoom bounding boxes on the map preview showing the exact InkHUD tile footprint.
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

**⬡ Export for InkHUD** generates a `map_tile.h` C header for direct inclusion in the Meshtastic firmware.

### Image pipeline

Before compression, each tile goes through the InkHUD image pipeline:

1. Water detection — pixels where blue significantly exceeds red are forced black (water bodies render solid).
2. Contrast and brightness adjustment using the configured slider values.
3. Unsharp mask to sharpen edges before dithering.
4. Bayer ordered dithering — pixels are quantized to three levels (black, mid-gray, white) and then dithered using a 4×4 Bayer matrix. This produces clean, firmware-friendly patterns that compress better than error-diffusion dithering.

### Tile format and compression

Each 256×256 tile is packed to 1 bit per pixel using **column-major byte layout**: bytes are stored as `[bx=0..31][y=0..255]` rather than the usual row-major `[y=0..255][bx=0..31]`. This means each byte covers 8 horizontally adjacent pixels in a single column.

Column-major layout is chosen specifically to help LZ4. Map tiles have strong vertical structure — roads run top-to-bottom, building edges are vertical, water fills columns uniformly. In column-major order these features become long identical runs in memory, which LZ4's literal/match encoding compresses efficiently. Row-major order breaks those runs into 32-byte fragments (one row width), cutting compression ratio roughly in half.

Each packed tile is then compressed as a **raw LZ4 block** (no frame header). Typical results on dense urban map tiles:

| Layout | Compressed size per 4×4 zoom |
|---|---|
| Row-major + LZ4 | ~78–81 KB |
| Column-major + LZ4 | ~53–57 KB |

The firmware reads pixel `(px, py)` from a decompressed buffer as:

```c
buf[(px / 8) * 256 + py] & (1 << (px % 8))
```

### Header format

The header uses parallel arrays, one entry per tile:

```c
map_tile_count      // total number of tiles
map_tile_zooms[]    // zoom level for each tile
map_tile_tx[]       // tile X index
map_tile_ty[]       // tile Y index
map_tile_sizes[]    // compressed byte count for each tile
map_tile_data[]     // pointers to per-tile LZ4 byte arrays
```

The firmware decompresses tiles on demand into a 2-entry LRU cache using an inline LZ4 decompressor (~25 lines of C, no external dependencies). Cache entries are 8192 bytes each (one decompressed tile), so RAM cost is 16 KB regardless of how many tiles are in flash.

### Grid size and flash budget

**Grid size** controls how many tiles are exported per zoom level, centered on the map bullseye:

| Grid | Tiles/zoom | Uncompressed | Typical LZ4 |
|---|---|---|---|
| 2×2 | 4 | 32 KB | ~15 KB |
| 3×3 | 9 | 72 KB | ~32 KB |
| 4×4 | 16 | 128 KB | ~56 KB |
| 5×5 | 25 | 200 KB | ~90 KB |
| 6×6 | 36 | 288 KB | ~130 KB |
| 8×8 | 64 | 512 KB | ~230 KB |

nRF52840 has approximately 85 KB available for tile data. ESP32-S3 has a much larger flash budget and can accommodate 5×5, 6×6, or 8×8 grids comfortably. Example combinations that fit nRF52840:

- z12 2×2 + z13 2×2 + z14 4×4 ≈ 81 KB (3 zoom levels)
- z13 4×4 + z14 4×4 ≈ 112 KB (fits ESP32-S3, tight for nRF)

The flash bars in the Export panel show estimated usage. The estimate uses 45% of uncompressed size as a conservative upper bound based on real urban tile measurements.

### InkHUD vs InkHUD2

Both modes use the same image pipeline and the same `map_tile.h` output format. The difference is in how tiles are selected:

- **InkHUD** — fixed grid centered on the map bullseye. Every zoom level exports the same grid size (e.g. 4×4) in a square around the center. Simple and predictable.
- **InkHUD2** — click individual tiles on the map to build a sparse, non-contiguous set across any combination of zoom levels. Useful when you want dense coverage of a specific corridor or route at one zoom level and broader context tiles at another, without paying for a full uniform grid.

**Coverage overlay** — enable the **Coverage** checkbox to see solid per-zoom bounding boxes on the preview showing the exact InkHUD tile footprint before exporting.

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
