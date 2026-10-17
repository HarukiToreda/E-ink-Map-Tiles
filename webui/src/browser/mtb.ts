import type { TileDepth } from "../models";

export interface PackedTile {
  z: number;
  x: number;
  y: number;
  pixels: Uint8Array;
}

interface PreparedPayloads {
  kinds: number[];
  sizes: number[];
  offsets: number[];
  unique: Uint8Array[];
  uniqueOffsets: number[];
  totalBytes: number;
}

function appendLength(output: number[], length: number) {
  while (length >= 255) {
    output.push(255);
    length -= 255;
  }
  output.push(length);
}

/** Encode a raw LZ4 block (no size prefix), compatible with lz4.block in firmware tooling. */
export function compressLz4Block(input: Uint8Array): Uint8Array {
  if (!input.length) return new Uint8Array();
  const output: number[] = [],
    table = new Int32Array(1 << 16).fill(-1);
  let anchor = 0,
    cursor = 0;
  while (cursor + 4 <= input.length) {
    const sequence =
      (input[cursor] |
        (input[cursor + 1] << 8) |
        (input[cursor + 2] << 16) |
        (input[cursor + 3] << 24)) >>>
      0;
    const hash = Math.imul(sequence, 2654435761) >>> 16;
    const match = table[hash];
    table[hash] = cursor;
    if (
      match < 0 ||
      cursor - match > 0xffff ||
      input[match] !== input[cursor] ||
      input[match + 1] !== input[cursor + 1] ||
      input[match + 2] !== input[cursor + 2] ||
      input[match + 3] !== input[cursor + 3]
    ) {
      cursor++;
      continue;
    }
    const literalLength = cursor - anchor;
    let matchLength = 4;
    while (
      cursor + matchLength < input.length &&
      input[match + matchLength] === input[cursor + matchLength]
    )
      matchLength++;
    output.push((Math.min(literalLength, 15) << 4) | Math.min(matchLength - 4, 15));
    if (literalLength >= 15) appendLength(output, literalLength - 15);
    for (let index = anchor; index < cursor; index++) output.push(input[index]);
    const offset = cursor - match;
    output.push(offset & 0xff, offset >>> 8);
    if (matchLength - 4 >= 15) appendLength(output, matchLength - 19);
    cursor += matchLength;
    anchor = cursor;
  }
  const literals = input.length - anchor;
  output.push(Math.min(literals, 15) << 4);
  if (literals >= 15) appendLength(output, literals - 15);
  for (let index = anchor; index < input.length; index++) output.push(input[index]);
  return Uint8Array.from(output);
}

function allEqual(data: Uint8Array, value: number): boolean {
  for (const byte of data) if (byte !== value) return false;
  return data.length > 0;
}

function preparePayloads(tiles: PackedTile[]): PreparedPayloads {
  const unique: Uint8Array[] = [],
    uniqueOffsets: number[] = [];
  const kinds: number[] = [],
    sizes: number[] = [],
    offsets: number[] = [];
  const byValue = new Map<string, number>();
  for (const tile of tiles) {
    if (allEqual(tile.pixels, 0xff)) {
      kinds.push(1);
      sizes.push(0);
      offsets.push(0);
      continue;
    }
    if (allEqual(tile.pixels, 0)) {
      kinds.push(2);
      sizes.push(0);
      offsets.push(0);
      continue;
    }
    const payload = compressLz4Block(tile.pixels);
    const key = Array.from(payload, (byte) => String.fromCharCode(byte)).join("");
    let index = byValue.get(key);
    if (index === undefined) {
      index = unique.length;
      unique.push(payload);
      byValue.set(key, index);
    }
    kinds.push(0);
    sizes.push(payload.length);
    offsets.push(index);
  }
  let totalBytes = 0;
  for (const payload of unique) {
    uniqueOffsets.push(totalBytes);
    totalBytes += payload.length;
  }
  return {
    kinds,
    sizes,
    offsets: offsets.map((value, index) => (kinds[index] ? 0 : uniqueOffsets[value])),
    unique,
    uniqueOffsets,
    totalBytes,
  };
}

function uintType(values: number[]): "uint8_t" | "uint16_t" | "uint32_t" {
  const maximum = Math.max(0, ...values);
  return maximum <= 0xff ? "uint8_t" : maximum <= 0xffff ? "uint16_t" : "uint32_t";
}

function values(values: number[]): string {
  return values.join(", ");
}

/** Build the legacy firmware C header byte-for-byte in the same schema as Python. */
export function buildSparseMtbHeader(tiles: PackedTile[], depth: TileDepth, style: string): string {
  const payloads = preparePayloads(tiles),
    zooms = [...new Set(tiles.map((tile) => tile.z))].sort((a, b) => a - b);
  const compressed = payloads.kinds.filter((kind) => kind === 0).length;
  const lines = [
    "#pragma once",
    "#include <stdint.h>",
    "",
    `// ${style} InkHUD sparse tile export: ${tiles.length} tiles, zooms [${zooms.join(", ")}]`,
    `// Each tile is 256x256px at ${depth} bpp = ${(256 * 256 * depth) / 8} bytes uncompressed, stored here as raw LZ4 blocks.`,
    `// Byte layout is COLUMN-MAJOR: bytes are packed as [bx=0..${(256 * depth) / 8 - 1}][y=0..255].`,
    "// map_tile_kinds: 0=LZ4 payload, 1=all-white tile, 2=all-black tile",
    `// unique payloads: ${payloads.unique.length} / ${compressed} compressed tiles (${compressed - payloads.unique.length} deduplicated)`,
    `// sentinels: ${payloads.kinds.filter((kind) => kind === 1).length} white, ${payloads.kinds.filter((kind) => kind === 2).length} black`,
    "",
    `static const uint8_t map_tile_bit_depth = ${depth};`,
    "static const uint8_t map_tile_layout = 0;",
    "static const uint8_t map_tile_grid_cols = 0;",
    "static const uint8_t map_tile_grid_rows = 0;",
    "static const uint8_t map_tile_block_count = 0;",
    `static const ${tiles.length <= 0xffff ? "uint16_t" : "uint32_t"} map_tile_count = ${tiles.length};`,
    `static const ${uintType(tiles.map((tile) => tile.z))} map_tile_zooms[] = { ${values(tiles.map((tile) => tile.z))} };`,
    `static const ${uintType(tiles.map((tile) => tile.x))} map_tile_tx[] = { ${values(tiles.map((tile) => tile.x))} };`,
    `static const ${uintType(tiles.map((tile) => tile.y))} map_tile_ty[] = { ${values(tiles.map((tile) => tile.y))} };`,
    "static const uint8_t map_tile_block_zooms[] = {};",
    "static const uint16_t map_tile_block_tx[] = {};",
    "static const uint16_t map_tile_block_ty[] = {};",
    `static const ${uintType(payloads.kinds)} map_tile_kinds[] = { ${values(payloads.kinds)} };`,
    `static const ${uintType(payloads.sizes)} map_tile_sizes[] = { ${values(payloads.sizes)} };`,
    `static const ${uintType(payloads.offsets)} map_tile_offsets[] = { ${values(payloads.offsets)} };`,
    "",
    "static const uint8_t map_tile_data[] = {",
  ];
  if (!payloads.unique.length)
    lines.push("    0x00,  // padding byte when all tiles are sentinel-filled");
  payloads.unique.forEach((payload, index) => {
    lines.push(
      `    // blob ${index}, offset ${payloads.uniqueOffsets[index]}, ${payload.length} bytes`,
    );
    for (let start = 0; start < payload.length; start += 16) {
      lines.push(
        `    ${[...payload.subarray(start, start + 16)].map((byte) => `0x${byte.toString(16).toUpperCase().padStart(2, "0")}`).join(", ")},`,
      );
    }
  });
  lines.push("};");
  return lines.join("\n");
}

export function buildSparseMtbBinary(tiles: PackedTile[], depth: TileDepth): Uint8Array {
  const payloads = preparePayloads(tiles),
    dataLength = payloads.totalBytes;
  const result = new Uint8Array(16 + tiles.length * 5 + tiles.length * 7 + dataLength);
  const view = new DataView(result.buffer);
  let offset = 0;
  for (const byte of new TextEncoder().encode(`MTB${depth}`)) result[offset++] = byte;
  result[offset++] = 0;
  result[offset++] = 0;
  result[offset++] = 0;
  result[offset++] = 0;
  view.setUint32(offset, tiles.length, true);
  offset += 4;
  view.setUint32(offset, dataLength, true);
  offset += 4;
  for (const tile of tiles) {
    result[offset++] = tile.z;
    view.setUint16(offset, tile.x, true);
    offset += 2;
    view.setUint16(offset, tile.y, true);
    offset += 2;
  }
  tiles.forEach((_tile, index) => {
    result[offset++] = payloads.kinds[index];
    view.setUint16(offset, payloads.sizes[index], true);
    offset += 2;
    view.setUint32(offset, payloads.offsets[index], true);
    offset += 4;
  });
  for (const payload of payloads.unique) {
    result.set(payload, offset);
    offset += payload.length;
  }
  return result;
}

export function downloadBlob(name: string, blob: Blob) {
  const url = URL.createObjectURL(blob),
    anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
