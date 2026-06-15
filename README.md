# E-ink Map Tiles

Local-only Windows tool for generating e-paper-friendly offline map tiles for future InkHUD work in the Meshtastic firmware repo.

This project is focused on the tile asset pipeline, not firmware integration. It exports normal XYZ tile folders plus a manifest that future firmware code can consume or transform.

## Use The App

Run the executable:

```powershell
.\dist\EinkMapTiles.exe
```

The app is a native desktop window. It does not open a browser, does not use GitHub Pages, and does not download a runner script.

Basic flow:

1. Enter or calculate an area.
2. Choose zoom levels and e-paper settings.
3. Enter an XYZ PNG tile source you are allowed to export from.
4. Check the permission box.
5. Click **Export Tiles**.

Output is saved under:

```text
%USERPROFILE%\Downloads\EinkMapTiles\
```

Each export writes:

```text
tiles/{style}/{z}/{x}/{y}.png
manifest.json
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

- A local renderer backed by data you are allowed to use.
- OpenFreeMap or OpenMapTiles data used according to their license and attribution terms.
- Protomaps PMTiles extracts used according to their license and attribution terms.
- A provider API only when the provider explicitly allows offline or bulk export.

Avoid:

- `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles.
- Scraping public raster tile servers.
- Assuming "free to view" means "free to bulk download."

Current limitation: the desktop app still expects an XYZ PNG tile URL. The next major improvement should be direct PMTiles/MBTiles file selection so users can choose a downloaded legal map source without understanding tile URL templates.

## CLI

The desktop app wraps the CLI. You can also run the CLI directly:

```powershell
eink-map-tiles --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-12 --mode mono --contrast 1.4 --brightness 0.95 --threshold 201 --url-template "http://127.0.0.1:8080/styles/basic/{z}/{x}/{y}.png" --zip
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

- `mono`: 1-bit black/white PNGs for high-contrast e-paper testing.
- `grayscale`: 8-bit grayscale PNGs for softer detail.
- `palette`: indexed-color PNGs.
- `original`: source PNGs with no e-paper conversion.

Default desktop settings are tuned toward e-paper readability:

```text
mode: mono
contrast: 1.40
brightness: 0.95
threshold: 201
```

## Attribution

Generated bundles include attribution guidance in `manifest.json`. Keep that manifest with exported tiles.

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
