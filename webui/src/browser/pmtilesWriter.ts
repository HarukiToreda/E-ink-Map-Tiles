import type { TileCoordinate } from "./tiles";

interface ArchiveTile {
  tile: TileCoordinate;
  data: Uint8Array;
}
interface DirectoryEntry {
  tileId: number;
  offset: number;
  length: number;
  runLength: number;
}

function concat(parts: Uint8Array[]): Uint8Array {
  const output = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

function varint(output: number[], value: number): void {
  while (value >= 128) {
    output.push((value % 128) | 128);
    value = Math.floor(value / 128);
  }
  output.push(value);
}

function encodeDirectory(entries: DirectoryEntry[]): Uint8Array {
  const output: number[] = [];
  varint(output, entries.length);
  let previousId = 0;
  for (const entry of entries) {
    varint(output, entry.tileId - previousId);
    previousId = entry.tileId;
  }
  for (const entry of entries) varint(output, entry.runLength);
  for (const entry of entries) varint(output, entry.length);
  let nextOffset = 0;
  entries.forEach((entry, index) => {
    varint(output, index > 0 && entry.offset === nextOffset ? 0 : entry.offset + 1);
    nextOffset = entry.offset + entry.length;
  });
  return Uint8Array.from(output);
}

export function zxyToTileId(z: number, x: number, y: number): number {
  if (z < 0 || z > 26) throw new Error("PMTiles zoom must be between 0 and 26");
  const base = ((1 << z) * (1 << z) - 1) / 3;
  let order = 0,
    tx = x,
    ty = y;
  for (let size = 1 << (z - 1); size > 0; size >>= 1) {
    const rx = (tx & size) > 0 ? 1 : 0,
      ry = (ty & size) > 0 ? 1 : 0;
    order += size * size * ((3 * rx) ^ ry);
    if (ry === 0) {
      if (rx === 1) {
        tx = size - 1 - tx;
        ty = size - 1 - ty;
      }
      [tx, ty] = [ty, tx];
    }
  }
  return base + order;
}

function tileBounds(tile: TileCoordinate) {
  const scale = 2 ** tile.z;
  const lon = (x: number) => (x / scale) * 360 - 180;
  const lat = (y: number) =>
    (180 / Math.PI) * Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / scale)));
  return { west: lon(tile.x), east: lon(tile.x + 1), north: lat(tile.y), south: lat(tile.y + 1) };
}

function setUint64(view: DataView, offset: number, value: number): void {
  view.setBigUint64(offset, BigInt(value), true);
}

export function buildRasterPmtiles(
  tiles: ArchiveTile[],
  styleName: string,
  attribution: string,
): Uint8Array {
  if (!tiles.length) throw new Error("PMTiles requires at least one tile");
  const ordered = tiles
    .map((item) => ({ ...item, tileId: zxyToTileId(item.tile.z, item.tile.x, item.tile.y) }))
    .sort((a, b) => a.tileId - b.tileId);
  let tileOffset = 0;
  const entries: DirectoryEntry[] = ordered.map(({ tileId, data }) => {
    const entry = { tileId, offset: tileOffset, length: data.length, runLength: 1 };
    tileOffset += data.length;
    return entry;
  });
  const tileData = concat(ordered.map(({ data }) => data));
  let leafSize = 4096;
  let root: Uint8Array<ArrayBufferLike>;
  let leaves: Uint8Array<ArrayBufferLike>;
  while (true) {
    const leafParts: Uint8Array[] = [],
      rootEntries: DirectoryEntry[] = [];
    let leafOffset = 0;
    for (let start = 0; start < entries.length; start += leafSize) {
      const leaf = encodeDirectory(entries.slice(start, start + leafSize));
      leafParts.push(leaf);
      rootEntries.push({
        tileId: entries[start].tileId,
        offset: leafOffset,
        length: leaf.length,
        runLength: 0,
      });
      leafOffset += leaf.length;
    }
    const nextLeaves = concat(leafParts),
      nextRoot = encodeDirectory(rootEntries);
    if (nextRoot.length <= 16257) {
      leaves = nextLeaves;
      root = nextRoot;
      break;
    }
    leafSize *= 2;
  }
  const bounds = ordered.map(({ tile }) => tileBounds(tile));
  const west = Math.min(...bounds.map((value) => value.west)),
    south = Math.min(...bounds.map((value) => value.south));
  const east = Math.max(...bounds.map((value) => value.east)),
    north = Math.max(...bounds.map((value) => value.north));
  const minZoom = Math.min(...ordered.map(({ tile }) => tile.z)),
    maxZoom = Math.max(...ordered.map(({ tile }) => tile.z));
  const metadata = new TextEncoder().encode(
    JSON.stringify({
      name: styleName,
      description: "MUI raster map tiles",
      attribution,
      type: "baselayer",
      version: "1.0.0",
    }),
  );
  const header = new Uint8Array(127),
    view = new DataView(header.buffer);
  header.set(new TextEncoder().encode("PMTiles"));
  header[7] = 3;
  const rootOffset = 127,
    metadataOffset = rootOffset + root.length,
    leafOffset = metadataOffset + metadata.length,
    dataOffset = leafOffset + leaves.length;
  [
    rootOffset,
    root.length,
    metadataOffset,
    metadata.length,
    leafOffset,
    leaves.length,
    dataOffset,
    tileData.length,
    entries.length,
    entries.length,
    entries.length,
  ].forEach((value, index) => setUint64(view, 8 + index * 8, value));
  header[96] = 1;
  header[97] = 1;
  header[98] = 1;
  header[99] = 2;
  header[100] = minZoom;
  header[101] = maxZoom;
  view.setInt32(102, Math.round(west * 1e7), true);
  view.setInt32(106, Math.round(south * 1e7), true);
  view.setInt32(110, Math.round(east * 1e7), true);
  view.setInt32(114, Math.round(north * 1e7), true);
  header[118] = Math.min(maxZoom, minZoom + 2);
  view.setInt32(119, Math.round(((west + east) / 2) * 1e7), true);
  view.setInt32(123, Math.round(((south + north) / 2) * 1e7), true);
  return concat([header, root, metadata, leaves, tileData]);
}
