import { describe, expect, it } from "vitest";
import { defaultSession, normalizeSession } from "./session";

describe("browser session schema", () => {
  it("creates the minimal version 3 schema", () => {
    const session = defaultSession();
    expect(session.version).toBe(3);
    expect(session.render).toEqual({
      source: "openfreemap-vector",
      style: "osm-eink",
      mode: "inkhud",
      elements: ["land", "water", "roads", "highways", "paths", "boundaries", "labels", "transit"],
    });
    expect(session.inkhud).toEqual({ tile_depth: 1 });
    expect(session.export.smooth_zoom_transitions).toBe(false);
  });

  it("preserves the smooth zoom transition export option", () => {
    expect(
      normalizeSession({ version: 3, export: { smooth_zoom_transitions: true } }).export
        .smooth_zoom_transitions,
    ).toBe(true);
  });

  it("rejects sessions from every other schema version", () => {
    expect(() => normalizeSession({ version: 2 })).toThrow("Unsupported session version");
    expect(() => normalizeSession({ version: 99 })).toThrow("Unsupported session version");
    expect(() => normalizeSession({})).toThrow("Unsupported session version");
  });

  it("normalizes display zoom to an integer tile level", () => {
    const session = normalizeSession({ version: 3, view: { zoom: 4.6 } });
    expect(session.view.zoom).toBe(5);
  });

  it("normalizes untrusted session values at the storage boundary", () => {
    const session = normalizeSession({
      version: 3,
      view: { center_lat: 999, center_lon: -999, zoom: 99, width: -1, height: 0 },
      render: {
        source: "usgs-topo",
        style: "osm-eink-topo",
        elements: ["roads", "roads", "not-a-layer"],
      },
      markers: [{ marker_id: "marker", lat: -999, lon: 999, label: "Here" }],
      area_selections: [
        {
          selection_id: "valid",
          name: "Valid",
          bbox: { west: -200, south: -50, east: 200, north: 50 },
          min_zoom: 18,
          max_zoom: 4,
          exact: true,
        },
        {
          selection_id: "invalid",
          bbox: { west: Number.NaN, south: 0, east: 1, north: 1 },
        },
      ],
    });

    expect(session.view).toEqual({ center_lat: 85.05112878, center_lon: -180, zoom: 20 });
    expect(session.render).toMatchObject({
      source: "usgs-topo",
      style: "osm-eink",
      elements: ["roads"],
    });
    expect(session.markers[0]).toMatchObject({ lat: -85.05112878, lon: 180 });
    expect(session.area_selections).toHaveLength(1);
    expect(session.area_selections[0]).toMatchObject({
      exact: false,
      min_zoom: 18,
      max_zoom: 18,
      bbox: { west: -180, east: 180 },
    });
  });
});
