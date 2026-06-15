const MAX_MERCATOR_LAT = 85.05112878;
const ELEMENTS = ["land", "water", "roads", "highways", "paths", "buildings", "boundaries", "labels", "pois", "transit"];
const DEFAULT_ATTRIBUTION = {
  mapData: "\u00a9 OpenStreetMap contributors",
  mapDataLicense: "Open Database License (ODbL) 1.0",
  openMapTiles: "\u00a9 OpenMapTiles, if using OpenMapTiles schema/data",
  notes: "Verify and preserve attribution required by your tile source/provider.",
};

const elements = {
  west: document.getElementById("westInput"),
  south: document.getElementById("southInput"),
  east: document.getElementById("eastInput"),
  north: document.getElementById("northInput"),
  minZoom: document.getElementById("minZoomInput"),
  maxZoom: document.getElementById("maxZoomInput"),
  styleName: document.getElementById("styleInput"),
  mode: document.getElementById("modeInput"),
  preview: document.getElementById("previewInput"),
  contrast: document.getElementById("contrastInput"),
  contrastOutput: document.getElementById("contrastOutput"),
  brightness: document.getElementById("brightnessInput"),
  brightnessOutput: document.getElementById("brightnessOutput"),
  threshold: document.getElementById("thresholdInput"),
  thresholdOutput: document.getElementById("thresholdOutput"),
  vectorSource: document.getElementById("vectorSourceInput"),
  elementInputs: [...document.querySelectorAll(".element-input")],
  layout: document.getElementById("layoutInput"),
  url: document.getElementById("urlInput"),
  permission: document.getElementById("permissionInput"),
  tileCount: document.getElementById("tileCount"),
  command: document.getElementById("commandOutput"),
  status: document.getElementById("statusText"),
  useView: document.getElementById("useViewButton"),
  allElements: document.getElementById("allElementsButton"),
  copy: document.getElementById("copyButton"),
  job: document.getElementById("jobButton"),
  styleButton: document.getElementById("styleButton"),
  zip: document.getElementById("zipButton"),
};

const map = L.map("map", { zoomControl: true }).setView([39.5, -98.35], 4);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  className: "preview-tiles",
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

let areaLayer = null;
setInputsFromBounds(map.getBounds());
refresh();

map.on("moveend", () => {
  setInputsFromBounds(map.getBounds());
  refresh();
});

elements.useView.addEventListener("click", () => {
  setInputsFromBounds(map.getBounds());
  refresh();
});

for (const element of Object.values(elements)) {
  if (element instanceof HTMLInputElement || element instanceof HTMLSelectElement) {
    element.addEventListener("input", refresh);
  }
}

elements.copy.addEventListener("click", async () => {
  await navigator.clipboard.writeText(elements.command.value);
  setStatus("Command copied.");
});

elements.job.addEventListener("click", () => {
  downloadText("inkhud-tile-job.json", JSON.stringify(buildJob(), null, 2) + "\n", "application/json");
});

elements.styleButton.addEventListener("click", () => {
  const job = buildJob();
  downloadText(`${job.style}.json`, JSON.stringify(buildEinkStyle(job), null, 2) + "\n", "application/json");
});

elements.allElements.addEventListener("click", () => {
  const enableAll = elements.elementInputs.some((input) => !input.checked);
  for (const input of elements.elementInputs) input.checked = enableAll;
  refresh();
});

elements.zip.addEventListener("click", async () => {
  const job = buildJob();
  if (!job.urlTemplate) {
    setStatus("Add a tile URL template before downloading a ZIP.", true);
    return;
  }
  if (!elements.permission.checked) {
    setStatus("Confirm that this source allows offline or bulk tile export.", true);
    return;
  }
  const tiles = tilesForJob(job);
  if (tiles.length > 2500) {
    setStatus("This browser export is capped at 2500 tiles. Use the CLI for larger jobs.", true);
    return;
  }

  elements.zip.disabled = true;
  try {
    await downloadZip(job, tiles);
    setStatus("ZIP downloaded.");
  } catch (error) {
    setStatus(`ZIP failed: ${error.message}`, true);
  } finally {
    elements.zip.disabled = false;
  }
});

function refresh() {
  normalizeZooms();
  drawArea();
  const job = buildJob();
  const tiles = tilesForJob(job);
  elements.tileCount.value = `${tiles.length.toLocaleString()} tiles`;
  elements.command.value = buildCommand(job);
  elements.contrastOutput.value = Number(elements.contrast.value).toFixed(2);
  elements.brightnessOutput.value = Number(elements.brightness.value).toFixed(2);
  elements.thresholdOutput.value = String(Math.round(Number(elements.threshold.value)));
  updatePreview(job);
}

function setInputsFromBounds(bounds) {
  elements.west.value = round(bounds.getWest());
  elements.south.value = round(bounds.getSouth());
  elements.east.value = round(bounds.getEast());
  elements.north.value = round(bounds.getNorth());
}

function buildJob() {
  return {
    bbox: {
      west: Number(elements.west.value),
      south: Number(elements.south.value),
      east: Number(elements.east.value),
      north: Number(elements.north.value),
    },
    zooms: zoomRange(Number(elements.minZoom.value), Number(elements.maxZoom.value)),
    style: sanitizeStyle(elements.styleName.value),
    mode: elements.mode.value,
    brightness: Number(elements.brightness.value),
    contrast: Number(elements.contrast.value),
    threshold: Math.round(Number(elements.threshold.value)),
    elements: selectedElements(),
    vectorSource: elements.vectorSource.value.trim(),
    attribution: DEFAULT_ATTRIBUTION,
    layout: elements.layout.value,
    urlTemplate: elements.url.value.trim(),
  };
}

function buildCommand(job) {
  const bbox = `${job.bbox.west},${job.bbox.south},${job.bbox.east},${job.bbox.north}`;
  const zooms = compactZooms(job.zooms);
  const parts = [
    "eink-map-tiles",
    `--bbox=${quote(bbox)}`,
    "--zooms",
    quote(zooms),
    "--style",
    quote(job.style),
    "--mode",
    quote(job.mode),
    "--brightness",
    quote(job.brightness.toFixed(2)),
    "--contrast",
    quote(job.contrast.toFixed(2)),
    "--threshold",
    quote(job.threshold),
    "--include-elements",
    quote(job.elements.include.join(",")),
    "--layout",
    quote(job.layout),
  ];
  if (job.urlTemplate) {
    parts.push("--url-template", quote(job.urlTemplate), "--zip");
  } else {
    parts.push("--dry-run");
  }
  return parts.join(" ");
}

function drawArea() {
  const bbox = buildJob().bbox;
  const bounds = [
    [bbox.south, bbox.west],
    [bbox.north, bbox.east],
  ];
  if (!areaLayer) {
    areaLayer = L.rectangle(bounds, { color: "#146c5f", weight: 2, fillOpacity: 0.08 }).addTo(map);
  } else {
    areaLayer.setBounds(bounds);
  }
}

function normalizeZooms() {
  let minZoom = clamp(Number(elements.minZoom.value), 0, 20);
  let maxZoom = clamp(Number(elements.maxZoom.value), 0, 20);
  if (maxZoom < minZoom) maxZoom = minZoom;
  elements.minZoom.value = minZoom;
  elements.maxZoom.value = maxZoom;
}

function tilesForJob(job) {
  const tiles = [];
  for (const z of job.zooms) {
    const xRange = xRanges(job.bbox, z);
    const yNorth = lonLatToTile(job.bbox.west, job.bbox.north, z).y;
    const ySouth = lonLatToTile(job.bbox.west, job.bbox.south, z).y;
    for (const [xStart, xEnd] of xRange) {
      for (let x = xStart; x <= xEnd; x += 1) {
        for (let y = Math.min(yNorth, ySouth); y <= Math.max(yNorth, ySouth); y += 1) {
          tiles.push({ z, x, y });
        }
      }
    }
  }
  return uniqueTiles(tiles);
}

function xRanges(bbox, z) {
  const spans = bbox.west > bbox.east ? [[bbox.west, 180], [-180, bbox.east]] : [[bbox.west, bbox.east]];
  return spans.map(([west, east]) => {
    const left = lonLatToTile(west, bbox.north, z).x;
    const right = lonLatToTile(east, bbox.north, z).x;
    return [Math.min(left, right), Math.max(left, right)];
  });
}

function lonLatToTile(lon, lat, z) {
  const clippedLat = Math.max(Math.min(lat, MAX_MERCATOR_LAT), -MAX_MERCATOR_LAT);
  const n = 2 ** z;
  const latRad = (clippedLat * Math.PI) / 180;
  const x = Math.floor(((lon + 180) / 360) * n);
  const y = Math.floor(((1 - Math.asinh(Math.tan(latRad)) / Math.PI) / 2) * n);
  return {
    x: clamp(x, 0, n - 1),
    y: clamp(y, 0, n - 1),
  };
}

async function downloadZip(job, tiles) {
  const zip = new JSZip();
  zip.file("manifest.json", JSON.stringify({ ...job, tileCount: tiles.length, createdUtc: new Date().toISOString() }, null, 2));

  for (let index = 0; index < tiles.length; index += 1) {
    const tile = tiles[index];
    setStatus(`Fetching ${index + 1} of ${tiles.length}`);
    const url = job.urlTemplate.replace("{z}", tile.z).replace("{x}", tile.x).replace("{y}", tile.y);
    const blob = await fetchConvertedTile(url, job);
    zip.file(tilePath(job, tile), blob);
  }

  const zipBlob = await zip.generateAsync({ type: "blob" });
  downloadBlob(`${job.style}-inkhud-tiles.zip`, zipBlob);
}

async function fetchConvertedTile(url, job) {
  const response = await fetch(url, { mode: "cors" });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  const imageBlob = await response.blob();
  if (job.mode === "original") return imageBlob;

  const bitmap = await createImageBitmap(imageBlob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(bitmap, 0, 0);
  const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;

  for (let i = 0; i < data.length; i += 4) {
    const gray = data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114;
    const tuned = clamp(Math.round((gray - 128) * job.contrast + 128 * job.brightness), 0, 255);
    const value = job.mode === "mono" ? (tuned >= job.threshold ? 255 : 0) : tuned;
    data[i] = value;
    data[i + 1] = value;
    data[i + 2] = value;
    data[i + 3] = 255;
  }

  context.putImageData(imageData, 0, 0);
  return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
}

function selectedElements() {
  const include = elements.elementInputs.filter((input) => input.checked).map((input) => input.value);
  return {
    include,
    exclude: ELEMENTS.filter((name) => !include.includes(name)),
  };
}

function buildEinkStyle(job) {
  const sourceId = "openmaptiles";
  const sourceUrl = job.vectorSource || "mbtiles://openmaptiles";
  return {
    version: 8,
    name: job.style,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources: {
      [sourceId]: {
        type: "vector",
        url: sourceUrl,
      },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#f8f8f8" } },
      ...styleLayersForElements(sourceId, job.elements.include),
    ],
  };
}

function styleLayersForElements(sourceId, include) {
  const enabled = new Set(include);
  const layers = [];
  if (enabled.has("land")) {
    layers.push(
      {
        id: "landcover",
        type: "fill",
        source: sourceId,
        "source-layer": "landcover",
        paint: { "fill-color": "#eeeeee", "fill-opacity": 0.55 },
      },
      {
        id: "landuse",
        type: "fill",
        source: sourceId,
        "source-layer": "landuse",
        paint: { "fill-color": "#e6e6e6", "fill-opacity": 0.45 },
      },
    );
  }
  if (enabled.has("water")) {
    layers.push(
      {
        id: "water",
        type: "fill",
        source: sourceId,
        "source-layer": "water",
        paint: { "fill-color": "#ffffff" },
      },
      {
        id: "waterway",
        type: "line",
        source: sourceId,
        "source-layer": "waterway",
        paint: { "line-color": "#444444", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.4, 14, 1.1] },
      },
    );
  }
  if (enabled.has("buildings")) {
    layers.push({
      id: "building",
      type: "fill",
      source: sourceId,
      "source-layer": "building",
      paint: { "fill-color": "#d0d0d0", "fill-outline-color": "#777777" },
    });
  }
  if (enabled.has("boundaries")) {
    layers.push({
      id: "boundary",
      type: "line",
      source: sourceId,
      "source-layer": "boundary",
      paint: { "line-color": "#8c8c8c", "line-dasharray": [2, 2], "line-width": 0.8 },
    });
  }
  if (enabled.has("paths")) {
    layers.push({
      id: "paths",
      type: "line",
      source: sourceId,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["path", "track", "footway", "cycleway", "pedestrian"]]],
      paint: { "line-color": "#777777", "line-dasharray": [1, 1.5], "line-width": ["interpolate", ["linear"], ["zoom"], 10, 0.5, 16, 1.6] },
    });
  }
  if (enabled.has("roads")) {
    layers.push({
      id: "roads",
      type: "line",
      source: sourceId,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["minor", "service", "tertiary", "secondary"]]],
      paint: { "line-color": "#222222", "line-width": ["interpolate", ["linear"], ["zoom"], 6, 0.45, 16, 2.4] },
    });
  }
  if (enabled.has("highways")) {
    layers.push({
      id: "highways",
      type: "line",
      source: sourceId,
      "source-layer": "transportation",
      filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk", "primary"]]],
      paint: { "line-color": "#000000", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.8, 16, 3.3] },
    });
  }
  if (enabled.has("transit")) {
    layers.push({
      id: "rail",
      type: "line",
      source: sourceId,
      "source-layer": "transportation",
      filter: ["==", ["get", "class"], "rail"],
      paint: { "line-color": "#333333", "line-dasharray": [3, 2], "line-width": 1 },
    });
  }
  if (enabled.has("labels")) {
    layers.push(
      {
        id: "place-labels",
        type: "symbol",
        source: sourceId,
        "source-layer": "place",
        layout: { "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-size": ["interpolate", ["linear"], ["zoom"], 4, 10, 12, 16] },
        paint: { "text-color": "#000000", "text-halo-color": "#ffffff", "text-halo-width": 2 },
      },
      {
        id: "road-labels",
        type: "symbol",
        source: sourceId,
        "source-layer": "transportation_name",
        layout: { "symbol-placement": "line", "text-field": ["get", "name"], "text-size": 10 },
        paint: { "text-color": "#111111", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
      },
    );
  }
  if (enabled.has("pois")) {
    layers.push({
      id: "poi-labels",
      type: "symbol",
      source: sourceId,
      "source-layer": "poi",
      layout: { "text-field": ["coalesce", ["get", "name:en"], ["get", "name"]], "text-size": 9 },
      paint: { "text-color": "#222222", "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
    });
  }
  return layers;
}

function updatePreview(job) {
  const enabled = elements.preview.checked && job.mode !== "original";
  const root = document.documentElement;
  root.style.setProperty("--preview-brightness", job.brightness.toFixed(2));
  root.style.setProperty("--preview-contrast", job.contrast.toFixed(2));
  root.style.setProperty("--preview-threshold", String(job.threshold));
  const container = map.getContainer();
  container.classList.toggle("eink-preview", enabled);
  container.classList.toggle("mono-preview", enabled && job.mode === "mono");
}

function tilePath(job, tile) {
  const style = job.style;
  if (job.layout === "single-map") return `map/${tile.z}/${tile.x}/${tile.y}.png`;
  if (job.layout === "meshtastic-sd") return `maps/${style}/${tile.z}/${tile.x}/${tile.y}.png`;
  if (job.layout === "style-root") return `${style}/${tile.z}/${tile.x}/${tile.y}.png`;
  return `tiles/${style}/${tile.z}/${tile.x}/${tile.y}.png`;
}

function compactZooms(zooms) {
  if (zooms.length === 1) return String(zooms[0]);
  return `${zooms[0]}-${zooms[zooms.length - 1]}`;
}

function zoomRange(minZoom, maxZoom) {
  const zooms = [];
  for (let z = minZoom; z <= maxZoom; z += 1) zooms.push(z);
  return zooms;
}

function uniqueTiles(tiles) {
  const seen = new Set();
  return tiles.filter((tile) => {
    const key = `${tile.z}/${tile.x}/${tile.y}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function sanitizeStyle(value) {
  return (value || "osm-eink").replace(/[^a-zA-Z0-9._-]/g, "-");
}

function quote(value) {
  return `"${String(value).replaceAll('"', '\\"')}"`;
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(value, high));
}

function round(value) {
  return Number(value).toFixed(6);
}

function setStatus(message, warning = false) {
  elements.status.textContent = message;
  elements.status.classList.toggle("warning", warning);
}

function downloadText(filename, text, type) {
  downloadBlob(filename, new Blob([text], { type }));
}

function downloadBlob(filename, blob) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}
