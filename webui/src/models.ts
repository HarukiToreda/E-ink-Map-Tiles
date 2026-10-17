export type MapSource = "openfreemap-vector" | "usgs-topo";
export type MapStyle = "osm-eink" | "osm-eink-topo";
export type RenderMode = "original" | "inkhud";
export type TileDepth = 1 | 2 | 4;
export type ExportKind = "normal-zip" | "mui-pmtiles" | "inkhud-header" | "inkhud-binary";
export type MapElement =
  | "land"
  | "water"
  | "roads"
  | "highways"
  | "paths"
  | "buildings"
  | "boundaries"
  | "labels"
  | "pois"
  | "transit";

export interface MapView {
  center_lat: number;
  center_lon: number;
  zoom: number;
}

export interface ProjectSnapshot {
  project_id: string;
  revision: number;
  render_revision: number;
  session: ProjectSession;
}

export interface ProjectSession {
  version: 3;
  map_revealed: boolean;
  view: MapView;
  render: {
    source: MapSource;
    style: MapStyle;
    mode: RenderMode;
    elements: MapElement[];
  };
  export: {
    attribution_acknowledged: boolean;
    smooth_zoom_transitions: boolean;
  };
  inkhud: {
    tile_depth: TileDepth;
  };
  markers: Marker[];
  geojson_layers: GeoJsonLayer[];
  area_selections: AreaSelection[];
}

export interface Marker {
  marker_id: string;
  lat: number;
  lon: number;
  label: string;
  label_is_marker: boolean;
}

export interface GeoJsonLayer {
  layer_id: string;
  name: string;
  geojson: Record<string, unknown>;
  visible: boolean;
  min_zoom: number;
  max_zoom: number;
}

export interface AreaSelection {
  selection_id: string;
  name: string;
  enabled: boolean;
  exact: boolean;
  min_zoom: number;
  max_zoom: number;
  bbox: MapBounds;
  geojson: Record<string, unknown> | null;
  source_layer_id?: string;
}

export interface MapBounds {
  west: number;
  south: number;
  east: number;
  north: number;
}

export interface SearchResult {
  display_name: string;
  lat: number;
  lon: number;
  bbox: MapBounds | null;
  category: string;
  geojson: Record<string, unknown> | null;
  country_code: string;
  postcode: string;
  boundary_label: string;
  geometry_source: string;
  geometry_source_url: string;
  osm_type?: string;
  osm_id?: number;
}

export interface ExportEstimate {
  exact: boolean;
  tile_count: number;
  raw_bytes: number;
  transition_tile_count: number;
  transition_raw_bytes: number;
  zooms: { zoom: number; tile_count: number; raw_bytes: number }[];
}

export interface ExportJob {
  job_id: string;
  project_id: string;
  kind: ExportKind;
  status: "running" | "completed" | "cancelled" | "failed";
  completed: number;
  total: number;
  message: string;
  error: string | null;
  artifact_size_bytes: number | null;
  compression_ratio: number | null;
  logs: string[];
}
