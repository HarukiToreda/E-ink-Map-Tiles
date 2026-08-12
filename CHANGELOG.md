# Changelog

---

## v2.1.0

### Map rendering

- Pedestrian streets (`highway=path`/`pedestrian`, e.g. Black Rock City's grid) now render as solid streets instead of thin dashed lines; true trails stay dashed.
- POI labels wrap and center below the marker (OSM style), are never truncated, skip overlaps, and stay inside the tile.

### Per-zoom grid sizes (classic InkHUD)

- **Each zoom level can now have its own grid size in classic InkHUD mode.** Open **Custom** in Export Settings and every zoom in the Min–Max range gets its own grid dropdown alongside its include toggle. This lets coarser zooms cover the *same* footprint as a finer one — e.g. set z16 to 8×8 and z15 to 4×4 so both cover an identical area (halve the grid for each zoom level you drop). Previously the classic InkHUD grid used one fixed tile count for every zoom.
- **No firmware change required.** When all active zooms share one grid, the export uses the compact fixed-grid layout as before. When grids differ, it automatically falls back to the sparse per-tile layout (the same one InkHUD2 uses), which the current firmware already reads. The export log and `MapTile.h` header note when the sparse fallback is used.
- Coverage boxes, the flash-size estimate, and the tile count all update live to reflect per-zoom grids, and per-zoom grids are saved and restored with sessions.

### GeoJSON overlays

- **Import GeoJSON files as map overlays** — points, lines, and polygons are drawn on the preview and baked into InkHUD exports, same as markers. Supports `.geojson`/`.json` with Point/MultiPoint/LineString/MultiLineString/Polygon/MultiPolygon/GeometryCollection.
- Per-layer visibility toggle, per-layer zoom range (geometry only draws within its configured zoom range), and per-layer label toggle.
- Labels auto-extracted from `name`/`NAME`/`label`/`title` properties, rendered as black text with a white halo (no background box), with a separate global zoom range for when labels appear.
- **Fit view to GeoJSON extent** and **Select same-box InkHUD2 tiles** — computes the exact tiles needed to cover a layer's bounding box at every zoom in your Min–Max zoom range, so e.g. z15 and z16 cover the same area (see the per-zoom grid sizes above for the same result in classic InkHUD mode).

### Markers

- Added **Toilet** and **Heart** icons.
- Marker icon picker buttons are bigger (32×32).
- Retuned per-zoom marker sizes so z13/z14 stay legible instead of shrinking to a 6px floor.

### Fixes

- GeoJSON overlays and markers could render in the wrong stacking order, letting lines/polygons paint over marker icons. Markers now always render on top regardless of which overlay was redrawn most recently.

---

## v2.0.0

- **New `MapTile.bin` SD card export** — **⬡ Export for InkHUD (SD Card)** packs the same tiles as `MapTile.h` into a binary file for devices that read tiles from an SD card instead of flash.
- **Fixed: InkHUD Firmware Builder required a system Git install** — first-run setup now bundles a portable Git, so no target device needs anything pre-installed.

---

## v1.9.0

### InkHUD tile compression

- **InkHUD `MapTile.h` exports now fit more map data into the same flash** — fixed-grid exports use a more compact block layout instead of repeating per-tile coordinates, and fully white/black tiles are stored as sentinels with no payload bytes.
- **Flash estimates now include the new compact InkHUD header layout** — the estimate path matches export behavior for LZ4 high-compression, deduplicated payloads, white/black sentinels, and grid-metadata savings.

---

## v1.8.0

### Hospital cross icon

- Added a "Hospital" icon to the Markers panel.

### Fixes

- **InkHUDBuilder no longer touches ambient system installs** — PlatformIO's core dir is now isolated under its own AppData folder, `MSYSTEM` no longer leaks into the build env, and first-run Python setup uses a zero-registry-footprint distribution instead of the MSI installer (which failed if any Python 3.12.x was already installed).
- **Cursor-anchored zoom no longer drifts off target** — fixed the anchor math (was snapping to screen center) and locked the anchor for the duration of a scroll burst.
- **Map panning no longer flashes empty tiles or a stray box** — overlays now stay visible while dragging, the preview renders a small buffer beyond the edges, and the leftover export-area outline was removed.
- **InkHUD zoom/pan no longer slows down mid-calculation** — the background flash-size worker now pauses during interaction and resumes after, and its coverage overlay updates in place instead of recreating itself every drag step.

---

## v1.7.0

### New Tool — InkHUD Firmware Builder

**`InkHUDBuilder.exe`** — standalone Windows tool for building and flashing Meshtastic InkHUD firmware. No Git, Python, PlatformIO, or VS Code required.

- Downloads Python + PlatformIO on first run, auto-clones/updates the firmware repo.
- Optionally bakes a `MapTile.h` from the EinkMapTile Tool into the build.
- Builds any of 14 InkHUD devices; Build + Flash or Upload-only; branch selector; Clean button resets everything.

### Docs

- Added `README-firmware-builder.md`; updated `README.md` with a companion-tool callout.

### Fixes

- **Flash estimate no longer recalculates on preview zoom** — sample key tracks map center instead of view bounds; fixed a logic error causing redundant recalculation; in-progress workers now cancel on real settings changes.

---

## v1.6.0

### UI

**Export panel cleaned up**
- Removed Browse and Folder buttons. Export Tiles now opens a folder picker before starting so you choose where tiles go each time.
- Output path field removed from Export Settings.
- Status bar label removed.

**InkHUD-only controls now hidden in other modes**
- Grid size, Coverage toggle, Custom zoom button, and Export for InkHUD button are hidden when mode is not `inkhud` or `inkhud2`. They appear automatically when switching to an InkHUD mode.
- Coverage toggle moved to the Export Settings Grid row, next to the Custom button.
- Export for InkHUD button now spans the full width of the Export panel.

**Grid sizes**
- Added `1×1` grid option.

**Custom zoom toggle wrapping**
- Per-zoom toggles in the Custom panel now wrap to a new row after every 8 zoom levels so all toggles remain accessible when a wide zoom range is selected.

**Flash usage bars**
- Added flash bars for all InkHUD-relevant flash targets: ESP32-S3 4 MB, ESP32-S3 8 MB, ESP32-S3 16 MB, and nRF52840 1 MB.
- Available flash figures are based on real InkHUD builds: 54,953 bytes free on a 4 MB ESP32-S3 (T3S3), 48,400 bytes free on nRF52840 (L1); 8 MB and 16 MB figures are estimated pending builds.
- Bars show "Calculating…" while the background LZ4 sample is running instead of displaying a potentially wrong early estimate.

**Coverage toggle**
- Coverage is now on by default when switching to InkHUD or InkHUD2 mode.
- Label changed to "Coverage / Boxes" stacked on two lines to fit the grid row without truncation.

**InkHUD default zoom range changed to 11–15**
- Switching to InkHUD or InkHUD2 mode now defaults to zoom 11–15 instead of 8–13, which better matches typical street-level use.

**Section hints**
- All collapsible sections and the Export panel now show a brief description next to their title so the purpose of each section is clear at a glance.

**Search bar placeholder**
- The map search bar now shows "City, address, zip code, landmark…" as placeholder text and clears on focus.

**Markers icon grid**
- Icons rearranged to 8 per row (2 rows of 8) to fill the available width without dead space.
- Placement hint ("Click an icon, then click the map to place it at those coordinates.") shown below the icon grid, wrapping correctly at any panel width.

---

## v1.5.0

### Performance

**InkHUD export is now much faster**
- The export no longer downloads every tile in the full bounding box. It now fetches only the exact g×g tiles needed per selected zoom level, directly and in parallel across 8 threads. A 2×2 grid with 3 zooms goes from thousands of tile downloads to 12.
- Bit-packing is now vectorized with numpy instead of a pure-Python pixel loop, giving a significant speedup for that step.
- Fixed a transposition bug in the numpy bit-packing that caused tile pixel data to be scrambled in the exported header.

### Fixes

**Session save and load now fully restores all settings**
- Min/max zoom, Custom zoom toggle state (which zoom levels are included), output folder, map source URL, area center/radius, section collapse state, brightness, contrast, map elements, and markers are all saved and restored correctly.
- Previously, loading a session while in InkHUD mode would reset min/max zoom to 8/13 due to a mode-change callback overwriting the restored values during load.

**Flash size estimate now samples all tiles in the grid**
- The estimate previously sampled only the center tile per zoom level and multiplied by the grid size. It now renders and compresses every tile in the g×g grid, giving an accurate prediction that reflects variation across the full export area.

**Excluded zoom levels are now respected during export**
- Zoom levels toggled off via the Custom button were correctly excluded from the flash estimate and coverage overlay, but were still being exported to the firmware header. The export now honors the same active-zoom set used for the estimate.

---

## v1.4.0

### Map Rendering

**InkHUD image pipeline**
- Replaced Bayer dithering with a softer 3-zone approach: pixels ≤175 go solid black, pixels in 175–215 get light Bayer dithering at level 220 (~8% black dots), pixels >215 go solid white. Preview and device output now match exactly.
- Default brightness and contrast for InkHUD and InkHUD2 modes changed to 0.96.
- Building outlines added — buildings now render with a thin black border so they are visible on the map.
- Land dither protection is now scoped: when the Land layer is enabled, pixels in the 175–215 raw gray range are locked to the dither zone so parks and landcover never crush to solid black at high contrast settings. When Land is off, the pipeline is unchanged — non-land features such as road casings are unaffected.
- Minor, service, and primary (z<12) road casing colors darkened to sit below the dither threshold so they always render as solid lines regardless of contrast.

### Export

**InkHUD flash size estimate**
- The pre-export flash size estimate now samples one real tile per zoom level at the center of the export area, LZ4 compresses each, and sums the results. This replaces the previous fixed compression factor, giving an accurate size prediction that reflects actual map content and contrast settings. The sample runs automatically in the background about one second after settings change.

**Custom zoom selection**
- New **Custom** button in InkHUD export settings reveals per-zoom toggles for every zoom level in the min–max range. Toggle individual zooms off to exclude them from the export. The flash size estimate and coverage overlay update immediately to reflect the active set.

**Output filename**
- Exported firmware header renamed from `map_tile.h` to `MapTile.h` to match firmware naming conventions.

**Waterways**
- River, canal, stream, drain, and ditch widths now scale with zoom level based on real-world metres per pixel (rivers widen at z15/z16, streams stay thin).
- Waterway names (rivers, creeks, streams) appear at zoom 15 and 16, rotated along the flow direction — same rendering engine as trail labels.
- Waterway names are placed at the flattest (least-curved) section of each waterway so the full name fits cleanly.
- Waterway labels respect a shared collision list with trail labels and are suppressed on busy tiles.

**Custom markers**
- Text label markers now render as white box with black text and a black outline instead of black box with white text.

---

## v1.3.1

### New Features

**Location search**
- Search bar in the map preview header. Type any place name and press Enter or click Search to jump the map there.
- Accepts city names, addresses, landmarks, national parks, mountains, lakes, zip codes, or any location OpenStreetMap recognizes.
- Map zooms automatically to fit the result using the bounding box returned by Nominatim.

### UI

- Full dark UI redesign: navy sidebar, teal accents, dark Windows title bar.
- Checkboxes replaced with animated toggle switches.
- Sliders replaced with pill-style sliders with teal fill.
- Rounded buttons with hover states throughout.
- Removed top header bar to reclaim vertical space.
- Flash usage bars now hidden in non-InkHUD modes (still visible in InkHUD/InkHUD2 for estimates).
- Progress bar and Cancel button only appear while an export is running.
- Removed Estimate button — tile count and flash estimates update automatically as settings change.

### Platform

- Linux and macOS support: run from source with `run.sh` or build with `EinkMapTiles-linux.spec`.
- Multi-platform GitHub Actions workflow — Windows, Linux, and macOS binaries built and attached automatically on each release tag.

---

## v1.3.0

### New Features

**Custom markers**
- Place icons on the map that get baked directly into exported tiles. No firmware changes required.
- 16 icon types: Parking, Sun, Star, Home, Fish, Bridge, Picnic, Bathroom, Binoculars, Hunting, Tent, RV, Tree, Group, Car, Campfire.
- Icons are white symbols on a black square (sign-board style).
- Each marker has a min/max zoom range — only appears in tiles at those zoom levels.
- Click an icon button to select it and enter placement mode, then click the map to drop it. Click the same icon again to cancel.
- Marker list shows all placed markers with type, zoom range, coordinates, and a delete button.
- Click any row to select it — a blue highlight appears on the map and the marker can be dragged to a new position in real time.
- Icon size in the preview scales with zoom — half the pixel size per zoom level out, matching map scale.

**Custom text labels**
- Type any text in the Label text field, set a font size (pt), set zoom range, click Place Label, then click the map.
- Labels render as white text on a black background rectangle, same sign-board style as icons.
- Font size scales with zoom the same way icons do.
- Labels appear in the marker list and support the same drag-to-move and delete as icons.

**Session save/load**
- Save and restore the full tool state to a JSON file: map center, zoom, all export settings, map elements, markers (including labels with text and font size), and InkHUD2 tile selection.
- Save Session / Load Session buttons in the Export panel.

### Fixes

**InkHUD export matches coverage overlay**
- Exported tiles now exactly match the Coverage overlay boxes at every zoom level. Previously the export was offset by one tile northwest of the overlay due to a double-subtraction of the grid half-offset.

**Grid centering corrected**
- Grid origin uses `floor(cx - N/2 + 0.5)` so the tile containing the center is always inside the exported area and tile coordinates are clean integers at every zoom level.

**Add NxN Here button centered correctly (InkHUD2)**
- Button now places the grid centered on the clicked tile.

**Coverage overlay rendering fixed**
- A class name bug silently skipped drawing coverage boxes in some cases.
