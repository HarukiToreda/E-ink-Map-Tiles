import type { SearchResult } from "../models";
import { isJsonObject } from "./geojson";

interface NominatimItem {
  display_name?: string;
  lat: string;
  lon: string;
  boundingbox?: string[];
  type?: string;
  category?: string;
  geojson?: Record<string, unknown>;
  address?: Record<string, string>;
  osm_type?: string;
  osm_id?: number;
}

interface OverpassPoint {
  lat: number;
  lon: number;
}
interface OverpassMember {
  type?: string;
  role?: string;
  geometry?: OverpassPoint[];
}
interface OverpassElement {
  type?: string;
  geometry?: OverpassPoint[];
  members?: OverpassMember[];
}
interface PhotonFeature {
  geometry?: { type?: string; coordinates?: number[] };
  properties?: Record<string, unknown> & {
    osm_type?: string;
    osm_id?: number;
    name?: string;
    type?: string;
    countrycode?: string;
    postcode?: string;
    extent?: number[];
  };
}
type BoundaryDetails = Pick<
  SearchResult,
  "geojson" | "boundary_label" | "geometry_source" | "geometry_source_url"
>;
type Position = [number, number];

const TIGERWEB_ZCTA_QUERY =
  "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/PUMA_TAD_TAZ_UGA_ZCTA/MapServer/1/query";
const OVERPASS_QUERY = "https://overpass-api.de/api/interpreter";
const PHOTON_QUERY = "https://photon.komoot.io/api/";
const boundaryCache = new Map<string, Promise<BoundaryDetails | null>>();

function isNominatimItem(value: unknown): value is NominatimItem {
  return isJsonObject(value) && typeof value.lat === "string" && typeof value.lon === "string";
}

export function searchResultKey(result: SearchResult): string {
  return `${result.osm_type ?? ""}:${result.osm_id ?? ""}:${result.lat}:${result.lon}`;
}

function searchBounds(values?: string[]): SearchResult["bbox"] {
  if (values?.length !== 4) return null;
  const [south, north, west, east] = values.map(Number);
  if (
    ![south, north, west, east].every(Number.isFinite) ||
    south > north ||
    south < -90 ||
    north > 90 ||
    west < -180 ||
    west > 180 ||
    east < -180 ||
    east > 180
  )
    return null;
  return { south, north, west, east };
}

function samePosition(a: Position, b: Position): boolean {
  return a[0] === b[0] && a[1] === b[1];
}
function positions(points?: OverpassPoint[]): Position[] {
  return (points ?? []).map(({ lon, lat }) => [lon, lat]);
}

function stitchRings(parts: Position[][]): Position[][] {
  const unused = parts.filter((part) => part.length >= 2).map((part) => [...part]);
  const rings: Position[][] = [];
  while (unused.length) {
    const ring = unused.shift();
    if (!ring) break;
    while (!samePosition(ring[0], ring[ring.length - 1])) {
      const end = ring[ring.length - 1];
      const index = unused.findIndex(
        (part) => samePosition(part[0], end) || samePosition(part[part.length - 1], end),
      );
      if (index < 0) break;
      const next = unused.splice(index, 1)[0];
      if (!samePosition(next[0], end)) next.reverse();
      ring.push(...next.slice(1));
    }
    if (ring.length >= 4 && samePosition(ring[0], ring[ring.length - 1])) rings.push(ring);
  }
  return rings;
}

function pointInRing(point: Position, ring: Position[]): boolean {
  let inside = false;
  for (let index = 0, previous = ring.length - 1; index < ring.length; previous = index++) {
    const [xi, yi] = ring[index];
    const [xj, yj] = ring[previous];
    if (
      yi > point[1] !== yj > point[1] &&
      point[0] < ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi
    )
      inside = !inside;
  }
  return inside;
}

function overpassGeometry(elements: OverpassElement[]): Record<string, unknown> | null {
  const polygons: Position[][][] = [];
  for (const element of elements) {
    if (element.type === "way") {
      const ring = positions(element.geometry);
      if (ring.length >= 4 && samePosition(ring[0], ring[ring.length - 1])) polygons.push([ring]);
      continue;
    }
    if (element.type !== "relation") continue;
    const members = element.members ?? [];
    const outers = stitchRings(
      members
        .filter((member) => member.type === "way" && member.role !== "inner")
        .map((member) => positions(member.geometry)),
    );
    const inners = stitchRings(
      members
        .filter((member) => member.type === "way" && member.role === "inner")
        .map((member) => positions(member.geometry)),
    );
    for (const outer of outers)
      polygons.push([outer, ...inners.filter((inner) => pointInRing(inner[0], outer))]);
  }
  if (polygons.length === 1) return { type: "Polygon", coordinates: polygons[0] };
  if (polygons.length > 1) return { type: "MultiPolygon", coordinates: polygons };
  return null;
}

async function queryOverpass(query: string): Promise<Record<string, unknown> | null> {
  try {
    // The public endpoint rejects browser-style form POSTs with 406 on some
    // frontends. These object/boundary queries are short enough for GET and
    // the GET endpoint is consistently CORS-accessible.
    const requestUrl = `${OVERPASS_QUERY}?${new URLSearchParams({ data: query })}`;
    const response = await fetch(requestUrl, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(20000),
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as { elements?: OverpassElement[] };
    return overpassGeometry(payload.elements ?? []);
  } catch {
    return null;
  }
}

function osmBoundary(geometry: Record<string, unknown>, label: string): BoundaryDetails {
  return {
    geojson: geometry,
    boundary_label: label,
    geometry_source: "OpenStreetMap Overpass",
    geometry_source_url: "https://www.openstreetmap.org/copyright",
  };
}

async function resolveOsmObject(
  item: Pick<SearchResult, "osm_id" | "osm_type">,
): Promise<BoundaryDetails | null> {
  if (!item.osm_id || !["way", "relation"].includes(item.osm_type ?? "")) return null;
  const geometry = await queryOverpass(
    `[out:json][timeout:15];${item.osm_type}(${item.osm_id});out geom;`,
  );
  return geometry ? osmBoundary(geometry, "OpenStreetMap boundary") : null;
}

function escapeOverpass(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

async function resolveOsmPostalBoundary(
  postcode: string,
  bbox: SearchResult["bbox"],
): Promise<BoundaryDetails | null> {
  if (!postcode || !bbox) return null;
  const code = escapeOverpass(postcode);
  const bounds = `${bbox.south},${bbox.west},${bbox.north},${bbox.east}`;
  const selectors = ["postal_code", "ref"]
    .flatMap((key) =>
      ["way", "relation"].map(
        (kind) => `${kind}["boundary"="postal_code"]["${key}"="${code}"](${bounds});`,
      ),
    )
    .join("");
  const geometry = await queryOverpass(`[out:json][timeout:15];(${selectors});out geom;`);
  return geometry ? osmBoundary(geometry, "Postal boundary") : null;
}

async function resolveUsZcta(postcode: string): Promise<BoundaryDetails | null> {
  if (!/^\d{5}$/.test(postcode)) return null;
  const params = new URLSearchParams({
    where: `ZCTA5='${postcode}'`,
    outFields: "ZCTA5,NAME",
    returnGeometry: "true",
    outSR: "4326",
    f: "geojson",
  });
  try {
    const response = await fetch(`${TIGERWEB_ZCTA_QUERY}?${params}`, {
      headers: { Accept: "application/geo+json, application/json" },
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as {
      features?: Array<{ geometry?: Record<string, unknown> }>;
    };
    const geometry = payload.features?.[0]?.geometry;
    if (!geometry || !["Polygon", "MultiPolygon"].includes(String(geometry.type))) return null;
    return {
      geojson: geometry,
      boundary_label: "Census ZCTA boundary",
      geometry_source: "U.S. Census Bureau TIGERweb",
      geometry_source_url:
        "https://www.census.gov/programs-surveys/geography/guidance/geo-areas/zctas.html",
    };
  } catch {
    return null;
  }
}

function photonDisplayName(properties: PhotonFeature["properties"]): string {
  if (!properties) return "Unnamed result";
  const parts = [
    properties.name,
    properties.city,
    properties.county,
    properties.state,
    properties.country,
  ].filter((part): part is string => typeof part === "string" && Boolean(part.trim()));
  return [...new Set(parts)].join(", ") || "Unnamed result";
}

async function searchPhoton(query: string, limit: number): Promise<NominatimItem[]> {
  try {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    const response = await fetch(`${PHOTON_QUERY}?${params}`, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(12000),
    });
    if (!response.ok) return [];
    const payload = (await response.json()) as { features?: PhotonFeature[] };
    return (payload.features ?? []).flatMap((feature) => {
      const coordinates = feature.geometry?.coordinates;
      const properties = feature.properties;
      if (!properties || !coordinates || coordinates.length < 2) return [];
      const extent = properties.extent;
      const osmTypes: Record<string, string> = { R: "relation", W: "way", N: "node" };
      return [
        {
          display_name: photonDisplayName(properties),
          lat: String(coordinates[1]),
          lon: String(coordinates[0]),
          boundingbox:
            extent?.length === 4
              ? [String(extent[3]), String(extent[1]), String(extent[0]), String(extent[2])]
              : undefined,
          type: properties.type,
          category: String(properties.osm_key ?? "place"),
          address: {
            country_code: String(properties.countrycode ?? "").toLowerCase(),
            postcode: properties.postcode ?? "",
          },
          osm_type: osmTypes[properties.osm_type ?? ""] ?? properties.osm_type?.toLowerCase(),
          osm_id: properties.osm_id,
        },
      ];
    });
  } catch {
    return [];
  }
}

export async function searchBrowserLocations(
  query: string,
  limit = 5,
): Promise<{ results: SearchResult[] }> {
  const normalizedQuery = query.trim();
  const params = new URLSearchParams({
    q: normalizedQuery,
    format: "jsonv2",
    limit: String(limit),
    addressdetails: "1",
  });
  const response = await fetch(`https://nominatim.openstreetmap.org/search?${params}`, {
    headers: { Accept: "application/json" },
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) throw new Error(`Location search failed (${response.status})`);
  const responseData: unknown = await response.json();
  let payload = Array.isArray(responseData) ? responseData.filter(isNominatimItem) : [];
  let searchSource = "OpenStreetMap Nominatim";
  if (!payload.length) {
    payload = await searchPhoton(normalizedQuery, limit);
    searchSource = "OpenStreetMap Photon";
  }
  const results = payload.flatMap((item): SearchResult[] => {
    const postcode = item.address?.postcode ?? "";
    const lat = Number(item.lat);
    const lon = Number(item.lon);
    if (
      !Number.isFinite(lat) ||
      !Number.isFinite(lon) ||
      lat < -90 ||
      lat > 90 ||
      lon < -180 ||
      lon > 180
    )
      return [];
    return [
      {
        display_name: item.display_name ?? "Unnamed result",
        lat,
        lon,
        bbox: searchBounds(item.boundingbox),
        category:
          postcode && postcode.toLowerCase() === normalizedQuery.toLowerCase()
            ? "postcode"
            : (item.type ?? item.category ?? "place"),
        geojson: null,
        country_code: item.address?.country_code ?? "",
        postcode,
        osm_type: item.osm_type,
        osm_id: item.osm_id,
        boundary_label: "Bounding rectangle",
        geometry_source: searchSource,
        geometry_source_url: "https://www.openstreetmap.org/copyright",
      },
    ];
  });
  return { results };
}

export async function resolveBrowserLocationBoundary(result: SearchResult): Promise<SearchResult> {
  if (result.geojson) return result;
  const key = `${result.osm_type ?? ""}:${result.osm_id ?? ""}:${result.country_code}:${result.postcode}:${JSON.stringify(result.bbox)}`;
  let pending = boundaryCache.get(key);
  if (!pending) {
    pending = (async () => {
      let resolved = await resolveOsmObject(result);
      if (!resolved && result.country_code === "us" && result.category === "postcode")
        resolved = await resolveUsZcta(result.postcode);
      if (!resolved && result.category === "postcode")
        resolved = await resolveOsmPostalBoundary(result.postcode, result.bbox);
      return resolved;
    })();
    boundaryCache.set(key, pending);
    if (boundaryCache.size > 64) {
      const oldestKey = boundaryCache.keys().next().value;
      if (oldestKey !== undefined) boundaryCache.delete(oldestKey);
    }
  }
  const resolved = await pending;
  // A timeout or temporary public-service failure should be retryable when
  // the user adds the result again, rather than becoming a session-long box.
  if (!resolved && boundaryCache.get(key) === pending) boundaryCache.delete(key);
  return resolved ? { ...result, ...resolved } : result;
}
