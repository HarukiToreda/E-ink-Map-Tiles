# Changelog

## 1.0.0 - 2026-06-16

First stable local-only Windows release.

- Added a native desktop app for selecting an area, previewing e-paper map tiles, and exporting offline bundles.
- Uses OpenFreeMap vector tiles by default and renders PNG tiles locally; no browser site, GitHub Pages flow, or separate tile server is required.
- Preview now uses the same export renderer as downloaded OpenFreeMap tiles, so the visible map matches the generated output.
- Added cursor-anchored mouse-wheel zoom and pan interaction.
- Added collapsible app sections, compact controls, export progress, and output folder access.
- Added map element toggles with buildings and POI disabled by default.
- Tuned default e-paper settings: grayscale mode, brightness `0.99`, contrast `1.15`, mono threshold `120`.
- Hid the mono threshold control unless mono output mode is selected.
- Includes README, license, notices, manifest, and attribution files for release and exported bundles.
