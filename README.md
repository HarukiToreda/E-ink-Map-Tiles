# E-ink Map Tiles

Generate offline map tiles for future e-ink map rendering work, especially a later InkHUD applet in the Meshtastic firmware repo.

This repo is intentionally focused on the asset pipeline, not the firmware integration. It takes tiles from a legal tile source that you control or are allowed to bulk export, converts them into e-paper-friendly PNGs, writes a predictable folder structure, and records a manifest that future firmware code can consume or transform.

## Plan

1. Use open map data or packaged open vector tiles, not scraped public raster tiles.
2. Render tiles locally from that source, or use a provider that explicitly allows bulk/offline export.
3. Generate a small test bundle around one known location.
4. Tune e-paper readability using grayscale, mono, brightness, and contrast options.
5. Keep the output as normal XYZ tiles: `{z}/{x}/{y}.png`.
6. Store generated tiles under `tiles/{style}/z/x/y.png` with a `manifest.json`.
7. Later, in the firmware repo, add an InkHUD map applet that can load this manifest or the same tile path convention.
8. After the renderer exists, decide whether the firmware should consume PNGs directly, preprocessed 1-bit bitmaps, or a compact custom tile format.

## Legal Free Map Sources

Best default: use OSM-derived data that is packaged for download, then render your own local tiles.

Good free/legal paths:

- OpenFreeMap: open-source stack with weekly full-planet downloads in Btrfs and MBTiles formats. Self-hosting or local rendering is the cleanest path if you have the disk space.
- Protomaps Basemap PMTiles: free downloadable OSM-derived vector basemap, ODbL Produced Work, attribution required. Extract only your area and render locally.
- OpenMapTiles schema/tooling: open-source schema and styles for self-hosting from OSM and other open data. Attribution required.
- Raw OSM extracts: use Geofabrik or other OSM extract providers, then render yourself with a local tile stack. This is the most controlled path, but the heaviest.

Avoid using `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for offline bundles. OSM data is free, but the public OSM tile servers are not for bulk downloading or prefetching.

## Recommended Workflow

For the cleanest free workflow:

1. Get vector tiles legally, preferably from OpenFreeMap MBTiles or a Protomaps PMTiles regional extract.
2. Run a local raster renderer such as TileServer GL so it exposes PNG tiles on `localhost`.
3. Point this tool at that local endpoint with `--url-template`.
4. Convert the rendered tiles to grayscale or 1-bit e-paper PNGs.
5. Keep the generated ZIP and manifest with attribution notes.

Example local-renderer URL:

```powershell
eink-map-tiles --bbox="-122.55,47.45,-122.15,47.75" --zooms 6-13 --mode grayscale --url-template "http://127.0.0.1:8080/styles/eink/{z}/{x}/{y}.png" --zip
```

## Hosted Tile Packs

Yes, you can make testing easier by hosting prebuilt tiles from this repo, as long as the tiles were generated from a source that allows redistribution and you keep the required attribution.

Best use for this repo:

- Host small demo/test packs, not continent-scale or world-scale tiles.
- Generate them from self-hosted/open packaged data such as OpenFreeMap MBTiles, Protomaps PMTiles, OpenMapTiles tooling, or raw OSM extracts.
- Store them under `docs/tiles/{pack-name}/z/x/y.png`.
- Set the picker tile URL template to:

```text
https://harukitoreda.github.io/E-ink-Map-Tiles/tiles/{pack-name}/{z}/{x}/{y}.png
```

This makes browser ZIP downloads much easier because the tiles are same-origin with the GitHub Pages site.

Important limits:

- GitHub Pages published sites may be no larger than 1 GB.
- GitHub Pages has a soft bandwidth limit of 100 GB per month.
- Tile pyramids grow quickly, so keep hosted packs small and low/medium zoom.
- Do not create hosted packs by scraping public OpenStreetMap raster tiles.

If you need large areas, use object storage or a real tile server instead of committing the tiles to Git.

## Getting A Tile Source

The **Tile URL template** field needs an XYZ raster PNG endpoint. In plain English, that means a URL where changing `{z}`, `{x}`, and `{y}` returns one 256x256 map image.

Example shape:

```text
http://127.0.0.1:8080/styles/eink/{z}/{x}/{y}.png
```

Do not paste `https://tile.openstreetmap.org/{z}/{x}/{y}.png` for exports. That public service is for interactive viewing, not building offline tile bundles.

### Option A: Local TileServer GL

This is the most practical legal path for testing.

You need:

- Docker Desktop
- A legal `.mbtiles` file, such as one downloaded/generated from OpenFreeMap, OpenMapTiles, MapTiler data, or your own OSM extract pipeline

Put the `.mbtiles` file in a folder, for example:

```text
C:\maps\my-area.mbtiles
```

Run TileServer GL:

```powershell
cd C:\maps
docker run --rm -it -v ${PWD}:/data -p 8080:8080 maptiler/tileserver-gl:latest --file my-area.mbtiles
```

Open this in your browser to confirm it is running:

```text
http://127.0.0.1:8080
```

TileServer GL shows available styles and tile endpoints. Use the PNG raster endpoint it shows as the picker's **Tile URL template**. It will usually look similar to:

```text
http://127.0.0.1:8080/styles/basic/{z}/{x}/{y}.png
```

Then return to the picker, paste that URL, check the permission box, and click **Download Runner** or **Download ZIP**.

### Option B: Hosted Demo Tiles

For the easiest public testing, generate a small legal tile pack once and commit it under:

```text
docs/tiles/demo/z/x/y.png
```

Then use:

```text
https://harukitoreda.github.io/E-ink-Map-Tiles/tiles/demo/{z}/{x}/{y}.png
```

This avoids every tester needing Docker, but it only works for areas and zooms already included in the hosted pack.

### Option C: Provider Tile API

Some providers offer raster tile APIs and may allow offline export under specific plans or terms. If a provider explicitly allows your use case, paste their XYZ PNG URL into the picker. If their terms only allow live display, do not use them for offline bundles.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## GitHub Pages Picker

The static picker lives in `docs/` so this repo can publish it with GitHub Pages using the `docs` folder as the Pages source.

Live test site:

```text
https://harukitoreda.github.io/E-ink-Map-Tiles/
```

Use it to:

- Pan and zoom to an area.
- Estimate tile counts before downloading anything.
- Choose which vector map elements to include in the renderer style.
- Export a CLI command or `inkhud-tile-job.json`.
- Export a Windows runner script that installs/runs the generator for that selected area.
- Export an `osm-eink.json` MapLibre style for a local vector renderer.
- Optionally create a ZIP in the browser when your tile source supports CORS and explicitly permits offline export.

Easiest test path:

1. Open the live site.
2. Choose an area and click **Use View**.
3. Add a legal tile URL template, or leave it blank and the runner will ask later.
4. Click **Download Runner**.
5. Run `run-inkhud-tile-job.ps1` in PowerShell.

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

