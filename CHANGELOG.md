# Changelog

## Unreleased

- Added flash usage bars in the Export panel showing how much of the available firmware flash the tile data will consume on ESP32-S3 and nRF52840 targets. Bars turn yellow above 60% and red above 85%.
- In InkHUD mode, flash bars update live as zoom range changes. Estimate shows as upper bound (≤) since RLE compression typically reduces the actual size by 70–90%.
- In other modes, bars update on explicit Estimate click.
- Added a Cancel button that appears during export and stops tile downloading cleanly between tiles.
- **InkHUD grid expanded from 3×3 to 4×4 tiles per zoom level.** Each zoom now exports 16 tiles (128 KB uncompressed) instead of 9, providing significantly more coverage around the map center.
- **InkHUD export format changed to sparse per-tile layout.** Each 256×256 tile is stored individually with parallel `map_tile_zooms[]`, `map_tile_tx[]`, `map_tile_ty[]`, and `map_tile_data[]` arrays. Firmware looks up tiles by `(zoom, tx, ty)` at render time rather than using a fixed mosaic layout. This matches the InkHUD2 format and allows both modes to share the same firmware rendering path.
- **Added InkHUD2 export mode** for nRF52840 and other flash-constrained targets. In InkHUD2 mode, click individual tiles on the map to select a sparse, non-contiguous coverage area across multiple zoom levels. An "Add 3×3 here" button adds a 3×3 block at the current map center and zoom. Flash size updates live as tiles are selected. Exports the same sparse `map_tile.h` format as InkHUD.
- **Added coverage overlay toggle** in InkHUD mode. A "Coverage" checkbox next to the Export button draws dashed per-zoom bounding boxes on the map preview, showing the exact 4×4 tile footprint that will be exported at each configured zoom level. Boxes represent actual tile boundaries and update as zoom range or map center changes.
- Fixed InkHUD export bounding box to correctly span the full 4×4 tile grid (was previously spanning only 3 tiles wide/tall due to off-by-one in the west/north boundary calculation).

## 1.1.0 - 2026-06-17

- Added an alternate `osm-eink-topo` map style with hillshade and contour overlays from Mapzen Terrain Tiles on AWS Open Data.
- Added regular `osm-eink` map exports through zoom 16 using crisp vector overzooming.
- Made topo mode use its own cleaner default layer set: land, water, labels, and trails/paths.
- Allowed regular and topo preview/export through zoom 16.
- Added crisp vector overzooming for zooms 15-16 so zoom-14 OpenFreeMap labels, land/water shapes, roads, and trails can remain visible without raster blur.
- Made the visible map view the export area automatically and added a center marker to the preview.
- Removed the desktop layout selector; normal exports now use one fixed tile-bundle layout, while InkHUD export generates the firmware header.
- Added InkHUD mode defaults for brightness `1.03` and contrast `2.41` when the user has not manually changed those sliders.
- Aligned CLI defaults with the desktop app defaults and removed stale desktop preview/source code.
- Raised desktop preview zoom to 16 for closer topo inspection.

## 1.0.0 - 2026-06-16

First stable local-only Windows release.

- Added a native desktop app for selecting an area, previewing e-paper map tiles, and exporting offline bundles.
- Uses OpenFreeMap vector tiles by default and renders PNG tiles locally.
- Preview now uses the same export renderer as downloaded OpenFreeMap tiles, so the visible map matches the generated output.
- Added cursor-anchored mouse-wheel zoom and pan interaction.
- Added collapsible app sections, compact controls, export progress, and output folder access.
- Added map element toggles with buildings and POI disabled by default.
- Tuned default e-paper settings: grayscale mode, brightness `0.99`, contrast `1.15`, mono threshold `120`.
- Hid the mono threshold control unless mono output mode is selected.
- Includes README, license, notices, manifest, and attribution files for release and exported bundles.
