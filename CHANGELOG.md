# Changelog

---

## Unreleased (since v1.3.1)

### Map Rendering

**InkHUD image pipeline**
- Replaced Bayer dithering with a softer 3-zone approach: pixels ≤175 go solid black, pixels in 175–215 get light Bayer dithering at level 220 (~8% black dots), pixels >215 go solid white. Preview and device output now match exactly.
- Default brightness and contrast for InkHUD and InkHUD2 modes changed to 0.96.
- Building outlines added — buildings now render with a thin black border so they are visible on the map.

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
