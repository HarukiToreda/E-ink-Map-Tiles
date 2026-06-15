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

1. Run `EinkMapTiles.exe`.
2. Pan/zoom the map preview.
3. Click **Use View** to make the visible map your export area.
4. Leave **Source preset** on **OpenFreeMap open vector tiles**.
5. Choose zoom levels and e-paper settings.
6. Click **Export Tiles**.

The default source downloads OpenFreeMap vector tiles for the selected area and renders e-paper PNG tiles locally. No TileServer GL setup or custom tile URL is needed for the default path.

The interactive preview uses fast raster map tiles for display only, with attribution shown in the preview. It is softened into stepped grayscale so the area picker stays readable on a normal monitor while approximating an e-paper look. Exported tile bundles are generated from the selected export source.

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

- Built-in OpenFreeMap vector tiles, which the app renders locally.
- A local renderer backed by data you are allowed to use.
- OpenFreeMap or OpenMapTiles data used according to their license and attribution terms.
- Protomaps PMTiles extracts used according to their license and attribution terms.
- A provider API only when the provider explicitly allows offline or bulk export.

Avoid:

- `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles.
- Scraping public raster tile servers.
- Assuming "free to view" means "free to bulk download."

Advanced users can still switch to a local TileServer GL raster URL or a custom XYZ PNG URL.

## CLI

The desktop app wraps the CLI. You can also run the CLI directly with the built-in OpenFreeMap source:

```powershell
eink-map-tiles --source openfreemap-vector --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-12 --mode mono --contrast 1.4 --brightness 0.95 --threshold 201 --zip
```

Or use a custom XYZ raster source:

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
contrast: 1.30
brightness: 0.80
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
