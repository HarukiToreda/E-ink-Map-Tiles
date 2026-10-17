import { describe, expect, it } from "vitest";
import {
  geoJsonBounds,
  geoJsonCoordinates,
  geoJsonPrimitiveCount,
  selectionGeometry,
} from "./geojson";

const collection = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { name: "area" },
      geometry: {
        type: "Polygon",
        coordinates: [
          [
            [-3, 1],
            [4, 1],
            [4, 6],
            [-3, 1],
          ],
        ],
      },
    },
    {
      type: "Feature",
      properties: { name: "route" },
      geometry: {
        type: "LineString",
        coordinates: [
          [-2, -5],
          [8, 2],
        ],
      },
    },
  ],
};

describe("GeoJSON utilities", () => {
  it("finds coordinates and bounds through feature collections", () => {
    expect(geoJsonCoordinates(collection)).toHaveLength(6);
    expect(geoJsonBounds(collection)).toEqual({ west: -3, south: -5, east: 8, north: 6 });
  });

  it("counts primitive geometries", () => {
    expect(geoJsonPrimitiveCount(collection)).toBe(2);
  });

  it("turns a feature collection into one exact selection geometry", () => {
    expect(selectionGeometry(collection)).toEqual({
      type: "GeometryCollection",
      geometries: [collection.features[0].geometry, collection.features[1].geometry],
    });
  });

  it("rejects objects without coordinates", () => {
    expect(geoJsonBounds({ type: "FeatureCollection", features: [] })).toBeNull();
    expect(geoJsonBounds({ type: "Point", coordinates: [Infinity, 2] })).toBeNull();
    expect(selectionGeometry({ hello: "world" })).toBeNull();
  });
});
