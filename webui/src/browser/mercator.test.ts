import { describe, expect, it } from "vitest";
import { sourceMaxZoom, zoomLabel } from "./mapConfig";
import { boundsCenter, lonLatToWorld, worldToLonLat, zoomToFit } from "./mercator";

describe("Web Mercator utilities", () => {
  it("round-trips a geographic point", () => {
    const world = lonLatToWorld(-82.3535, 36.3134, 12);
    const location = worldToLonLat(world.x, world.y, 12);
    expect(location.lon).toBeCloseTo(-82.3535, 8);
    expect(location.lat).toBeCloseTo(36.3134, 8);
  });

  it("describes native and derived zoom levels consistently", () => {
    expect(sourceMaxZoom("openfreemap-vector")).toBe(14);
    expect(zoomLabel(14, "openfreemap-vector")).toBe("z14");
    expect(zoomLabel(18, "openfreemap-vector")).toBe("z14 +4");
  });

  it("fits larger areas at lower zoom levels", () => {
    const small = zoomToFit({ west: -82.4, south: 36.2, east: -82.2, north: 36.4 }, 800, 600, 14);
    const large = zoomToFit({ west: -125, south: 25, east: -66, north: 49 }, 800, 600, 14);
    expect(small).toBeGreaterThan(large);
  });

  it("centers and fits bounds that cross the antimeridian", () => {
    const bounds = { west: 170, south: -10, east: -170, north: 10 };
    expect(Math.abs(boundsCenter(bounds).lon)).toBe(180);
    expect(zoomToFit(bounds, 800, 600, 14)).toBeGreaterThan(1);
  });
});
