# E-ink Map Tiles

Version 1.0.0

Local-only Windows tool for generating e-paper-friendly offline map tiles for future InkHUD work in the Meshtastic firmware repo.

This project is focused on the tile asset pipeline, not firmware integration. It exports normal XYZ tile folders, attribution files, a manifest, and a zip bundle that future firmware code can consume or transform.

## What It Does

- Runs as a native Windows desktop app.
- Lets you pan and zoom an interactive map preview.
- Lets you choose an export area from the current visible map.
- Downloads OpenFreeMap vector tiles for that selected area.
- Renders e-paper-ready PNG tiles locally.
- Exports a folder and zip bundle with `manifest.json` and `ATTRIBUTION.txt`.
- Supports map element toggles, including land, water, roads, highways, paths, buildings, boundaries, labels, POI, and transit.
- Supports grayscale, mono, palette, and original output modes.
- Includes an alternate topo style with high-zoom hillshade, contour lines, and clearer trail/path rendering.
- Shows export estimates, progress, tile counts, and an export log.

The workflow is fully local and does not require a separate tile server.

## Use The App

Run the executable:

```powershell
.\dist\EinkMapTiles.exe
```

Basic flow:

1. Run `EinkMapTiles.exe`.
2. Pan and zoom the map preview.
3. Click **Use View** to make the visible map your export area.
4. Leave **Source preset** on **OpenFreeMap open vector tiles**.
5. Choose zoom levels and e-paper settings.
6. Click **Estimate** to check tile count.
7. Click **Export Tiles**.
8. Click **Open Folder** when export finishes.

The default source downloads OpenFreeMap vector tiles and renders the final PNG tiles locally. No map URL entry or extra setup is needed for normal use.

## Map Preview

The preview uses the same local renderer and e-paper conversion path as exports. What you see in the export preview is intended to match the downloaded tiles.

Map controls:

- Drag to pan.
- Mouse wheel zooms in or out around the current cursor location.
- `+` and `-` zoom around the map center.
- **Use View** copies the visible map bounds into the export area.
- **Refresh** redraws the export preview.

The preview keeps the current map visible while a new export preview is rendering, then swaps in the updated render when it is ready.

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

- Pan/zoom the map and click **Use View**.
- Enter center latitude, center longitude, and radius in kilometers, then click **Set BBox From Center**.
- Manually edit west, south, east, and north bounds.

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
layout: inkhud-dev
style: osm-eink
brightness: 0.99
contrast: 1.15
mono threshold: 120
```

`Mono threshold` only affects `mono` mode. The desktop app hides that control for grayscale, palette, and original exports.

Output modes:

- `grayscale`: 8-bit grayscale PNGs tuned for detailed e-paper map viewing.
- `mono`: true 1-bit black/white PNGs for devices or tests that require binary output.
- `palette`: indexed-color PNGs.
- `original`: rendered/source PNGs with no e-paper conversion.

Map styles:

- `osm-eink`: default clean e-paper map.
- `osm-eink-topo`: alternate e-paper topo map. At high zooms, it overlays subtle hillshade and contour lines from Mapzen Terrain Tiles on AWS Open Data. Trails/paths are drawn more visibly in this style.

Output layouts:

- `inkhud-dev`: `tiles/{style}/{z}/{x}/{y}.png`
- `style-root`: `{style}/{z}/{x}/{y}.png`
- `single-map`: `map/{z}/{x}/{y}.png`
- `meshtastic-sd`: `maps/{style}/{z}/{x}/{y}.png`

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

## CLI

The desktop app wraps the CLI. You can also run the CLI directly with the built-in OpenFreeMap source:

```powershell
eink-map-tiles --source openfreemap-vector --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-12 --mode grayscale --contrast 1.15 --brightness 0.99 --threshold 120 --zip
```

Preview tile count without downloading:

```powershell
eink-map-tiles --center-lat 47.6062 --center-lon -122.3321 --radius-km 10 --zooms 6-12 --dry-run
```

Useful CLI options:

```text
--source openfreemap-vector
--bbox west,south,east,north
--center-lat LAT --center-lon LON --radius-km KM
--zooms 4-8
--mode grayscale|mono|palette|original
--brightness VALUE
--contrast VALUE
--threshold VALUE
--elements land,water,roads,highways,paths,boundaries,labels,transit
--layout inkhud-dev|style-root|single-map|meshtastic-sd
--output PATH
--zip
--dry-run
```

Topo export example:

```powershell
eink-map-tiles --source openfreemap-vector --style osm-eink-topo --bbox="-74.30,40.80,-73.80,41.10" --zooms 13-14 --mode grayscale --contrast 1.15 --brightness 0.99 --zip
```

## Rebuild The Exe

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-exe.ps1
```

The built executable is:

```text
dist\EinkMapTiles.exe
```

The build script also copies `README.md`, `LICENSE`, `NOTICE.md`, and `CHANGELOG.md` into `dist\` for release packaging.

## Release Package

The 1.0.0 Windows release package should include:

```text
EinkMapTiles.exe
README.md
LICENSE
NOTICE.md
CHANGELOG.md
```

Release zip naming:

```text
EinkMapTiles-1.0.0-windows-x64.zip
```

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
eink-map-tiles-app
```

Run tests:

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests
```
