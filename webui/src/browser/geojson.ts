import type { MapBounds } from "../models";

export type JsonObject = Record<string, unknown>;

export function isJsonObject(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function geoJsonCoordinates(
  value: unknown,
  output: [number, number][] = [],
): [number, number][] {
  if (Array.isArray(value)) {
    if (
      value.length >= 2 &&
      typeof value[0] === "number" &&
      Number.isFinite(value[0]) &&
      typeof value[1] === "number" &&
      Number.isFinite(value[1])
    ) {
      output.push([value[0], value[1]]);
    } else {
      value.forEach((item) => geoJsonCoordinates(item, output));
    }
  } else if (isJsonObject(value)) {
    if ("coordinates" in value) geoJsonCoordinates(value.coordinates, output);
    if ("geometry" in value) geoJsonCoordinates(value.geometry, output);
    if ("geometries" in value) geoJsonCoordinates(value.geometries, output);
    if ("features" in value) geoJsonCoordinates(value.features, output);
  }
  return output;
}

export function geoJsonBounds(value: unknown): MapBounds | null {
  const coordinates = geoJsonCoordinates(value);
  if (!coordinates.length) return null;
  let west = Infinity,
    east = -Infinity,
    south = Infinity,
    north = -Infinity;
  for (const [lon, lat] of coordinates) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return { west, east, south, north };
}

export function geoJsonPrimitiveCount(value: unknown): number {
  if (!isJsonObject(value)) return 0;
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    return value.features.reduce((total, feature) => total + geoJsonPrimitiveCount(feature), 0);
  }
  if (value.type === "Feature") return geoJsonPrimitiveCount(value.geometry);
  if (value.type === "GeometryCollection" && Array.isArray(value.geometries)) {
    return value.geometries.reduce((total, geometry) => total + geoJsonPrimitiveCount(geometry), 0);
  }
  if (["MultiPoint", "MultiLineString", "MultiPolygon"].includes(String(value.type))) {
    return Array.isArray(value.coordinates) ? value.coordinates.length : 0;
  }
  return ["Point", "LineString", "Polygon"].includes(String(value.type)) ? 1 : 0;
}

function collectGeometries(value: unknown, output: JsonObject[]): void {
  if (!isJsonObject(value)) return;
  if (value.type === "FeatureCollection" && Array.isArray(value.features)) {
    value.features.forEach((feature) => collectGeometries(feature, output));
  } else if (value.type === "Feature") {
    collectGeometries(value.geometry, output);
  } else if (value.type === "GeometryCollection" && Array.isArray(value.geometries)) {
    value.geometries.forEach((geometry) => collectGeometries(geometry, output));
  } else if (typeof value.type === "string" && "coordinates" in value) {
    output.push(value);
  }
}

export function selectionGeometry(value: unknown): JsonObject | null {
  const geometries: JsonObject[] = [];
  collectGeometries(value, geometries);
  if (!geometries.length) return null;
  if (geometries.length === 1) return structuredClone(geometries[0]);
  return { type: "GeometryCollection", geometries: structuredClone(geometries) };
}
