import { VectorTile, type VectorTileFeature } from "@mapbox/vector-tile";
import { PbfReader } from "pbf";
import type { ProjectSession } from "../models";
import { isJsonObject } from "./geojson";
import { drawProjectMarkers } from "./markerDrawing";
import { sourceMaxZoom } from "./mapConfig";
import { lonLatToWorld, TILE_SIZE } from "./mercator";
import { tileBounds, type TileCoordinate } from "./tiles";

const SIZE = TILE_SIZE;
const SOURCE_CACHE_LIMIT = 32,
  RENDER_CACHE_LIMIT = 64;
type PreparedLayer = VectorTileFeature[];
type PreparedVectorTile = { layers: Record<string, PreparedLayer | undefined> };
const sourceTileCache = new Map<string, Promise<PreparedVectorTile>>();
const renderedTileCache = new Map<string, Promise<HTMLCanvasElement>>();
const geometryCache = new WeakMap<
  VectorTileFeature,
  ReturnType<VectorTileFeature["loadGeometry"]>
>();
const usedLayers = [
  "landcover",
  "landuse",
  "park",
  "water",
  "waterway",
  "building",
  "boundary",
  "transportation",
  "place",
  "water_name",
  "poi",
  "transportation_name",
];
const COLORS = {
  background: "#f8f4f0",
  park: "#d8e8c8",
  landcover: "#b0d59a",
  landuse: "#eadfc8",
  water: "#9ebdff",
  building: "#ddd9d4",
  buildingOutline: "#cbc5bf",
  boundary: "#686768",
  roadCasing: "#e9ac77",
  motorway: "#ffcc88",
  majorRoad: "#ffeeaa",
  minorRoad: "#ffffff",
  minorRoadCasing: "#cfcdca",
  rail: "#bbbbbb",
  path: "#9b8d7c",
} as const;

const EINK_COLORS = {
  background: COLORS.background,
  park: COLORS.park,
  landcover: COLORS.landcover,
  landuse: COLORS.landuse,
  water: COLORS.water,
  building: COLORS.building,
  buildingOutline: COLORS.buildingOutline,
  boundary: COLORS.boundary,
  roadCasing: "#555555",
  motorway: "#f8f8f8",
  majorRoad: "#f8f8f8",
  minorRoad: "#ffffff",
  minorRoadCasing: "#777777",
  rail: "#555555",
  path: "#777777",
} as const;

const LABEL_PRIORITY: Readonly<Record<string, number>> = {
  country: 0,
  state: 10,
  city: 20,
  town: 30,
  village: 40,
  motorway: 0,
  trunk: 5,
  primary: 10,
  secondary: 20,
  tertiary: 30,
  minor: 40,
  service: 50,
};

type VectorView = { scale: number; offsetX: number; offsetY: number };
const IDENTITY_VIEW: VectorView = { scale: 1, offsetX: 0, offsetY: 0 };
function viewPoint(x: number, y: number, view: VectorView) {
  return { x: x * view.scale - view.offsetX, y: y * view.scale - view.offsetY };
}

function closestPointOnSegment(
  point: { x: number; y: number },
  start: { x: number; y: number },
  end: { x: number; y: number },
) {
  const dx = end.x - start.x,
    dy = end.y - start.y,
    lengthSquared = dx * dx + dy * dy;
  const amount = lengthSquared
    ? Math.max(
        0,
        Math.min(1, ((point.x - start.x) * dx + (point.y - start.y) * dy) / lengthSquared),
      )
    : 0;
  return { x: start.x + amount * dx, y: start.y + amount * dy };
}

function touchLru<K, V>(cache: Map<K, V>, key: K, value: V, limit: number) {
  cache.delete(key);
  cache.set(key, value);
  while (cache.size > limit) {
    const oldestKey = cache.keys().next().value;
    if (oldestKey === undefined) break;
    cache.delete(oldestKey);
  }
}

async function preparedVectorTile(url: string): Promise<PreparedVectorTile> {
  const existing = sourceTileCache.get(url);
  if (existing) {
    touchLru(sourceTileCache, url, existing, SOURCE_CACHE_LIMIT);
    return existing;
  }
  const pending = (async () => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`OpenFreeMap tile request failed (${response.status})`);
    const vector = new VectorTile(new PbfReader(new Uint8Array(await response.arrayBuffer())));
    const layers: PreparedVectorTile["layers"] = {};
    for (const name of usedLayers) {
      const layer = vector.layers[name];
      if (!layer) continue;
      const features: VectorTileFeature[] = [];
      for (let index = 0; index < layer.length; index++) {
        const feature = layer.feature(index);
        features.push(feature);
        geometryCache.set(feature, feature.loadGeometry());
      }
      layers[name] = features;
    }
    return { layers };
  })();
  touchLru(sourceTileCache, url, pending, SOURCE_CACHE_LIMIT);
  pending.catch(() => sourceTileCache.get(url) === pending && sourceTileCache.delete(url));
  return pending;
}

function featureGeometry(
  feature: VectorTileFeature,
): ReturnType<VectorTileFeature["loadGeometry"]> {
  const existing = geometryCache.get(feature);
  if (existing) return existing;
  const geometry = feature.loadGeometry();
  geometryCache.set(feature, geometry);
  return geometry;
}

function eachFeature(
  layer: PreparedLayer | undefined,
  callback: (feature: VectorTileFeature) => void,
) {
  if (!layer) return;
  for (const feature of layer) callback(feature);
}

function trace(
  context: CanvasRenderingContext2D,
  feature: VectorTileFeature,
  close: boolean,
  view: VectorView,
) {
  const scale = SIZE / feature.extent;
  context.beginPath();
  for (const line of featureGeometry(feature)) {
    if (!line.length) continue;
    const first = viewPoint(line[0].x * scale, line[0].y * scale, view);
    context.moveTo(first.x, first.y);
    for (let index = 1; index < line.length; index++) {
      const point = viewPoint(line[index].x * scale, line[index].y * scale, view);
      context.lineTo(point.x, point.y);
    }
    if (close) context.closePath();
  }
}

function polygons(
  context: CanvasRenderingContext2D,
  layer: PreparedLayer | undefined,
  fill: string,
  stroke: string | undefined,
  view: VectorView,
) {
  eachFeature(layer, (feature) => {
    if (feature.type !== 3) return;
    trace(context, feature, true, view);
    context.fillStyle = fill;
    context.fill("evenodd");
    if (stroke) {
      context.strokeStyle = stroke;
      context.lineWidth = 1;
      context.stroke();
    }
  });
}

function lines(
  context: CanvasRenderingContext2D,
  layer: PreparedLayer | undefined,
  color: string,
  width: number,
  view: VectorView,
  filter?: (feature: VectorTileFeature) => boolean,
  dash: number[] = [],
) {
  eachFeature(layer, (feature) => {
    if (feature.type !== 2 || (filter && !filter(feature))) return;
    trace(context, feature, false, view);
    context.strokeStyle = color;
    context.lineWidth = width;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.setLineDash(dash);
    context.stroke();
  });
  context.setLineDash([]);
}

function transportation(
  context: CanvasRenderingContext2D,
  layer: PreparedLayer | undefined,
  zoom: number,
  enabled: Set<string>,
  eink: boolean,
  view: VectorView,
) {
  if (!layer || zoom <= 5) return;
  const palette = eink ? EINK_COLORS : COLORS;
  const groups: Array<{
    classes: Set<string>;
    element: string;
    casing: string;
    fill?: string;
    outer: number;
    inner?: number;
    dash?: number[];
  }> = [
    {
      classes: new Set(["motorway", "trunk"]),
      element: "highways",
      casing: palette.roadCasing,
      fill: palette.motorway,
      outer: zoom < 12 ? 1 : 5,
      inner: zoom < 12 ? 0 : 3,
    },
    {
      classes: new Set(["primary"]),
      element: "highways",
      casing: palette.roadCasing,
      fill: palette.majorRoad,
      outer: zoom < 12 ? 1 : 4,
      inner: zoom < 12 ? 0 : 2,
    },
    {
      classes: new Set(["secondary", "tertiary"]),
      element: "roads",
      casing: palette.roadCasing,
      fill: palette.majorRoad,
      outer: 3,
      inner: 1,
    },
    {
      classes: new Set(["minor", "service"]),
      element: "roads",
      casing: palette.minorRoadCasing,
      fill: palette.minorRoad,
      outer: 2,
      inner: 1,
    },
    {
      classes: new Set(["track", "path", "footway", "cycleway", "bridleway", "steps"]),
      element: "paths",
      casing: palette.path,
      outer: 1,
      dash: [1, 5],
    },
    {
      classes: new Set(["rail"]),
      element: "transit",
      casing: palette.rail,
      fill: palette.background,
      outer: 2,
      inner: 1,
    },
  ];
  for (const group of groups) {
    if (!enabled.has(group.element)) continue;
    const filter = (feature: VectorTileFeature) =>
      group.classes.has(String(feature.properties.class ?? ""));
    lines(context, layer, group.casing, group.outer, view, filter, group.dash);
    if (group.fill && group.inner)
      lines(context, layer, group.fill, group.inner, view, filter, group.dash);
  }
}

type LabelKind = "place" | "water" | "poi" | "road";

function labels(
  context: CanvasRenderingContext2D,
  layer: PreparedLayer | undefined,
  zoom: number,
  placed: Array<[number, number, number, number]>,
  kind: LabelKind,
  view: VectorView,
) {
  const minimum = kind === "place" ? 4 : kind === "water" ? 6 : kind === "road" ? 16 : 13;
  if (!layer || zoom < minimum) return;
  const candidates: Array<{ name: string; x: number; y: number; rank: number }> = [],
    seen = new Set<string>();
  eachFeature(layer, (feature) => {
    const labelClass = String(feature.properties.class ?? "");
    if (kind === "place") {
      const allowed =
        zoom <= 4
          ? new Set(["country"])
          : zoom === 5
            ? new Set(["country", "state", "city"])
            : zoom <= 7
              ? new Set(["country", "state", "city", "town"])
              : zoom <= 10
                ? new Set(["country", "state", "city", "town", "village"])
                : null;
      if (allowed && !allowed.has(labelClass)) return;
    }
    if (kind === "road") {
      const roadClass = String(feature.properties.class ?? feature.properties.subclass ?? "");
      const major = new Set(["motorway", "trunk", "primary", "secondary", "tertiary"]);
      if (zoom === 16 && !major.has(roadClass)) return;
    }
    const geometry = featureGeometry(feature),
      line = geometry.reduce(
        (longest, candidate) => (candidate.length > longest.length ? candidate : longest),
        geometry[0] ?? [],
      );
    const name = String(
      feature.properties.name_en ?? feature.properties.name ?? feature.properties.ref ?? "",
    ).trim();
    if (!line.length || !name || seen.has(name)) return;
    const tileScale = SIZE / feature.extent;
    const projectedLines = geometry.map((part) =>
      part.map((point) => viewPoint(point.x * tileScale, point.y * tileScale, view)),
    );
    const projectedLine = projectedLines.reduce(
      (longest, candidate) => (candidate.length > longest.length ? candidate : longest),
      projectedLines[0] ?? [],
    );
    let projected = projectedLine[Math.floor(projectedLine.length / 2)];
    if (kind === "road" && view.scale > 1) {
      const center = { x: SIZE / 2, y: SIZE / 2 };
      const candidates = projectedLines.flatMap((part) =>
        part.filter(
          (point) =>
            point.x >= -32 && point.x <= SIZE + 32 && point.y >= -16 && point.y <= SIZE + 16,
        ),
      );
      for (const part of projectedLines)
        for (let index = 1; index < part.length; index++) {
          const point = closestPointOnSegment(center, part[index - 1], part[index]);
          if (point.x >= -32 && point.x <= SIZE + 32 && point.y >= -16 && point.y <= SIZE + 16)
            candidates.push(point);
        }
      if (candidates.length)
        projected = candidates.reduce((closest, point) =>
          Math.hypot(point.x - center.x, point.y - center.y) <
          Math.hypot(closest.x - center.x, closest.y - center.y)
            ? point
            : closest,
        );
    }
    if (
      projected.x < -64 ||
      projected.x > SIZE + 64 ||
      projected.y < -32 ||
      projected.y > SIZE + 32
    )
      return;
    seen.add(name);
    const classPriority = LABEL_PRIORITY[labelClass] ?? 60;
    candidates.push({
      name,
      x: projected.x,
      y: projected.y,
      rank: classPriority + Number(feature.properties.rank ?? 99),
    });
  });
  const density =
    kind === "road"
      ? zoom >= 18
        ? 200
        : 48
      : zoom <= 4
        ? 5
        : zoom <= 6
          ? 9
          : zoom <= 8
            ? 14
            : zoom <= 10
              ? 20
              : zoom <= 12
                ? 28
                : 40;
  const fontSize =
    kind === "road" ? (zoom >= 18 ? 9 : 10) : 11 + (zoom >= 12 ? 1 : 0) + (zoom >= 14 ? 1 : 0);
  const collisionGap = kind === "road" && zoom >= 18 ? 1 : 3;
  context.font = `500 ${fontSize}px Arial, "Segoe UI", "DejaVu Sans", sans-serif`;
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.lineJoin = "round";
  for (const item of candidates.sort((a, b) => a.rank - b.rank).slice(0, density)) {
    const name =
      item.name.length > 28 ? `${item.name.slice(0, 27).replace(/\s+\S*$/, "")}…` : item.name;
    const metrics = context.measureText(name),
      width = metrics.width,
      height = fontSize + 4;
    const box: [number, number, number, number] = [
      item.x - width / 2 - 2,
      item.y - height / 2,
      item.x + width / 2 + 2,
      item.y + height / 2,
    ];
    if (
      box[0] < 1 ||
      box[2] > 255 ||
      box[1] < 1 ||
      box[3] > 255 ||
      placed.some(
        (old) =>
          !(
            box[2] + collisionGap < old[0] ||
            box[0] - collisionGap > old[2] ||
            box[3] + collisionGap < old[1] ||
            box[1] - collisionGap > old[3]
          ),
      )
    )
      continue;
    context.lineWidth = kind === "road" && zoom >= 18 ? 3 : 4;
    context.strokeStyle = "#ffffff";
    context.strokeText(name, item.x, item.y);
    context.fillStyle = "#111111";
    context.fillText(name, item.x, item.y);
    placed.push(box);
  }
}

async function imageFrom(url: string): Promise<ImageBitmap> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Map tile request failed (${response.status})`);
  return createImageBitmap(await response.blob());
}

async function drawTerrain(context: CanvasRenderingContext2D, tile: TileCoordinate) {
  if (tile.z < 4) return;
  try {
    const image = await imageFrom(
      `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${tile.z}/${tile.x}/${tile.y}.png`,
    );
    const terrain = document.createElement("canvas");
    terrain.width = terrain.height = SIZE;
    const terrainContext = terrain.getContext("2d", { willReadFrequently: true });
    if (!terrainContext) return;
    terrainContext.drawImage(image, 0, 0, SIZE, SIZE);
    image.close();
    const raw = terrainContext.getImageData(0, 0, SIZE, SIZE).data,
      elevation = new Float32Array(SIZE * SIZE);
    for (let index = 0; index < elevation.length; index++) {
      const offset = index * 4;
      elevation[index] = raw[offset] * 256 + raw[offset + 1] + raw[offset + 2] / 256 - 32768;
    }
    const base = context.getImageData(0, 0, SIZE, SIZE);
    for (let y = 1; y < SIZE - 1; y++)
      for (let x = 1; x < SIZE - 1; x++) {
        const eastWest = elevation[y * SIZE + x + 1] - elevation[y * SIZE + x - 1];
        const northSouth = elevation[(y + 1) * SIZE + x] - elevation[(y - 1) * SIZE + x];
        const relief = Math.max(-42, Math.min(42, (eastWest + northSouth) * 0.42));
        const slope = Math.min(26, (Math.abs(eastWest) + Math.abs(northSouth)) * 0.09);
        const shade = Math.max(168, Math.min(244, 222 + relief - slope)),
          offset = (y * SIZE + x) * 4;
        base.data[offset] = Math.round(base.data[offset] * 0.72 + shade * 0.28);
        base.data[offset + 1] = Math.round(base.data[offset + 1] * 0.72 + shade * 0.28);
        base.data[offset + 2] = Math.round(base.data[offset + 2] * 0.72 + shade * 0.28);
      }
    context.putImageData(base, 0, 0);
  } catch {
    // Terrain is an optional enhancement; keep the vector base if it is unavailable.
  }
}

function lonLatPoint(lon: number, lat: number, tile: TileCoordinate) {
  const point = lonLatToWorld(lon, lat, tile.z);
  return { x: point.x - tile.x * SIZE, y: point.y - tile.y * SIZE };
}

function drawGeoJson(context: CanvasRenderingContext2D, value: unknown, tile: TileCoordinate) {
  if (!isJsonObject(value)) return;
  const object = value;
  if (object.type === "FeatureCollection" && Array.isArray(object.features)) {
    object.features.forEach((item) => drawGeoJson(context, item, tile));
    return;
  }
  if (object.type === "Feature") {
    drawGeoJson(context, object.geometry, tile);
    return;
  }
  if (object.type === "GeometryCollection" && Array.isArray(object.geometries)) {
    object.geometries.forEach((item) => drawGeoJson(context, item, tile));
    return;
  }
  const coordinates = object.coordinates;
  const path = (points: unknown, close: boolean) => {
    if (!Array.isArray(points)) return;
    context.beginPath();
    let started = false;
    for (const coordinate of points)
      if (
        Array.isArray(coordinate) &&
        typeof coordinate[0] === "number" &&
        typeof coordinate[1] === "number"
      ) {
        const point = lonLatPoint(coordinate[0], coordinate[1], tile);
        if (!started) {
          context.moveTo(point.x, point.y);
          started = true;
        } else context.lineTo(point.x, point.y);
      }
    if (close) {
      context.closePath();
      context.fillStyle = "rgba(75,85,99,.25)";
      context.fill("evenodd");
    }
    context.strokeStyle = "#111827";
    context.lineWidth = 2;
    context.stroke();
  };
  if (object.type === "LineString") path(coordinates, false);
  else if (object.type === "MultiLineString" && Array.isArray(coordinates))
    coordinates.forEach((line) => path(line, false));
  else if (object.type === "Polygon" && Array.isArray(coordinates))
    coordinates.forEach((ring) => path(ring, true));
  else if (object.type === "MultiPolygon" && Array.isArray(coordinates))
    coordinates.forEach(
      (polygon) => Array.isArray(polygon) && polygon.forEach((ring) => path(ring, true)),
    );
}

async function renderNativeTileUncached(
  session: ProjectSession,
  tile: TileCoordinate,
  cacheNamespace?: string,
  signal?: AbortSignal,
): Promise<HTMLCanvasElement> {
  signal?.throwIfAborted();
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas rendering is unavailable");
  const sourceZoom = sourceMaxZoom(session.render.source);
  if (session.render.source === "usgs-topo" && tile.z > sourceZoom) {
    const difference = tile.z - sourceZoom,
      factor = 2 ** difference;
    const parent = await renderNativeTile(
      session,
      { z: sourceZoom, x: Math.floor(tile.x / factor), y: Math.floor(tile.y / factor) },
      cacheNamespace,
      signal,
    );
    const sourceSize = SIZE / factor,
      sourceX = (tile.x % factor) * sourceSize,
      sourceY = (tile.y % factor) * sourceSize;
    context.imageSmoothingEnabled = false;
    context.drawImage(parent, sourceX, sourceY, sourceSize, sourceSize, 0, 0, SIZE, SIZE);
    return canvas;
  }
  if (session.render.source === "usgs-topo") {
    const image = await imageFrom(
      `https://basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/${tile.z}/${tile.y}/${tile.x}`,
    );
    context.drawImage(image, 0, 0, SIZE, SIZE);
    image.close();
  } else {
    const difference = Math.max(0, tile.z - sourceZoom),
      factor = 2 ** difference;
    const sourceTile = {
      z: Math.min(tile.z, sourceZoom),
      x: Math.floor(tile.x / factor),
      y: Math.floor(tile.y / factor),
    };
    const vectorView = difference
      ? { scale: factor, offsetX: (tile.x % factor) * SIZE, offsetY: (tile.y % factor) * SIZE }
      : IDENTITY_VIEW;
    const vector = await preparedVectorTile(
      `https://tiles.openfreemap.org/planet/latest/${sourceTile.z}/${sourceTile.x}/${sourceTile.y}.pbf`,
    );
    signal?.throwIfAborted();
    const enabled = new Set(session.render.elements),
      eink = session.render.mode !== "original",
      palette = eink ? EINK_COLORS : COLORS;
    context.fillStyle = palette.background;
    context.fillRect(0, 0, SIZE, SIZE);
    if (enabled.has("land")) {
      polygons(context, vector.layers.landcover, palette.landcover, undefined, vectorView);
      polygons(context, vector.layers.landuse, palette.landuse, undefined, vectorView);
      polygons(context, vector.layers.park, palette.park, eink ? "#aaaaaa" : "#5fd064", vectorView);
    }
    if (session.render.style === "osm-eink-topo") await drawTerrain(context, tile);
    if (enabled.has("water")) {
      polygons(context, vector.layers.water, palette.water, palette.water, vectorView);
      lines(context, vector.layers.waterway, palette.water, 1, vectorView);
    }
    if (enabled.has("buildings"))
      polygons(
        context,
        vector.layers.building,
        palette.building,
        palette.buildingOutline,
        vectorView,
      );
    if (enabled.has("boundaries"))
      lines(context, vector.layers.boundary, palette.boundary, 1, vectorView);
    transportation(context, vector.layers.transportation, tile.z, enabled, eink, vectorView);
    const placed: Array<[number, number, number, number]> = [];
    if (enabled.has("labels")) {
      labels(context, vector.layers.place, tile.z, placed, "place", vectorView);
      labels(context, vector.layers.water_name, tile.z, placed, "water", vectorView);
      labels(
        context,
        vector.layers.transportation_name,
        tile.z,
        tile.z >= 18 ? [] : placed,
        "road",
        vectorView,
      );
    }
    if (enabled.has("pois")) labels(context, vector.layers.poi, tile.z, placed, "poi", vectorView);
  }
  for (const layer of session.geojson_layers)
    if (layer.visible && tile.z >= layer.min_zoom && tile.z <= layer.max_zoom)
      drawGeoJson(context, layer.geojson, tile);
  const bounds = tileBounds(tile);
  drawProjectMarkers(context, session.markers, (marker) => {
    if (
      marker.lon < bounds.west ||
      marker.lon > bounds.east ||
      marker.lat < bounds.south ||
      marker.lat > bounds.north
    )
      return null;
    return lonLatPoint(marker.lon, marker.lat, tile);
  });
  return canvas;
}

export function renderNativeTile(
  session: ProjectSession,
  tile: TileCoordinate,
  cacheNamespace?: string,
  signal?: AbortSignal,
): Promise<HTMLCanvasElement> {
  signal?.throwIfAborted();
  if (!cacheNamespace) return renderNativeTileUncached(session, tile, undefined, signal);
  const key = `${cacheNamespace}:${tile.z}/${tile.x}/${tile.y}`;
  const existing = renderedTileCache.get(key);
  if (existing) {
    touchLru(renderedTileCache, key, existing, RENDER_CACHE_LIMIT);
    return existing.then((canvas) => {
      signal?.throwIfAborted();
      return canvas;
    });
  }
  const pending = renderNativeTileUncached(session, tile, cacheNamespace);
  touchLru(renderedTileCache, key, pending, RENDER_CACHE_LIMIT);
  pending.catch(() => renderedTileCache.get(key) === pending && renderedTileCache.delete(key));
  return pending.then((canvas) => {
    signal?.throwIfAborted();
    return canvas;
  });
}
