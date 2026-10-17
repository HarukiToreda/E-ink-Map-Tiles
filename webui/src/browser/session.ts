import type {
  AreaSelection,
  GeoJsonLayer,
  MapElement,
  MapSource,
  MapStyle,
  Marker,
  ProjectSession,
  TileDepth,
} from "../models";
import { isMapSource } from "./mapConfig";
import { MAX_DISPLAY_ZOOM, MAX_MERCATOR_LATITUDE } from "./mercator";

const MAP_ELEMENTS: ReadonlySet<string> = new Set<MapElement>([
  "land",
  "water",
  "roads",
  "highways",
  "paths",
  "buildings",
  "boundaries",
  "labels",
  "pois",
  "transit",
]);

export function defaultSession(): ProjectSession {
  return {
    version: 3,
    map_revealed: false,
    view: { center_lat: 0, center_lon: 0, zoom: 2 },
    render: {
      source: "openfreemap-vector",
      style: "osm-eink",
      mode: "inkhud",
      elements: ["land", "water", "roads", "highways", "paths", "boundaries", "labels", "transit"],
    },
    export: { attribution_acknowledged: true, smooth_zoom_transitions: false },
    inkhud: { tile_depth: 1 },
    markers: [],
    geojson_layers: [],
    area_selections: [],
  };
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function object(value: unknown): Record<string, unknown> {
  return isObject(value) ? value : {};
}

function number(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function zoom(value: unknown, fallback: number): number {
  return Math.round(clamp(number(value, fallback), 0, MAX_DISPLAY_ZOOM));
}

function source(value: unknown, fallback: MapSource): MapSource {
  return isMapSource(value) ? value : fallback;
}

function style(value: unknown, fallback: MapStyle): MapStyle {
  return value === "osm-eink" || value === "osm-eink-topo" ? value : fallback;
}

export function isTileDepth(value: unknown): value is TileDepth {
  return value === 1 || value === 2 || value === 4;
}

function tileDepth(value: unknown, fallback: TileDepth): TileDepth {
  return isTileDepth(value) ? value : fallback;
}

function normalizeMarker(value: unknown): Marker | null {
  const input = object(value);
  const lat = number(input.lat, Number.NaN);
  const lon = number(input.lon, Number.NaN);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return {
    marker_id: typeof input.marker_id === "string" ? input.marker_id : crypto.randomUUID(),
    lat: clamp(lat, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE),
    lon: clamp(lon, -180, 180),
    label: typeof input.label === "string" ? input.label : "Marker",
    label_is_marker: input.label_is_marker === true,
  };
}

function normalizeLayer(value: unknown): GeoJsonLayer | null {
  const input = object(value);
  if (!isObject(input.geojson)) return null;
  const minZoom = zoom(input.min_zoom, 0);
  const maxZoom = Math.max(minZoom, zoom(input.max_zoom, MAX_DISPLAY_ZOOM));
  return {
    layer_id: typeof input.layer_id === "string" ? input.layer_id : crypto.randomUUID(),
    name: typeof input.name === "string" ? input.name : "GeoJSON layer",
    geojson: input.geojson,
    visible: input.visible !== false,
    min_zoom: minZoom,
    max_zoom: maxZoom,
  };
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizeSelection(value: unknown): AreaSelection | null {
  const input = object(value);
  const bbox = object(input.bbox);
  const rawWest = finiteNumber(bbox.west);
  const rawSouth = finiteNumber(bbox.south);
  const rawEast = finiteNumber(bbox.east);
  const rawNorth = finiteNumber(bbox.north);
  if (rawWest === null || rawSouth === null || rawEast === null || rawNorth === null) return null;

  const west = clamp(rawWest, -180, 180);
  const east = clamp(rawEast, -180, 180);
  const south = clamp(rawSouth, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE);
  const north = clamp(rawNorth, -MAX_MERCATOR_LATITUDE, MAX_MERCATOR_LATITUDE);
  if (south > north) return null;
  const minZoom = zoom(input.min_zoom, 0);
  const maxZoom = Math.max(minZoom, zoom(input.max_zoom, 12));
  const geojson = isObject(input.geojson) ? input.geojson : null;
  return {
    selection_id: typeof input.selection_id === "string" ? input.selection_id : crypto.randomUUID(),
    name: typeof input.name === "string" ? input.name : "Selected area",
    enabled: input.enabled !== false,
    exact: input.exact === true && geojson !== null,
    min_zoom: minZoom,
    max_zoom: maxZoom,
    bbox: { west, south, east, north },
    geojson,
    ...(typeof input.source_layer_id === "string"
      ? { source_layer_id: input.source_layer_id }
      : {}),
  };
}

export function normalizeSession(value: unknown): ProjectSession {
  if (!isObject(value)) throw new Error("Session file must contain a JSON object");
  if (value.version !== 3) {
    throw new Error(`Unsupported session version: ${String(value.version)}`);
  }

  const defaults = defaultSession();
  const view = object(value.view);
  const render = object(value.render);
  const exportSettings = object(value.export);
  const inkhud = object(value.inkhud);
  const normalizedSource = source(render.source, defaults.render.source);
  const normalizedStyle = style(render.style, defaults.render.style);

  return {
    version: 3,
    map_revealed: value.map_revealed === true,
    view: {
      center_lat: clamp(
        number(view.center_lat, defaults.view.center_lat),
        -MAX_MERCATOR_LATITUDE,
        MAX_MERCATOR_LATITUDE,
      ),
      center_lon: clamp(number(view.center_lon, defaults.view.center_lon), -180, 180),
      zoom: zoom(view.zoom, defaults.view.zoom),
    },
    render: {
      source: normalizedSource,
      style: normalizedSource === "usgs-topo" ? "osm-eink" : normalizedStyle,
      mode: render.mode === "original" ? "original" : "inkhud",
      elements: Array.isArray(render.elements)
        ? [
            ...new Set(
              render.elements.filter(
                (item): item is MapElement => typeof item === "string" && MAP_ELEMENTS.has(item),
              ),
            ),
          ]
        : defaults.render.elements,
    },
    export: {
      attribution_acknowledged: exportSettings.attribution_acknowledged !== false,
      smooth_zoom_transitions: exportSettings.smooth_zoom_transitions === true,
    },
    inkhud: {
      tile_depth: tileDepth(inkhud.tile_depth, defaults.inkhud.tile_depth),
    },
    markers: Array.isArray(value.markers)
      ? value.markers.map(normalizeMarker).filter((item): item is Marker => Boolean(item))
      : [],
    geojson_layers: Array.isArray(value.geojson_layers)
      ? value.geojson_layers
          .map(normalizeLayer)
          .filter((item): item is GeoJsonLayer => Boolean(item))
      : [],
    area_selections: Array.isArray(value.area_selections)
      ? value.area_selections
          .map(normalizeSelection)
          .filter((item): item is AreaSelection => Boolean(item))
      : [],
  };
}
