const MAX_MERCATOR_LAT = 85.05112878;

const elements = {
  west: document.getElementById("westInput"),
  south: document.getElementById("southInput"),
  east: document.getElementById("eastInput"),
  north: document.getElementById("northInput"),
  minZoom: document.getElementById("minZoomInput"),
  maxZoom: document.getElementById("maxZoomInput"),
  style: document.getElementById("styleInput"),
  mode: document.getElementById("modeInput"),
  layout: document.getElementById("layoutInput"),
  url: document.getElementById("urlInput"),
  permission: document.getElementById("permissionInput"),
  tileCount: document.getElementById("tileCount"),
  command: document.getElementById("commandOutput"),
  status: document.getElementById("statusText"),
  useView: document.getElementById("useViewButton"),
  copy: document.getElementById("copyButton"),
  job: document.getElementById("jobButton"),
  zip: document.getElementById("zipButton"),
};

const map = L.map("map", { zoomControl: true }).setView([39.5, -98.35], 4);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
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
    style: sanitizeStyle(elements.style.value),
    mode: elements.mode.value,
    layout: elements.layout.value,
    urlTemplate: elements.url.value.trim(),
  };
}

function buildCommand(job) {
  const bbox = `${job.bbox.west},${job.bbox.south},${job.bbox.east},${job.bbox.north}`;
  const zooms = compactZooms(job.zooms);
  const parts = [
    "eink-map-tiles",
    "--bbox",
    quote(bbox),
    "--zooms",
    quote(zooms),
    "--style",
    quote(job.style),
    "--mode",
    quote(job.mode),
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
    const blob = await fetchConvertedTile(url, job.mode);
    zip.file(tilePath(job, tile), blob);
  }

  const zipBlob = await zip.generateAsync({ type: "blob" });
  downloadBlob(`${job.style}-inkhud-tiles.zip`, zipBlob);
}

async function fetchConvertedTile(url, mode) {
  const response = await fetch(url, { mode: "cors" });
  if (!response.ok) throw new Error(`HTTP ${response.status} for ${url}`);
  const imageBlob = await response.blob();
  if (mode === "original") return imageBlob;

  const bitmap = await createImageBitmap(imageBlob);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(bitmap, 0, 0);
  const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
  const data = imageData.data;

  for (let i = 0; i < data.length; i += 4) {
    const gray = Math.round(data[i] * 0.299 + data[i + 1] * 0.587 + data[i + 2] * 0.114);
    const value = mode === "mono" ? (gray >= 150 ? 255 : 0) : gray;
    data[i] = value;
    data[i + 1] = value;
    data[i + 2] = value;
    data[i + 3] = 255;
  }

  context.putImageData(imageData, 0, 0);
  return await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
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
