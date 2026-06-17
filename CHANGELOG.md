# Changelog

## Unreleased

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
