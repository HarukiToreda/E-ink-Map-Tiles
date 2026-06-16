# Notices

E-ink Map Tiles is licensed under the MIT License. See `LICENSE`.

## Map Data And Tile Sources

Default exports use OpenFreeMap vector tiles and render PNG tiles locally. OpenFreeMap data comes from OpenStreetMap.

OpenStreetMap data is licensed under the Open Database License (ODbL) 1.0 and requires attribution when used publicly:

- `(c) OpenStreetMap contributors`
- https://www.openstreetmap.org/copyright
- https://opendatacommons.org/licenses/odbl/1-0/

OpenMapTiles-derived schema or data may require visible OpenMapTiles attribution:

- `(c) OpenMapTiles`
- https://openmaptiles.org/

The desktop preview uses the same local OpenFreeMap vector renderer as exported OpenFreeMap tiles. Do not use OpenStreetMap public raster tiles for offline export, bulk downloads, or tile archives.

Each exported bundle includes `manifest.json` and `ATTRIBUTION.txt`. Keep those files with exported tiles.

## Bundled Python Dependencies

The Windows executable is built with PyInstaller and bundles Python dependencies. Check the installed package metadata for exact versions in a given build. At the time this notice was added, the primary runtime dependencies were:

- Pillow: HPND-style Pillow license
- mapbox-vector-tile: MIT
- Shapely: BSD 3-Clause
- pyclipper: MIT
- protobuf: BSD 3-Clause
- NumPy: BSD-style NumPy license

This notice is a practical distribution aid, not legal advice.
