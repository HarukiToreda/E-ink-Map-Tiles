# Changelog

Unreleased changes since v1.2.0 — staged here for the next release.

---

## Unreleased (since v1.2.0)

### New Features

**Custom markers**
- Place icons on the map that get baked directly into exported tiles. No firmware changes required.
- 10 icon types: Parking, Sun, Star, Home, Fish, Bridge, Picnic, Bathroom, Binoculars, Hunting.
- Icons are white symbols on a black square (sign-board style).
- Each marker has a min/max zoom range — only appears in tiles at those zoom levels.
- Click an icon button to select it and enter placement mode, then click the map to drop it. Click the same icon again to cancel.
- Marker list shows all placed markers with icon name, zoom range, coordinates, and a delete button.
- Icon size in the preview scales with zoom — half the pixel size per zoom level out, matching map scale.

**Session save/load**
- Save and restore the full tool state to a JSON file: map center, zoom, all export settings, map elements, markers, and InkHUD2 tile selection.
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

### UI

- Removed top header bar to reclaim vertical space.
- Flash usage bars now hidden in non-InkHUD modes (still visible in InkHUD/InkHUD2 for estimates).
- Progress bar and Cancel button only appear while an export is running.
- Removed Estimate button — tile count and flash estimates update automatically as settings change.
