# E-ink Map Tiles

Version 1.1.0

Local-only Windows desktop app for generating e-paper-friendly offline map tiles for InkHUD in the Meshtastic firmware repo.

This project is focused on the tile asset pipeline, not firmware integration. It exports normal XYZ tile folders, attribution files, a manifest, and a zip bundle, as well as InkHUD firmware headers (`map_tile.h`) with LZ4-compressed tiles.

## What It Does

- Runs as a native Windows desktop app.
- Lets you pan and zoom an interactive map preview with cursor-anchored scroll wheel zoom.
- Lets you choose an export area from the current visible map.
- Downloads OpenFreeMap vector tiles for that selected area and renders e-paper-ready PNG tiles locally.
- Exports a folder and zip bundle with `manifest.json` and `ATTRIBUTION.txt`.
- Exports InkHUD firmware headers (`map_tile.h`) with LZ4-compressed column-major tiles for ESP32-S3 and nRF52840 targets.
- Supports configurable InkHUD grid sizes (2×2, 3×3, 4×4) to fit flash budgets.
- Supports InkHUD2 mode for sparse per-tile selection across multiple zoom levels.
- Supports map element toggles, including land, water, roads, highways, paths, buildings, boundaries, labels, POI, and transit.
- Supports grayscale, mono, palette, and original output modes.
- Includes regular map overzoom and an alternate topo style for crisp closer inspection without raster blur.
- Shows flash usage bars, export estimates, progress, tile counts, and an export log.

The workflow is fully local and does not require a separate tile server.

## Use The App

Run the executable:

```powershell
.\dist\EinkMapTiles.exe
```

Basic flow:

1. Run `EinkMapTiles.exe`.
2. Pan and zoom the map preview.
3. Leave **Map Source** on **OpenFreeMap open vector tiles**.
4. Choose zoom levels and e-paper settings.
5. Click **Estimate** to check tile count.
6. Click **Export Tiles**.
7. Click **Open Folder** when export finishes.

The default source downloads OpenFreeMap vector tiles and renders the final PNG tiles locally. No map URL entry or extra setup is needed for normal use.

## Map Preview

The preview uses the same local renderer and e-paper conversion path as exports. What you see in the export preview is intended to match the downloaded tiles.

Map controls:

- Drag to pan.
- Mouse wheel zooms in or out around the current cursor location.
- `+` and `-` zoom around the map center.
- The center marker shows the current center latitude/longitude.
- **Refresh** redraws the export preview.

The visible map is the export area. The preview keeps the current map visible while a new export preview is rendering, then swaps in the updated render when it is ready.

The standard `osm-eink` map uses OpenFreeMap vector detail through zoom 14, then can preview/export deeper through zoom 16 by redrawing zoom-14 OpenFreeMap vectors into deeper child tiles. Labels, water, land shapes, roads, and trails stay crisp without raster blur. The `osm-eink-topo` style also adds deeper terrain data.

## Export Panel

The export panel shows:

- Estimated tile count.
- Current status.
- Export progress bar.
- Completed/exported tile log.
- Buttons for **Estimate**, **Export Tiles**, and **Open Folder**.
- **About / Licenses** for bundled license and attribution notes.

Large areas and high zoom ranges can create many tiles. Start with a small area and zoom range, then increase as needed.

## Area

The **Area** section controls the export bounding box.

You can either:

- Pan/zoom the map directly.
- Enter center latitude, center longitude, and radius in kilometers, then click **Fit Center Area**.
- Read the west, south, east, and north bounds from **Visible BBox**.

## Map Source

The default source is **OpenFreeMap open vector tiles**:

```text
https://tiles.openfreemap.org/planet/latest/{z}/{x}/{y}.pbf
```

The app downloads those vector tiles for the selected area and renders local e-paper PNG output.

The app includes a permission checkbox to make the attribution/legal step explicit. Keep the generated attribution files with exported tile bundles.

## Export Settings

Default desktop settings:

```text
min zoom: 4
max zoom: 8
mode: grayscale
style: osm-eink
brightness: 0.99
contrast: 1.15
mono threshold: 120
```

`Mono threshold` only affects `mono` mode. The desktop app hides that control for grayscale, palette, and original exports.

Output modes:

- `grayscale`: 8-bit grayscale PNGs tuned for detailed e-paper map viewing.
- `mono`: true 1-bit black/white PNGs for devices or tests that require binary output.
- `inkhud`: Bayer-dithered 1-bit processing that mirrors the InkHUD firmware pipeline. When selected, unchanged sliders default to brightness `1.03` and contrast `2.41`. Use **Export for InkHUD** to generate a `map_tile.h` firmware header.
- `inkhud2`: same pipeline as `inkhud`, but lets you click individual tiles on the map to build a sparse non-contiguous coverage area across multiple zoom levels.
- `palette`: indexed-color PNGs.
- `original`: rendered/source PNGs with no e-paper conversion.

Map styles:

- `osm-eink`: default clean e-paper map. It can export zooms 15-16 by clipping and redrawing zoom-14 OpenFreeMap vector data into deeper child tiles. This stays sharp, but it does not add new source detail beyond zoom 14.
- `osm-eink-topo`: alternate e-paper topo map with land, water, labels, trails/paths, hillshade, and contour lines from Mapzen Terrain Tiles on AWS Open Data. Regular roads, highways, buildings, boundaries, POI, and transit are disabled by default for this style, though boundaries can be enabled in **Map Elements**.

Zoom guidance:

- Use `osm-eink` for regular map exports up to zoom 16 when crisp generalized detail is acceptable.
- Use `osm-eink-topo` for terrain-focused topo exports up to zoom 16.
- At zooms above 14, the app keeps vector content sharp by clipping and redrawing zoom-14 OpenFreeMap vector data into the deeper child tiles. This avoids blurry scaling, but it does not add brand-new road/building/label detail beyond what exists at zoom 14.

## Map Elements

The app can include or exclude these map layers:

- Land
- Water
- Roads
- Highways
- Paths
- Buildings
- Boundaries
- Labels
- POI
- Transit

Buildings and POI are disabled by default to reduce visual clutter on e-paper. Labels, boundaries, water, land, roads, highways, paths, and transit are enabled by default.

Element choices affect both preview and exported OpenFreeMap tiles.

## Output

Exports are saved under:

```text
%USERPROFILE%\Downloads\EinkMapTiles\
```

Each export writes:

```text
tiles/{style}/{z}/{x}/{y}.png
manifest.json
ATTRIBUTION.txt
{export-name}.zip
```

Keep `manifest.json` and `ATTRIBUTION.txt` with any shared tile bundle.

The desktop app always writes normal tile bundles as:

```text
tiles/{style}/{z}/{x}/{y}.png
```

Use **Export for InkHUD** when you need a `map_tile.h` firmware header instead of a normal tile bundle. **Export for InkHUD** also applies the InkHUD brightness and contrast defaults when the sliders are still unchanged.

## InkHUD Firmware Export

**Export for InkHUD** generates a `map_tile.h` C header for direct inclusion in the Meshtastic firmware. Each 256×256 tile is stored as a raw LZ4 block using column-major byte layout (`[bx][y]` instead of row-major), which makes vertical map features (roads, building edges) contiguous in memory so LZ4 compresses them ~30% better.

Typical compression on dense urban areas: 128 KB per 4×4 zoom level uncompressed → 53–57 KB after column-major LZ4.

The header contains parallel arrays:

```c
map_tile_count      // number of tiles
map_tile_zooms[]    // zoom level per tile
map_tile_tx[]       // tile X index
map_tile_ty[]       // tile Y index
map_tile_sizes[]    // compressed byte count per tile
map_tile_data[]     // pointers to per-tile LZ4 byte arrays
```

The firmware decompresses tiles on demand into a 2-entry LRU cache. Pixel read from a decompressed tile: `tile[(px/8)*256 + py] & (1 << (px%8))`.

**Grid size** controls how many tiles are exported per zoom level:

| Grid | Tiles/zoom | Uncompressed | Typical LZ4 |
|------|-----------|-------------|-------------|
| 2×2  | 4         | 32 KB       | ~15 KB      |
| 3×3  | 9         | 72 KB       | ~32 KB      |
| 4×4  | 16        | 128 KB      | ~56 KB      |

nRF52840 has approximately 85 KB available for tile data. Combinations like z12 2×2 + z13 2×2 + z14 4×4 fit in ~81 KB.

**Coverage overlay**: enable the **Coverage** checkbox to see dashed per-zoom bounding boxes on the preview showing the exact tile footprint that will be exported.

**InkHUD2 mode** lets you click individual tiles to build a sparse, non-contiguous coverage area across multiple zoom levels, useful when you want specific areas at different zoom levels without a fixed grid.

## Legal Map Sources

A local executable does not make every map source legal. The source still has to allow offline export, bulk tile generation, and redistribution if you share the resulting tiles.

Good directions:

- Built-in OpenFreeMap vector tiles, used with required attribution.
- OpenFreeMap or OpenMapTiles data used according to their license and attribution terms.
- Protomaps PMTiles extracts used according to their license and attribution terms.
- A provider API only when the provider explicitly allows offline or bulk export.

Avoid:

- `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles.
- Scraping public raster tile servers.
- Assuming "free to view" means "free to bulk download."

This is a practical checklist, not legal advice.

## Attribution

Generated bundles include attribution guidance in `manifest.json` and `ATTRIBUTION.txt`.

Recommended baseline attribution for OSM-derived sources:

```text
(c) OpenStreetMap contributors
OpenStreetMap data is available under the Open Database License (ODbL) 1.0.
(c) OpenMapTiles, if using OpenMapTiles schema/data.
Terrain Tiles were accessed from https://registry.opendata.aws/terrain-tiles/, if using topo style.
Additional attribution may be required by the tile source or renderer.
```


