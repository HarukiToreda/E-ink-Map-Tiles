import { describe, expect, it } from "vitest";
import { buildSparseMtbBinary, buildSparseMtbHeader, compressLz4Block } from "./mtb";

function decompress(block: Uint8Array, expected: number): Uint8Array {
  const output = new Uint8Array(expected);
  let source = 0,
    target = 0;
  while (source < block.length) {
    const token = block[source++];
    let literals = token >>> 4;
    if (literals === 15) {
      let byte;
      do {
        byte = block[source++];
        literals += byte;
      } while (byte === 255);
    }
    output.set(block.subarray(source, source + literals), target);
    source += literals;
    target += literals;
    if (source >= block.length) break;
    const distance = block[source++] | (block[source++] << 8);
    let match = (token & 15) + 4;
    if ((token & 15) === 15) {
      let byte;
      do {
        byte = block[source++];
        match += byte;
      } while (byte === 255);
    }
    for (let index = 0; index < match; index++) {
      output[target] = output[target - distance];
      target++;
    }
  }
  return output;
}

describe("browser MTB artifacts", () => {
  it("writes firmware-compatible raw LZ4 blocks", () => {
    const source = Uint8Array.from({ length: 8192 }, (_, index) => index % 31);
    const compressed = compressLz4Block(source);
    expect([...decompress(compressed, source.length)]).toEqual([...source]);
    expect(compressed.length).toBeLessThan(source.length);
  });

  it("writes a sparse MTB binary header and positions", () => {
    const binary = buildSparseMtbBinary([{ z: 7, x: 12, y: 34, pixels: new Uint8Array(8192) }], 1);
    expect(new TextDecoder().decode(binary.subarray(0, 4))).toBe("MTB1");
    const view = new DataView(binary.buffer);
    expect(view.getUint32(8, true)).toBe(1);
    expect(binary[16]).toBe(7);
    expect(view.getUint16(17, true)).toBe(12);
    expect(view.getUint16(19, true)).toBe(34);
    expect(binary[21]).toBe(2);
  });

  it("writes the firmware C header schema", () => {
    const header = buildSparseMtbHeader(
      [{ z: 7, x: 12, y: 34, pixels: new Uint8Array(8192) }],
      1,
      "osm-eink",
    );
    expect(header).toContain("static const uint8_t map_tile_bit_depth = 1;");
    expect(header).toContain('static const char map_tile_attribution[] = "";');
    expect(header).toContain("static const uint16_t map_tile_count = 1;");
    expect(header).toContain("static const uint8_t map_tile_zooms[] = { 7 };");
    expect(header).toContain("static const uint8_t map_tile_kinds[] = { 2 };");
    expect(header).toContain("0x00,  // padding byte when all tiles are sentinel-filled");
  });

  it("embeds escaped attribution in the C header without changing MTB binary data", () => {
    const tile = { z: 0, x: 0, y: 0, pixels: new Uint8Array(8192) };
    const header = buildSparseMtbHeader(
      [tile],
      1,
      "test",
      'OpenStreetMap "contributors"\nline two',
      "ODbL\\terms",
    );
    expect(header).toContain(
      'static const char map_tile_attribution[] = "OpenStreetMap \\"contributors\\"\\nline two";',
    );
    expect(header).toContain('static const char map_tile_license[] = "ODbL\\\\terms";');
    expect(new TextDecoder().decode(buildSparseMtbBinary([tile], 1).subarray(0, 4))).toBe("MTB1");
  });

  it("describes the byte-column count for each depth", () => {
    const tile = { z: 0, x: 0, y: 0 };
    expect(buildSparseMtbHeader([{ ...tile, pixels: new Uint8Array(8192) }], 1, "test")).toContain(
      "[bx=0..31][y=0..255]",
    );
    expect(buildSparseMtbHeader([{ ...tile, pixels: new Uint8Array(16384) }], 2, "test")).toContain(
      "[bx=0..63][y=0..255]",
    );
    expect(buildSparseMtbHeader([{ ...tile, pixels: new Uint8Array(32768) }], 4, "test")).toContain(
      "[bx=0..127][y=0..255]",
    );
  });

  it("recognizes white and black sentinel bytes for every MTB depth", () => {
    const tile = { z: 0, x: 0, y: 0 };
    for (const depth of [1, 2, 4] as const) {
      const length = (256 * 256 * depth) / 8;
      expect(
        buildSparseMtbHeader(
          [{ ...tile, pixels: new Uint8Array(length).fill(0xff) }],
          depth,
          "test",
        ),
      ).toContain("static const uint8_t map_tile_kinds[] = { 1 };");
      expect(
        buildSparseMtbHeader([{ ...tile, pixels: new Uint8Array(length) }], depth, "test"),
      ).toContain("static const uint8_t map_tile_kinds[] = { 2 };");
    }
  });
});
