import { describe, expect, it } from "vitest";
import type { AreaSelection } from "../models";
import { defaultSession } from "./session";
import {
  estimateBrowserExportFast,
  lonLatToTile,
  planTileCoverage,
  selectionZoomCacheIdentity,
  summarizeTiles,
  tilesForSelection,
} from "./tiles";

function selection(overrides: Partial<AreaSelection> = {}): AreaSelection {
  return {
    selection_id: "area",
    name: "Area",
    enabled: true,
    exact: false,
    min_zoom: 0,
    max_zoom: 1,
    bbox: { west: -1, south: -1, east: 1, north: 1 },
    geojson: null,
    ...overrides,
  };
}

describe("browser tile selection", () => {
  it("represents the whole world exactly once at z0", () => {
    expect(
      tilesForSelection(
        selection({
          bbox: { west: -180, south: -85, east: 180, north: 85 },
          min_zoom: 0,
          max_zoom: 0,
        }),
      ),
    ).toEqual([{ z: 0, x: 0, y: 0 }]);
  });

  it("filters bounding-box candidates against exact polygons", () => {
    const rectangle = selection({
      min_zoom: 3,
      max_zoom: 3,
      bbox: { west: -170, south: 10, east: -10, north: 80 },
    });
    const area = {
      ...rectangle,
      exact: true,
      geojson: {
        type: "MultiPolygon",
        coordinates: [
          [
            [
              [-169, 79],
              [-160, 79],
              [-160, 70],
              [-169, 79],
            ],
          ],
          [
            [
              [-20, 20],
              [-11, 20],
              [-11, 11],
              [-20, 20],
            ],
          ],
        ],
      },
    };
    expect(tilesForSelection(area).length).toBeLessThan(tilesForSelection(rectangle).length);
  });

  it("deduplicates overlapping selections", () => {
    const session = defaultSession();
    session.area_selections = [
      selection({ selection_id: "one", min_zoom: 0, max_zoom: 0 }),
      selection({ selection_id: "two", min_zoom: 0, max_zoom: 0 }),
    ];
    const tiles = planTileCoverage(session).tiles;
    expect(tiles).toHaveLength(1);
    expect(summarizeTiles(tiles, session, true).raw_bytes).toBe(8192);
  });

  it("adds one-tile-per-level transition rings between overlapping regions", () => {
    const session = defaultSession();
    session.export.smooth_zoom_transitions = true;
    session.area_selections = [
      selection({
        selection_id: "outer",
        min_zoom: 0,
        max_zoom: 1,
        bbox: { west: -20, south: -20, east: 20, north: 20 },
      }),
      selection({
        selection_id: "inner",
        min_zoom: 0,
        max_zoom: 3,
        bbox: { west: -1, south: -1, east: 1, north: 1 },
      }),
    ];
    const smoothed = planTileCoverage({
      area_selections: session.area_selections,
      smooth_zoom_transitions: true,
    }).tiles;
    const unsmoothed = planTileCoverage({ area_selections: session.area_selections }).tiles;
    expect(smoothed.filter(({ z }) => z === 2)).toHaveLength(16);
    expect(unsmoothed.filter(({ z }) => z === 2)).toHaveLength(4);
    const estimate = summarizeTiles(smoothed, session, true);
    expect(estimate.transition_tile_count).toBe(12);
    expect(estimate.transition_raw_bytes).toBe(12 * 8192);
    expect(smoothed.filter(({ z }) => z === 3)).toHaveLength(
      unsmoothed.filter(({ z }) => z === 3).length,
    );
  });

  it("estimates full-color MUI tiles as 8-bit indexed pixels", () => {
    const session = defaultSession();
    session.render.mode = "original";
    session.area_selections = [selection({ min_zoom: 0, max_zoom: 0 })];
    expect(summarizeTiles(planTileCoverage(session).tiles, session, true).raw_bytes).toBe(65536);
  });

  it("produces live size estimates without claiming exact tile intersection", () => {
    const session = defaultSession();
    session.area_selections = [selection({ min_zoom: 0, max_zoom: 1 })];
    const estimate = estimateBrowserExportFast(session);
    expect(estimate.exact).toBe(false);
    expect(estimate.zooms.map(({ zoom }) => zoom)).toEqual([0, 1]);
    expect(estimate.raw_bytes).toBe(estimate.tile_count * 8192);
  });

  it("reuses cached selection zooms and calculates only missing levels", () => {
    const area = selection({ min_zoom: 0, max_zoom: 1 });
    const session = defaultSession();
    session.area_selections = [area];
    const cachedIdentity = selectionZoomCacheIdentity(area, 0),
      progress: Array<{ completed: number; total: number }> = [];
    const result = planTileCoverage(session, (value) => progress.push(value), {
      [cachedIdentity.key]: [{ z: 0, x: 0, y: 0 }],
    });
    expect(result.tiles.some((tile) => tile.z === 0)).toBe(true);
    expect(result.cacheWrites.map(({ key }) => key)).not.toContain(cachedIdentity.key);
    expect(result.cacheWrites).toHaveLength(1);
    expect(progress[0].total).toBeGreaterThan(0);
    expect(progress.at(-1)?.completed).toBe(progress.at(-1)?.total);
  });

  it("converts the origin to the expected tile", () => {
    expect(lonLatToTile(0, 0, 1)).toEqual([1, 1]);
  });

  it("wraps antimeridian-crossing bounding boxes", () => {
    const wrapped = selection({
      min_zoom: 2,
      max_zoom: 2,
      bbox: { west: 170, south: -1, east: -170, north: 1 },
    });
    expect(new Set(tilesForSelection(wrapped).map((tile) => tile.x))).toEqual(new Set([0, 3]));
  });
});
