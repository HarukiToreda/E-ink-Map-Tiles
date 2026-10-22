import type { ProjectSession } from "../models";
import { mapAttributionText, mapLicenseText } from "./mapConfig";
import type { TileCoordinate } from "./tiles";

export function sdCardAttributionText(
  session: ProjectSession,
  tiles: readonly TileCoordinate[],
): string {
  const zooms = [...new Set(tiles.map((tile) => tile.z))].sort((a, b) => a - b);
  return [
    "E-ink Map Tiles SD card bundle",
    `Source: ${session.render.source}`,
    `Style: ${session.render.style}`,
    `E-ink bit depth: ${session.inkhud.tile_depth}`,
    `Tile count: ${tiles.length}`,
    `Zoom levels: ${zooms.join(", ")}`,
    `Enabled map elements: ${session.render.elements.join(", ") || "none"}`,
    `Terrain overlay: ${session.render.style === "osm-eink-topo" ? "enabled" : "disabled"}`,
    "",
    "Required attribution",
    mapAttributionText(session).trimEnd(),
    "",
  ].join("\n");
}

export function sdCardLicenseText(session: ProjectSession): string {
  return [
    "LICENSES AND DATA TERMS",
    "",
    "The rendered map data in this bundle remains subject to the following licenses and terms.",
    "",
    mapLicenseText(session).trimEnd(),
    "",
  ].join("\n");
}
