# E-ink Map Tiles

Version 1.5.0

Local-only desktop app for generating e-paper-friendly offline map tiles for InkHUD in the Meshtastic firmware repo. Runs on Windows (pre-built `.exe`) and Linux/macOS (from source).

Exports normal XYZ tile folders with attribution and a manifest, and InkHUD firmware headers (`MapTile.h`) with LZ4-compressed column-major tiles ready for ESP32-S3 and nRF52840 targets.

## What It Does

- Pan and zoom an interactive map preview with cursor-anchored scroll wheel zoom.
- Export the visible map area as e-paper-ready PNG tiles rendered locally from OpenFreeMap vector data.
- Export InkHUD firmware headers (`MapTile.h`) with LZ4-compressed tiles for direct inclusion in Meshtastic firmware.
- Configurable InkHUD grid sizes (2×2, 3×3, 4×4, 5×5, 6×6, 8×8) to fit flash budgets on nRF52840 and ESP32-S3.
- InkHUD2 mode for sparse per-tile selection across multiple zoom levels.
- Coverage overlay showing the exact tile footprint per zoom level before export.
- Flash usage bars showing how much of the available firmware flash the tiles will consume on ESP32-S3 and nRF52840.
- Custom map markers — place icons on the map that get baked into exported tiles. No firmware changes required.
- Session save/load — save and restore the full tool state (map position, settings, markers, tile selection) to a JSON file.
- Map element toggles: land, water, roads, highways, paths, buildings, boundaries, labels, POI, transit.
- Grayscale, mono, palette, and original output modes.
- Regular map overzoom and a topo style with hillshade and contour lines.

The workflow is fully local and does not require a separate tile server.

## Running on Linux / macOS

No pre-built binary is provided for Linux or macOS. Run from source:

```bash
# Install dependencies (Python 3.10+ required)
pip install -r requirements.txt

# Also install tkinter if not present (Linux)
# Debian/Ubuntu: sudo apt install python3-tk
# Arch:          sudo pacman -S tk
# Fedora:        sudo dnf install python3-tkinter

./run.sh
# or: python3 launch.py
```

To build your own binary on Linux:

```bash
pip install pyinstaller
pyinstaller EinkMapTiles-linux.spec
# Output: dist/EinkMapTiles
```

**Notes:**
- The Windows-style dark title bar is skipped on Linux/macOS — the system theme applies instead.
- Label font falls back to DejaVu Sans if Arial is not installed.

## Basic Flow

1. Run `EinkMapTiles.exe` (Windows) or `./run.sh` (Linux/macOS).
2. Pan and zoom the map preview to your area of interest.
3. Check the attribution checkbox in **Map Source**.
4. In **Export Settings**, choose zoom range, mode, style, and grid size.
5. Click **Export Tiles** for a normal PNG tile bundle, or **⬡ Export for InkHUD** for a firmware header.
6. Click **Folder** when done to open the output directory.

Tile count and flash estimates update automatically as you change settings.

## Map Preview

The preview uses the same local vector renderer and e-paper conversion as exports — what you see matches the exported tiles. At zoom 15 and 16, river and creek names appear rotated along the waterway direction.

Controls:

- **Search** — type any place name in the search bar and press Enter or click Search to jump the map there. Accepts city names, addresses, landmarks, national parks, mountains, lakes, zip codes, or any location OpenStreetMap recognizes. The map zooms automatically to fit the result.
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
| Brightness | 0.99 | InkHUD defaults to 0.96 |
| Contrast | 1.15 | InkHUD defaults to 0.96 |
| Mono threshold | 120 | `mono` mode only, hidden otherwise |

**Output modes:**

- `grayscale` — 8-bit grayscale PNGs.
- `mono` — 1-bit black/white PNGs.
- `inkhud` — Bayer-dithered 1-bit processing matching the InkHUD firmware pipeline. Brightness and contrast default to InkHUD values when sliders are unchanged. Use **⬡ Export for InkHUD** to generate `MapTile.h`.
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

- Tile count and flash estimate label (updates automatically as settings change).
- Flash usage bars for ESP32-S3 and nRF52840 targets (shown in InkHUD/InkHUD2 mode). Bars turn yellow above 60% and red above 85%.
- **Export Tiles** — downloads and renders the tile bundle to the output folder.
- **Folder** — opens the output folder.
- **About** — license and attribution summary.
- **⬡ Export for InkHUD** — generates `MapTile.h` for firmware inclusion.
- **Coverage** checkbox — draws solid per-zoom bounding boxes on the map preview showing the exact InkHUD tile footprint.
- Progress bar and **Cancel** button (appear only while an export is running).
- Export log showing downloaded tile paths and progress.
- **Save Session** / **Load Session** — save and restore the full tool state to a JSON file.

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
MapTile.h
```

## InkHUD Firmware Export

**⬡ Export for InkHUD** generates a `MapTile.h` C header for direct inclusion in the Meshtastic firmware.

### Image pipeline

Before compression, each tile goes through the InkHUD image pipeline:

1. Water detection — pixels where blue significantly exceeds red are forced black (water bodies render solid).
2. Contrast and brightness adjustment using the configured slider values.
3. Unsharp mask to sharpen edges before dithering.
4. 3-zone Bayer dithering — pixels ≤175 go solid black, pixels in 175–215 are dithered with a 4×4 Bayer matrix at level 220 (~8% black dots), and pixels >215 go solid white. When the Land layer is enabled, pixels in the 175–215 range are locked to the dither zone so parks and landcover never crush to solid black at high contrast settings. The ordered pattern compresses better than error-diffusion dithering and produces the same result on both the preview and the e-ink display.

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

**Grid size** controls how many tiles are exported per zoom level, centered on the map bullseye. The grid is positioned so the tile containing the bullseye is always inside the exported area. For even-sized grids (2×2, 4×4, etc.) the boxes at different zoom levels are concentric to within one sub-tile width — a fundamental property of the doubling tile coordinate system.

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

The flash bars in the Export panel show estimated usage. The estimate is computed by rendering and LZ4-compressing one real tile per zoom level at the center of the export area, then multiplying by the grid size. This gives an accurate prediction that reflects actual map content and contrast settings. The sample runs automatically in the background about one second after settings change.

### InkHUD vs InkHUD2

Both modes use the same image pipeline and the same `MapTile.h` output format. The difference is in how tiles are selected:

- **InkHUD** — fixed grid centered on the map bullseye. Every zoom level exports the same grid size (e.g. 4×4) in a square around the center. Simple and predictable.
- **InkHUD2** — click individual tiles on the map to build a sparse, non-contiguous set across any combination of zoom levels. Useful when you want dense coverage of a specific corridor or route at one zoom level and broader context tiles at another, without paying for a full uniform grid.

**Coverage overlay** — enable the **Coverage** checkbox to see solid per-zoom bounding boxes on the preview showing the exact InkHUD tile footprint before exporting. The exported tiles match the overlay boxes exactly — what the overlay shows at each zoom level is what will be in `MapTile.h`.

**Custom zoom selection** — click **Custom** in the InkHUD export settings to reveal per-zoom toggles for every zoom level in the min–max range. Toggle individual zooms off to exclude them from the export. The flash size estimate and coverage overlay update immediately to reflect the active set.

## Markers

The **Markers** section lets you place custom icons on the map that are baked directly into the exported tile images. No firmware changes are needed — the firmware sees them as normal tile pixels.

**Available icons:** Parking, Sun, Star, Home, Fish, Bridge, Picnic, Bathroom, Binoculars, Hunting, Tent, RV, Tree, Group, Car, Campfire

**How to place an icon marker:**
1. Set the zoom range — the marker will only appear in tiles at those zoom levels.
2. Click an icon button to select it. The cursor changes to a crosshair and the button highlights.
3. Click anywhere on the map to drop the marker. Placement mode exits automatically.
4. Click the same icon button again to cancel without placing.

**Custom text labels:**
1. Type the label text in the **Label text** field and set the font size in **pt** (default 12).
2. Set the zoom range.
3. Click **Place Label**, then click the map to drop it.

Labels render as black text on a white background rectangle with a black outline. Font size scales with zoom the same way icons do — half the pixel size per zoom level out.

**Moving and editing markers:**
- Click any row in the marker list to select it. A blue highlight appears around it on the map and the cursor changes to a move cursor.
- Drag the marker on the map to reposition it in real time.
- Click the same row again to deselect.
- For labels, the controls above populate with the label's current text, font size, and zoom range — edit them and place again to update.

Placed markers appear in the list below the icon picker with their type, zoom range, and coordinates. Click **×** to remove one.

Icons are drawn as white symbols on a black square. Text labels are drawn as black text on a white rectangle with a black outline. Size scales with zoom: half the pixel size per zoom level out.

## Session

**Save Session** and **Load Session** (in the Export panel) save and restore the complete tool state to a JSON file:

- Map center position and zoom level
- All Export Settings (mode, style, zoom range, grid, brightness, contrast)
- Map Elements toggle states
- All placed markers and labels (icon/text, font size, position, zoom range)
- InkHUD2 selected tile set

Use sessions to switch between different areas or projects without re-configuring everything from scratch.

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
