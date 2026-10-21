import type { MapBounds, MapView } from "../models";

export const TILE_SIZE = 256;
export const MAX_DISPLAY_ZOOM = 20;
export const MAX_MERCATOR_LATITUDE = 85.05112878;

export interface Point {
  x: number;
  y: number;
}

export function lonLatToWorld(lon: number, lat: number, zoom: number): Point {
  const size = TILE_SIZE * 2 ** zoom;
  const boundedLatitude = Math.max(-MAX_MERCATOR_LATITUDE, Math.min(MAX_MERCATOR_LATITUDE, lat));
  return {
    x: ((lon + 180) / 360) * size,
    y: ((1 - Math.asinh(Math.tan((boundedLatitude * Math.PI) / 180)) / Math.PI) / 2) * size,
  };
}

export function worldToLonLat(x: number, y: number, zoom: number): { lon: number; lat: number } {
  const size = TILE_SIZE * 2 ** zoom;
  return {
    lon: (x / size) * 360 - 180,
    lat: (180 / Math.PI) * Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / size))),
  };
}

export function viewport(view: MapView, width: number, height: number) {
  const center = lonLatToWorld(view.center_lon, view.center_lat, view.zoom);
  return { center, left: center.x - width / 2, top: center.y - height / 2 };
}

export function boundsCenter(bounds: MapBounds): { lon: number; lat: number } {
  const lon =
    bounds.west <= bounds.east
      ? (bounds.west + bounds.east) / 2
      : (((bounds.west + bounds.east + 360) / 2 + 540) % 360) - 180;
  return { lon, lat: (bounds.south + bounds.north) / 2 };
}

export function zoomToFit(
  bounds: MapBounds,
  width: number,
  height: number,
  maximum: number,
): number {
  let result = 0;
  for (let zoom = 0; zoom <= maximum; zoom++) {
    const northwest = lonLatToWorld(bounds.west, bounds.north, zoom);
    const southeast = lonLatToWorld(bounds.east, bounds.south, zoom);
    const worldWidth = TILE_SIZE * 2 ** zoom;
    const geographicWidth =
      bounds.west <= bounds.east
        ? southeast.x - northwest.x
        : worldWidth - northwest.x + southeast.x;
    if (
      geographicWidth <= Math.max(1, width - 64) &&
      Math.abs(southeast.y - northwest.y) <= Math.max(1, height - 64)
    ) {
      result = zoom;
    } else {
      break;
    }
  }
  return result;
}
