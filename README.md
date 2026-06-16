# E-ink Map Tiles

Local-only Windows tool for generating e-paper-friendly offline map tiles for future InkHUD work in the Meshtastic firmware repo.

This project is focused on the tile asset pipeline, not firmware integration. It exports normal XYZ tile folders plus a manifest that future firmware code can consume or transform.

## Use The App

Run the executable:

```powershell
.\dist\EinkMapTiles.exe
```

The app is a native desktop window.

Basic flow:

1. Run `EinkMapTiles.exe`.
2. Pan/zoom the map preview.
3. Click **Use View** to make the visible map your export area.
4. Leave **Source preset** on **OpenFreeMap open vector tiles**.
5. Choose zoom levels and e-paper settings.
6. Click **Export Tiles**.

The default source downloads OpenFreeMap vector tiles for the selected area and renders e-paper PNG tiles locally. No separate map server or custom tile URL is needed.

During export, the app shows a progress bar, current tile count, and a log of completed tile paths.

The interactive preview is two-stage: it shows high-detail raster map tiles while the view is moving, then settles into an export preview rendered from the same OpenFreeMap vector source and e-paper conversion used by downloaded tiles.

Fast preview tiles are cached locally for at least 7 days under the user's local app data folder to respect OpenStreetMap public tile usage expectations.

Output is saved under:

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

## Rebuild The Exe

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows-exe.ps1
```

The built executable is:

```text
dist\EinkMapTiles.exe
```

The build script also copies `README.md`, `LICENSE`, and `NOTICE.md` into `dist\` for release packaging.

## Development

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
eink-map-tiles-app
```

The development command also opens the native desktop app.

## Legal Map Sources

A local executable does not make every map source legal. The source still has to allow offline export, bulk tile generation, and redistribution if you share the resulting tiles.

Good directions:

- Built-in OpenFreeMap vector tiles, which the app renders locally.
- OpenFreeMap or OpenMapTiles data used according to their license and attribution terms.
- Protomaps PMTiles extracts used according to their license and attribution terms.
- A provider API only when the provider explicitly allows offline or bulk export.

Avoid:

- `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles.
- Scraping public raster tile servers.
- Assuming "free to view" means "free to bulk download."

## CLI

The desktop app wraps the CLI. You can also run the CLI directly with the built-in OpenFreeMap source:

```powershell
eink-map-tiles --source openfreemap-vector --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-12 --mode grayscale --contrast 1.15 --brightness 0.99 --threshold 120 --zip
```

Preview tile count without downloading:

```powershell
eink-map-tiles --center-lat 47.6062 --center-lon -122.3321 --radius-km 10 --zooms 6-12 --dry-run
```

## Output Layouts

The default layout is `inkhud-dev`:

```text
tiles/{style}/{z}/{x}/{y}.png
```

Other layouts:

- `style-root`: `{style}/{z}/{x}/{y}.png`
- `single-map`: `map/{z}/{x}/{y}.png`
- `meshtastic-sd`: `maps/{style}/{z}/{x}/{y}.png`

## E-paper Modes

- `grayscale`: 8-bit grayscale PNGs for the high-detail e-paper preview/export path.
- `mono`: stark 1-bit black/white PNGs for devices or tests that require true black/white output.
- `palette`: indexed-color PNGs.
- `original`: source PNGs with no e-paper conversion.

Default desktop settings are tuned toward e-paper readability:

```text
mode: grayscale
brightness: 0.99
contrast: 1.15
threshold: 120
enabled elements: land, water, roads, highways, paths, boundaries, labels, transit
```

`Mono threshold` only affects `mono` mode. The desktop app hides that control for grayscale, palette, and original exports.

## Attribution

Generated bundles include attribution guidance in `manifest.json` and `ATTRIBUTION.txt`. Keep those files with exported tiles.

Recommended baseline attribution for OSM-derived sources:

```text
(c) OpenStreetMap contributors
OpenStreetMap data is available under the Open Database License (ODbL) 1.0.
(c) OpenMapTiles, if using OpenMapTiles schema/data.
Additional attribution may be required by the tile source or renderer.
```

This is a practical checklist, not legal advice.

## Test

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests
```
