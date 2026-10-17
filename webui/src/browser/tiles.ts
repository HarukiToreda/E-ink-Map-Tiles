import booleanIntersects from "@turf/boolean-intersects";
import { feature, polygon } from "@turf/helpers";
import type { AreaSelection, ExportEstimate, ProjectSession } from "../models";
import { MAX_MERCATOR_LATITUDE } from "./mercator";

export interface TileCoordinate {
  z: number;
  x: number;
  y: number;
  transition?: boolean;
}
export interface TileEstimateProgress {
  completed: number;
  total: number;
}
export interface TilePlanCacheEntry {
  key: string;
  signature: string;
  tiles: TileCoordinate[];
}
export type TileSelection = Pick<
  AreaSelection,
  "selection_id" | "enabled" | "exact" | "min_zoom" | "max_zoom" | "bbox" | "geojson"
>;
export type TileCoverageSession = {
  area_selections: TileSelection[];
  smooth_zoom_transitions?: boolean;
};
export type TileFormatSession = {
  render: Pick<ProjectSession["render"], "mode">;
  inkhud: Pick<ProjectSession["inkhud"], "tile_depth">;
};
export type TilePlanningSession = TileCoverageSession & TileFormatSession;
const geometryStatsCache = new Map<string, { area: number; perimeter: number }>();

export function lonLatToTile(lon: number, lat: number, zoom: number): [number, number] {
  const scale = 2 ** zoom,
    boundedLat = Math.max(-MAX_MERCATOR_LATITUDE, Math.min(MAX_MERCATOR_LATITUDE, lat));
  const x = Math.floor(((lon + 180) / 360) * scale);
  const y = Math.floor(
    ((1 - Math.asinh(Math.tan((boundedLat * Math.PI) / 180)) / Math.PI) / 2) * scale,
  );
  return [Math.max(0, Math.min(scale - 1, x)), Math.max(0, Math.min(scale - 1, y))];
}

export function tileBounds({ z, x, y }: TileCoordinate) {
  const scale = 2 ** z;
  const lon = (value: number) => (value / scale) * 360 - 180;
  const lat = (value: number) =>
    (180 / Math.PI) * Math.atan(Math.sinh(Math.PI * (1 - (2 * value) / scale)));
  return { west: lon(x), east: lon(x + 1), north: lat(y), south: lat(y + 1) };
}

function candidateTileCountAtZoom(selection: TileSelection, zoom: number): number {
  return bboxTileCount(selection, zoom);
}

function* candidates(selection: TileSelection): Generator<TileCoordinate> {
  for (let z = selection.min_zoom; z <= selection.max_zoom; z++) {
    const [west, south] = lonLatToTile(selection.bbox.west, selection.bbox.south, z);
    const [east, north] = lonLatToTile(selection.bbox.east, selection.bbox.north, z);
    const xRanges: [number, number][] =
      selection.bbox.west > selection.bbox.east
        ? [
            [west, 2 ** z - 1],
            [0, east],
          ]
        : [[Math.min(west, east), Math.max(west, east)]];
    for (const [firstX, lastX] of xRanges)
      for (let x = firstX; x <= lastX; x++) {
        for (let y = Math.min(north, south); y <= Math.max(north, south); y++) yield { z, x, y };
      }
  }
}

function* candidatesAtZoom(selection: TileSelection, zoom: number): Generator<TileCoordinate> {
  yield* candidates({ ...selection, min_zoom: zoom, max_zoom: zoom });
}

function intersectsGeometry(
  tile: TileCoordinate,
  geometryFeature: ReturnType<typeof feature>,
): boolean {
  const bounds = tileBounds(tile);
  const rectangle = polygon([
    [
      [bounds.west, bounds.south],
      [bounds.east, bounds.south],
      [bounds.east, bounds.north],
      [bounds.west, bounds.north],
      [bounds.west, bounds.south],
    ],
  ]);
  try {
    return booleanIntersects(geometryFeature, rectangle);
  } catch {
    return true;
  }
}

function exactSelectionFeature(selection: TileSelection): ReturnType<typeof feature> | null {
  return selection.exact && selection.geojson
    ? feature(selection.geojson as unknown as Parameters<typeof feature>[0])
    : null;
}

export function tilesForSelection(
  selection: TileSelection,
  advance?: () => void,
): TileCoordinate[] {
  if (!selection.enabled) return [];
  const geometryFeature = exactSelectionFeature(selection);
  const matched: TileCoordinate[] = [];
  for (const tile of candidates(selection)) {
    if (!geometryFeature || intersectsGeometry(tile, geometryFeature)) matched.push(tile);
    advance?.();
  }
  return matched;
}

function tilesForSelectionAtZoom(
  selection: TileSelection,
  zoom: number,
  advance?: () => void,
): TileCoordinate[] {
  if (!selection.enabled) return [];
  const geometryFeature = exactSelectionFeature(selection);
  const matched: TileCoordinate[] = [];
  for (const tile of candidatesAtZoom(selection, zoom)) {
    if (!geometryFeature || intersectsGeometry(tile, geometryFeature)) matched.push(tile);
    advance?.();
  }
  return matched;
}

function hashText(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

export function selectionZoomCacheIdentity(
  selection: TileSelection,
  zoom: number,
): { key: string; signature: string } {
  const signature = JSON.stringify({
    bbox: selection.bbox,
    exact: selection.exact,
    geojson: selection.geojson,
    zoom,
  });
  return { key: `${selection.selection_id}:${zoom}:${hashText(signature)}`, signature };
}

export function rawBytesPerTile(session: TileFormatSession): number {
  return session.render.mode === "original"
    ? 256 * 256
    : (256 * 256 * session.inkhud.tile_depth) / 8;
}

export function planTileCoverage(
  session: TileCoverageSession,
  progress?: (value: TileEstimateProgress) => void,
  cached: Record<string, TileCoordinate[]> = {},
): { tiles: TileCoordinate[]; cacheWrites: TilePlanCacheEntry[] } {
  const total = session.area_selections
    .filter((selection) => selection.enabled)
    .reduce((sum, selection) => {
      for (let zoom = selection.min_zoom; zoom <= selection.max_zoom; zoom++) {
        const identity = selectionZoomCacheIdentity(selection, zoom);
        if (!cached[identity.key]) sum += candidateTileCountAtZoom(selection, zoom);
      }
      return sum;
    }, 0);
  let completed = 0,
    lastReport = performance.now();
  const advance = () => {
    completed++;
    const now = performance.now();
    if (progress && (now - lastReport >= 120 || completed === total)) {
      lastReport = now;
      progress({ completed, total });
    }
  };
  progress?.({ completed: 0, total });
  const byKey = new Map<string, TileCoordinate>(),
    tilesBySelection = new Map<string, Map<number, TileCoordinate[]>>(),
    cacheWrites: TilePlanCacheEntry[] = [];
  for (const selection of session.area_selections) {
    if (selection.enabled)
      for (let zoom = selection.min_zoom; zoom <= selection.max_zoom; zoom++) {
        const identity = selectionZoomCacheIdentity(selection, zoom);
        const tiles = cached[identity.key] ?? tilesForSelectionAtZoom(selection, zoom, advance);
        if (!cached[identity.key]) cacheWrites.push({ ...identity, tiles });
        let zooms = tilesBySelection.get(selection.selection_id);
        if (!zooms) {
          zooms = new Map();
          tilesBySelection.set(selection.selection_id, zooms);
        }
        zooms.set(zoom, tiles);
        for (const tile of tiles) byKey.set(`${tile.z}/${tile.x}/${tile.y}`, tile);
      }
  }
  if (session.smooth_zoom_transitions)
    addSmoothZoomTransitions(session.area_selections, tilesBySelection, byKey);
  const tiles = [...byKey.values()];
  tiles.sort((a, b) => a.z - b.z || a.x - b.x || a.y - b.y);
  return { tiles, cacheWrites };
}

function longitudeIntervals(selection: TileSelection): Array<[number, number]> {
  return selection.bbox.west <= selection.bbox.east
    ? [[selection.bbox.west, selection.bbox.east]]
    : [
        [selection.bbox.west, 180],
        [-180, selection.bbox.east],
      ];
}

function selectionsOverlap(left: TileSelection, right: TileSelection): boolean {
  if (left.bbox.north < right.bbox.south || right.bbox.north < left.bbox.south) return false;
  return longitudeIntervals(left).some(([leftWest, leftEast]) =>
    longitudeIntervals(right).some(
      ([rightWest, rightEast]) => leftEast >= rightWest && rightEast >= leftWest,
    ),
  );
}

function addSmoothZoomTransitions(
  selections: TileSelection[],
  tilesBySelection: Map<string, Map<number, TileCoordinate[]>>,
  output: Map<string, TileCoordinate>,
) {
  const enabled = selections.filter((selection) => selection.enabled);
  for (const inner of enabled) {
    const surroundingZoom = Math.max(
      -1,
      ...enabled
        .filter(
          (outer) =>
            outer.selection_id !== inner.selection_id &&
            outer.max_zoom < inner.max_zoom &&
            selectionsOverlap(inner, outer),
        )
        .map((outer) => outer.max_zoom),
    );
    if (surroundingZoom < 0) continue;
    const zooms = tilesBySelection.get(inner.selection_id);
    if (!zooms) continue;
    for (let zoom = Math.max(inner.min_zoom, surroundingZoom + 1); zoom < inner.max_zoom; zoom++) {
      const radius = inner.max_zoom - zoom;
      const scale = 2 ** zoom;
      for (const tile of zooms.get(zoom) ?? [])
        for (let dx = -radius; dx <= radius; dx++)
          for (let dy = -radius; dy <= radius; dy++) {
            const y = tile.y + dy;
            if (y < 0 || y >= scale) continue;
            const x = (((tile.x + dx) % scale) + scale) % scale;
            const key = `${zoom}/${x}/${y}`;
            if (!output.has(key)) output.set(key, { z: zoom, x, y, transition: true });
          }
    }
  }
}

export function summarizeTiles(
  tiles: TileCoordinate[],
  format: TileFormatSession,
  exact: boolean,
): ExportEstimate {
  const bytesPerTile = rawBytesPerTile(format);
  const zooms = new Map<number, number>();
  for (const tile of tiles) zooms.set(tile.z, (zooms.get(tile.z) ?? 0) + 1);
  const transition_tile_count = tiles.filter((tile) => tile.transition).length;
  return {
    exact,
    tile_count: tiles.length,
    raw_bytes: tiles.length * bytesPerTile,
    transition_tile_count,
    transition_raw_bytes: transition_tile_count * bytesPerTile,
    zooms: [...zooms]
      .sort(([a], [b]) => a - b)
      .map(([zoom, tile_count]) => ({ zoom, tile_count, raw_bytes: tile_count * bytesPerTile })),
  };
}

function bboxTileCount(selection: TileSelection, zoom: number): number {
  const [west, south] = lonLatToTile(selection.bbox.west, selection.bbox.south, zoom);
  const [east, north] = lonLatToTile(selection.bbox.east, selection.bbox.north, zoom);
  const columns =
    selection.bbox.west > selection.bbox.east
      ? 2 ** zoom - west + east + 1
      : Math.abs(east - west) + 1;
  return columns * (Math.abs(south - north) + 1);
}

function geometryStats(selection: TileSelection): { area: number; perimeter: number } | null {
  if (!selection.exact || !selection.geojson || selection.bbox.west > selection.bbox.east)
    return null;
  const cacheKey = `${selection.selection_id}:${hashText(JSON.stringify(selection.geojson))}`;
  const cached = geometryStatsCache.get(cacheKey);
  if (cached) return cached;
  const project = (coordinate: unknown): [number, number] | null => {
    if (
      !Array.isArray(coordinate) ||
      typeof coordinate[0] !== "number" ||
      typeof coordinate[1] !== "number"
    )
      return null;
    const lat = Math.max(-MAX_MERCATOR_LATITUDE, Math.min(MAX_MERCATOR_LATITUDE, coordinate[1]));
    return [
      (coordinate[0] + 180) / 360,
      (1 - Math.asinh(Math.tan((lat * Math.PI) / 180)) / Math.PI) / 2,
    ];
  };
  const ringStats = (ring: unknown): { area: number; perimeter: number } => {
    if (!Array.isArray(ring)) return { area: 0, perimeter: 0 };
    const points = ring.map(project).filter((point): point is [number, number] => Boolean(point));
    let twiceArea = 0,
      perimeter = 0;
    for (let index = 0; index < points.length; index++) {
      const current = points[index],
        next = points[(index + 1) % points.length];
      twiceArea += current[0] * next[1] - next[0] * current[1];
      perimeter += Math.hypot(next[0] - current[0], next[1] - current[1]);
    }
    return { area: Math.abs(twiceArea) / 2, perimeter };
  };
  const coordinates = selection.geojson.coordinates;
  const polygons: unknown[][] =
    selection.geojson.type === "Polygon" && Array.isArray(coordinates)
      ? [coordinates]
      : selection.geojson.type === "MultiPolygon" && Array.isArray(coordinates)
        ? coordinates.filter((polygon): polygon is unknown[] => Array.isArray(polygon))
        : [];
  if (!polygons.length) return null;
  let area = 0,
    perimeter = 0;
  for (const polygonRings of polygons)
    polygonRings.forEach((ring, index) => {
      const stats = ringStats(ring);
      area += index === 0 ? stats.area : -stats.area;
      perimeter += stats.perimeter;
    });
  const stats = { area: Math.max(0, area), perimeter };
  geometryStatsCache.set(cacheKey, stats);
  if (geometryStatsCache.size > 128) {
    const oldestKey = geometryStatsCache.keys().next().value;
    if (oldestKey !== undefined) geometryStatsCache.delete(oldestKey);
  }
  return stats;
}

/** Fast mathematical estimate shown while exact worker-based planning is still running. */
export function estimateBrowserExportFast(session: TilePlanningSession): ExportEstimate {
  const zooms = new Map<number, number>();
  for (const selection of session.area_selections) {
    if (selection.enabled)
      for (let zoom = selection.min_zoom; zoom <= selection.max_zoom; zoom++) {
        const bboxCount = bboxTileCount(selection, zoom),
          stats = geometryStats(selection),
          scale = 2 ** zoom;
        const count = stats
          ? Math.max(
              1,
              Math.min(
                bboxCount,
                Math.ceil(stats.area * scale * scale + stats.perimeter * scale + 1),
              ),
            )
          : bboxCount;
        zooms.set(zoom, (zooms.get(zoom) ?? 0) + count);
      }
  }
  const bytesPerTile = rawBytesPerTile(session);
  const rows = [...zooms]
    .sort(([left], [right]) => left - right)
    .map(([zoom, tile_count]) => ({ zoom, tile_count, raw_bytes: tile_count * bytesPerTile }));
  const tile_count = rows.reduce((total, row) => total + row.tile_count, 0);
  return {
    exact: false,
    tile_count,
    raw_bytes: tile_count * bytesPerTile,
    transition_tile_count: 0,
    transition_raw_bytes: 0,
    zooms: rows,
  };
}
