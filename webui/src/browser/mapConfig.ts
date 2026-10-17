import type { MapSource, MapStyle, ProjectSession } from "../models";

export interface Attribution {
  label: string;
  url: string;
}

interface MapSourceDefinition {
  id: MapSource;
  label: string;
  maxZoom: number;
  configurableElements: boolean;
  optionalTopography: boolean;
}

export const MAP_SOURCES: readonly MapSourceDefinition[] = [
  {
    id: "openfreemap-vector",
    label: "OpenFreeMap vector",
    maxZoom: 14,
    configurableElements: true,
    optionalTopography: true,
  },
  {
    id: "usgs-topo",
    label: "USGS topo (US only)",
    maxZoom: 16,
    configurableElements: false,
    optionalTopography: false,
  },
];

const OPENFREEMAP_ATTRIBUTION: Attribution[] = [
  { label: "OpenFreeMap", url: "https://openfreemap.org/" },
  { label: "© OpenMapTiles", url: "https://openmaptiles.org/" },
  { label: "© OpenStreetMap contributors", url: "https://www.openstreetmap.org/copyright" },
  {
    label: "Liberty reference style",
    url: "https://github.com/hyperknot/openfreemap-styles",
  },
];

const MAPZEN_ATTRIBUTION: Attribution = {
  label: "Terrain data © Mapzen contributors",
  url: "https://github.com/tilezen/joerd/blob/master/docs/attribution.md",
};

const USGS_ATTRIBUTION: Attribution = {
  label: "Map services and data available from U.S. Geological Survey, National Geospatial Program",
  url: "https://www.usgs.gov/faqs/what-are-terms-uselicensing-map-services-and-data-national-map",
};

export function sourceMaxZoom(source: MapSource): number {
  return mapSourceDefinition(source).maxZoom;
}

export function isMapSource(value: unknown): value is MapSource {
  return typeof value === "string" && MAP_SOURCES.some((source) => source.id === value);
}

export function mapSourceDefinition(source: MapSource): MapSourceDefinition {
  const definition = MAP_SOURCES.find((item) => item.id === source);
  if (!definition) throw new Error(`Unknown map source: ${source}`);
  return definition;
}

export function zoomLabel(zoom: number, source: MapSource): string {
  const maximum = sourceMaxZoom(source);
  return zoom <= maximum ? `z${zoom}` : `z${maximum} +${zoom - maximum}`;
}

export function muiStyleName(style: MapStyle): string {
  return style === "osm-eink-topo" ? "liberty-topo" : "liberty";
}

export function mapAttributions(session: Pick<ProjectSession, "render">): readonly Attribution[] {
  if (session.render.source === "usgs-topo") return [USGS_ATTRIBUTION];
  return session.render.style === "osm-eink-topo"
    ? [...OPENFREEMAP_ATTRIBUTION, MAPZEN_ATTRIBUTION]
    : OPENFREEMAP_ATTRIBUTION;
}

export function mapAttributionText(session: Pick<ProjectSession, "render">): string {
  return `${mapAttributions(session)
    .map(({ label, url }) => `${label}\n${url}`)
    .join("\n\n")}\n`;
}
