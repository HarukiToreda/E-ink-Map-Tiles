# E-ink Map Tiles

Generate offline map tiles for future e-ink map rendering work, especially a later InkHUD applet in the Meshtastic firmware repo.

This repo is intentionally focused on the asset pipeline, not the firmware integration. It takes tiles from a legal tile source that you control or are allowed to bulk export, converts them into e-paper-friendly PNGs, writes a predictable folder structure, and records a manifest that future firmware code can consume or transform.

## Direction: Local App First

The GitHub Pages picker was useful for proving the idea, but it is not the right main workflow. The better product is a local app/exe:

1. Open one local map picker.
2. Select an area.
3. Choose an allowed map source.
4. Click export.
5. Get a ready-to-copy ZIP/folder of e-paper tiles.

A local app does not make an arbitrary map source legal by itself. The legal win is that the app can work from sources that are meant to be downloaded or self-hosted, such as PMTiles/MBTiles archives or a tile server you control. It also avoids the confusing hosted-site flow where a web page downloads a PowerShell script that then asks for another tile URL.

The current CLI remains useful as the export engine. The next implementation should wrap it in a local UI instead of making users assemble the pieces manually.

## Legal Free Map Sources

Best default: use OSM-derived data that is packaged for download, then render your own local tiles.

Good free/legal paths:

- OpenFreeMap: open-source stack with weekly full-planet downloads in Btrfs and MBTiles formats. Self-hosting or local rendering is the cleanest path if you have the disk space.
- Protomaps Basemap PMTiles: free downloadable OSM-derived vector basemap, ODbL Produced Work, attribution required. Extract only your area and render locally.
- OpenMapTiles schema/tooling: open-source schema and styles for self-hosting from OSM and other open data. Attribution required.
- Raw OSM extracts: use Geofabrik or other OSM extract providers, then render yourself with a local tile stack. This is the most controlled path, but the heaviest.

Avoid using `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles. OSM data is free, but the public OSM tile servers are not for bulk downloading or prefetching.

## New Recommended Workflow

The simplest legal user experience should be:

1. Run `EinkMapTiles.exe`.
2. Pick an area on the map.
3. Choose one of these source options:
   - **Local PMTiles/MBTiles file**: safest free path once the file is downloaded.
   - **Local tile server**: good for advanced users who already run TileServer GL, Martin, or another renderer.
   - **Provider URL**: only when that provider explicitly permits offline/bulk export.
4. Pick zooms and e-paper settings.
5. Click **Export Tiles**.

The app should write:

```text
build/inkhud-tiles/
  tiles/{style}/{z}/{x}/{y}.png
  manifest.json
  inkhud-tiles.zip
```

## Map Source Rules

Use sources that are designed for download, self-hosting, or offline export.

Good source directions:

- Protomaps PMTiles: downloadable OSM-derived vector basemap. Regional extracts can be created with the `pmtiles` CLI. Attribution required.
- OpenFreeMap downloads: open-source stack with weekly full-planet downloads in Btrfs and MBTiles formats. Attribution required.
- OpenMapTiles tooling/data: useful when self-hosting or building your own tiles from OSM data. Attribution required.
- Your own tile server: legal when you control the data source and its license allows the export.
- A paid/free provider API: legal only if the provider's terms explicitly allow offline export or bulk tile generation.

Avoid:

- Downloading from `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles.
- Building hosted packs by scraping public raster tile servers.
- Assuming "free to view" means "free to bulk download and redistribute."

## Local App Implementation Plan

Build the next version around a local executable:

1. Keep `eink-map-tiles` as the command-line export engine.
2. Add `eink-map-tiles-app`, a local web UI served from `127.0.0.1`.
3. The local UI should call a local export API instead of downloading a runner script.
4. First source support: local/self-hosted XYZ PNG URL, because the current CLI already supports it.
5. Next source support: local PMTiles/MBTiles file with a bundled/local renderer, so users do not need to understand tile URL templates.
6. Keep GitHub Pages only as documentation or a non-exporting demo.

This gives users a normal desktop-app flow while preserving the legal line: the app exports from an allowed source, not from public viewing-only tiles.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## Run The Local App

```powershell
eink-map-tiles-app
```

This opens:

```text
http://127.0.0.1:8765/
```

Use the map picker, enter a legal tile source, confirm permission, then click **Export Locally**. The app saves output under:

```text
%USERPROFILE%\Downloads\EinkMapTiles\
```

Current local-app limitation: it still expects an XYZ PNG tile URL. That should be treated as a stepping stone. The next major source upgrade should let users choose a local PMTiles/MBTiles file so they do not need to understand tile URL templates.

## GitHub Pages Picker

The static picker lives in `docs/` so this repo can publish a demo with GitHub Pages, but GitHub Pages is no longer the recommended export workflow.

Live test site:

```text
https://harukitoreda.github.io/E-ink-Map-Tiles/
```

Use it to:

- Pan and zoom to an area.
- Estimate tile counts before downloading anything.
- Choose which vector map elements to include in the renderer style.
- Export a CLI command or `inkhud-tile-job.json`.
- Export an `osm-eink.json` MapLibre style for a local vector renderer.
- Try browser ZIP export only when your tile source supports CORS and explicitly permits offline export.

Recommended export path:

1. Run `eink-map-tiles-app`.
2. Choose an area and click **Use View**.
3. Add a legal tile URL template.
4. Confirm permission.
5. Click **Export Locally**.

Run an exported job with:

```powershell
eink-map-tiles --job .\inkhud-tile-job.json --zip
```

### Publish It

Yes, this can be hosted with GitHub Pages for others to test.

Repository setup:

1. Push this repo to GitHub.
2. Open the repository's **Settings**.
3. Go to **Pages**.
4. Set **Source** to **Deploy from a branch**.
5. Set the branch to `main` and the folder to `/docs`.
6. Save, then wait for GitHub to publish the site.

What works from GitHub Pages:

- Area selection on the preview map.
- E-paper contrast, brightness, threshold preview.
- Tile count estimates.
- Job JSON download.
- MapLibre style JSON download.
- CLI command generation.

What needs extra setup:

- Browser ZIP downloads require a tile source that allows offline/bulk export and sends CORS headers.
- A `localhost` tile renderer may work for a tester running a local renderer, but that renderer must allow browser requests from the GitHub Pages origin.
- GitHub Pages cannot run the Python CLI for visitors. For larger or more reliable exports, testers should download the job JSON and run `eink-map-tiles --job .\inkhud-tile-job.json --zip` locally.

The preview map uses public OpenStreetMap raster tiles only for interactive area selection with visible attribution. Do not use the public OSM tile server as the export/download source.

## Examples

Preview the tile count for a 10 km radius around Seattle:

```powershell
eink-map-tiles --center-lat 47.6062 --center-lon -122.3321 --radius-km 10 --zooms 6-12 --dry-run
```

Download an e-ink grayscale bundle and create a ZIP:

```powershell
eink-map-tiles --center-lat 47.6062 --center-lon -122.3321 --radius-km 10 --zooms 6-12 --style osm --url-template "http://127.0.0.1:8080/{z}/{x}/{y}.png" --zip
```

Create a 1-bit black/white test bundle:

```powershell
eink-map-tiles --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-13 --mode mono --contrast 1.4 --url-template "http://127.0.0.1:8080/{z}/{x}/{y}.png" --zip
```

Use a different XYZ tile server:

```powershell
eink-map-tiles --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-13 --style my-style --url-template "https://example.com/tiles/{z}/{x}/{y}.png" --zip
```

The default output folder is `build/inkhud-tiles`. The ZIP contains:

```text
tiles/
  osm/
    6/
      10/
        22.png
manifest.json
```

## Layout Options

The default layout is `--layout inkhud-dev`, which writes `tiles/{style}/z/x/y.png`.

Other layouts are available for experiments:

- `--layout style-root` writes `{style}/z/x/y.png`.
- `--layout single-map` writes `map/z/x/y.png`.
- `--layout meshtastic-sd` writes `maps/{style}/z/x/y.png`.

## E-paper Modes

- `--mode mono` writes 1-bit black/white PNGs for memory and contrast testing. The picker defaults here because it looks closest to many e-paper panels.
- `--mode grayscale` writes 8-bit grayscale PNGs when you want softer map detail.
- `--mode palette --colors 256` writes indexed-color PNGs.
- `--brightness` and `--contrast` tune readability before conversion.
- `--threshold` controls the black/white cutoff for mono exports.

## Map Elements

The picker can include or exclude broad vector-renderer categories: land, water, roads, highways, paths, buildings, boundaries, labels, POI, and transit.

These choices are written to the job and manifest, and the picker can download a simple MapLibre style JSON using those choices. They should be applied before raster tile export by your local vector renderer; already-rendered PNG tiles cannot reliably have individual map elements removed afterward.

## Provider Notes

This tool intentionally has no default online tile URL. For downloads, pass `--url-template` for a local tile renderer, your own tile server, or a provider that explicitly allows the kind of offline bundle you are generating.

## Compliance Notes

This is a practical checklist, not legal advice.

Current repo status:

- Leaflet is used by the GitHub Pages picker from a CDN. Leaflet is BSD 2-Clause licensed. The local CSS includes a small Leaflet-compatible layout fallback, so keep Leaflet's license/copyright notice in downstream distributions.
- JSZip is used by the picker from a CDN for browser ZIP creation. JSZip is dual licensed; this project uses it under the MIT license option.
- Pillow is the Python image-processing dependency. Pillow is MIT-CMU licensed.
- OpenStreetMap public raster tiles are used only for the interactive preview map the user is actively viewing, with visible `(c) OpenStreetMap contributors` attribution. Do not use `tile.openstreetmap.org` as a download source for bundles.
- Generated bundles require a tile URL you provide. Use a local renderer, your own tile server, or a provider that explicitly allows offline/bulk export.
- OpenFreeMap, OpenMapTiles, Protomaps, and raw OSM extracts are valid directions only when you follow their attribution/license terms. Most OSM-derived outputs require `(c) OpenStreetMap contributors` and ODbL notice; OpenMapTiles-derived outputs also require OpenMapTiles attribution.

Recommended attribution to keep with generated tile bundles:

```text
(c) OpenStreetMap contributors
OpenStreetMap data is available under the Open Database License (ODbL) 1.0.
(c) OpenMapTiles, if using OpenMapTiles schema/data.
Additional attribution may be required by the tile source or renderer.
```

The CLI and browser picker now write attribution guidance into generated job files and manifests. If you publish or redistribute generated tile bundles, keep those manifest files with the tiles and add visible attribution wherever the map is displayed.

## Test

```powershell
$env:PYTHONPATH='src'
python -m unittest discover -s tests
```

