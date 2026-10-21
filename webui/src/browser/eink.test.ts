import { describe, expect, it } from "vitest";
import { convertToMtbPixels, packMtbColumnMajor } from "./eink";

describe("browser MTB conversion", () => {
  it("quantizes to the supported shade counts", () => {
    const rgba = new Uint8ClampedArray([
      0, 0, 0, 255, 85, 85, 85, 255, 170, 170, 170, 255, 255, 255, 255, 255,
    ]);
    expect([...convertToMtbPixels({ width: 4, height: 1, data: rgba }, 1)]).toEqual([0, 0, 0, 255]);
    expect([...convertToMtbPixels({ width: 4, height: 1, data: rgba }, 2)]).toEqual([
      0, 85, 170, 255,
    ]);
  });

  it("packs black and white pixels in firmware column-major order", () => {
    const pixels = new Uint8Array(256 * 256).fill(255);
    for (let x = 0; x < 8; x++) pixels[x] = x % 2 ? 255 : 0;
    const packed = packMtbColumnMajor(pixels, 1);
    expect(packed.length).toBe(8192);
    expect(packed[0]).toBe(0b01010101);
    expect(packed[1]).toBe(0xff);
  });

  it("packs MTB1 left-to-right from the most-significant bit", () => {
    const pixels = new Uint8Array(256 * 256);
    pixels[0] = 255;
    expect(packMtbColumnMajor(pixels, 1)[0]).toBe(0x80);
  });

  it("packs MTB2 left-to-right from the most-significant pair", () => {
    const pixels = new Uint8Array(256 * 256);
    pixels[0] = 85;
    pixels[1] = 170;
    pixels[2] = 255;
    expect(packMtbColumnMajor(pixels, 2)[0]).toBe(0x6c);
  });

  it("packs four-bit pixels two per byte", () => {
    const pixels = new Uint8Array(256 * 256).fill(255);
    pixels[0] = 0;
    pixels[1] = 255;
    expect(packMtbColumnMajor(pixels, 4)[0]).toBe(0x0f);
  });

  it("uses the FastEPD MTB4 level and nibble contract", () => {
    const pixels = new Uint8Array(256 * 256).fill(255);
    pixels[0] = 17; // level 1, left/high nibble
    pixels[1] = 34; // level 2, right/low nibble
    expect(packMtbColumnMajor(pixels, 4)[0]).toBe(0x12);
  });

  it("keeps structural ink black and gives water a stable depth-specific tone", () => {
    const rgba = new Uint8ClampedArray([0, 0, 0, 255, 158, 189, 255, 255, 248, 244, 240, 255]);
    expect([...convertToMtbPixels({ width: 3, height: 1, data: rgba }, 1)]).toEqual([0, 0, 255]);
    expect([...convertToMtbPixels({ width: 3, height: 1, data: rgba }, 2)]).toEqual([0, 85, 255]);
    expect([...convertToMtbPixels({ width: 3, height: 1, data: rgba }, 4)]).toEqual([0, 102, 255]);
  });

  it("uses the established Bayer pattern for MTB1 midtones", () => {
    const data = new Uint8ClampedArray(4 * 4 * 4);
    for (let index = 0; index < 16; index++) data.set([200, 200, 200, 255], index * 4);
    const converted = convertToMtbPixels({ width: 4, height: 4, data }, 1);
    expect(new Set(converted)).toEqual(new Set([0, 255]));
  });
});

describe("browser InkHUD conversion fixture", () => {
  it.each([1, 2, 4] as const)("produces stable, non-flat %i-bit packed output", (depth) => {
    const data = new Uint8ClampedArray(256 * 256 * 4);
    for (let y = 0; y < 256; y++)
      for (let x = 0; x < 256; x++) {
        const offset = (y * 256 + x) * 4;
        data[offset] = (x * 17 + y * 3) % 256;
        data[offset + 1] = (x * 5 + y * 11) % 256;
        data[offset + 2] = (x * 13 + y * 7) % 256;
        data[offset + 3] = 255;
      }
    const packed = packMtbColumnMajor(
      convertToMtbPixels({ width: 256, height: 256, data }, depth),
      depth,
    );
    expect(packed.length).toBe((256 * 256 * depth) / 8);
    expect(new Set(packed).size).toBeGreaterThan(8);
    expect(packed.reduce((total, byte) => total + byte, 0)).toBeGreaterThan(0);
  });
});
