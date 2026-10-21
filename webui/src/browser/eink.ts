import type { TileDepth } from "../models";

export interface PixelBuffer {
  width: number;
  height: number;
  data: Uint8ClampedArray;
}

const BAYER_4X4 = [
  [15, 7, 13, 5],
  [3, 11, 1, 9],
  [12, 4, 14, 6],
  [0, 8, 2, 10],
];

function luminance(red: number, green: number, blue: number): number {
  // Pillow's integer RGB -> L conversion, retained for Python-export parity.
  return (19595 * red + 38470 * green + 7471 * blue + 32768) >> 16;
}

/** Convert an RGBA render into the exact grayscale levels representable by MTB. */
export function convertToMtbPixels(source: PixelBuffer, depth: TileDepth): Uint8Array<ArrayBuffer> {
  const output = new Uint8Array(source.width * source.height);
  const raw = new Uint8Array(output.length),
    sharpened = new Float32Array(output.length);
  for (let index = 0; index < output.length; index++) {
    const offset = index * 4,
      alpha = source.data[offset + 3] / 255;
    raw[index] = luminance(
      Math.round(source.data[offset] * alpha + 255 * (1 - alpha)),
      Math.round(source.data[offset + 1] * alpha + 255 * (1 - alpha)),
      Math.round(source.data[offset + 2] * alpha + 255 * (1 - alpha)),
    );
  }
  for (let y = 0; y < source.height; y++)
    for (let x = 0; x < source.width; x++) {
      const index = y * source.width + x;
      let total = 0,
        count = 0;
      for (let dy = -1; dy <= 1; dy++)
        for (let dx = -1; dx <= 1; dx++) {
          const px = x + dx,
            py = y + dy;
          if (px >= 0 && px < source.width && py >= 0 && py < source.height) {
            total += raw[py * source.width + px];
            count++;
          }
        }
      const detail = raw[index] - total / count;
      const sharp = Math.abs(detail) > 2 ? raw[index] + detail * 1.5 : raw[index];
      sharpened[index] = Math.max(0, Math.min(255, sharp));
    }
  const levels = (1 << depth) - 1;
  for (let y = 0; y < source.height; y++)
    for (let x = 0; x < source.width; x++) {
      const index = y * source.width + x,
        offset = index * 4;
      const water = source.data[offset + 2] - source.data[offset] > 25;
      if (depth === 1) {
        if (water || sharpened[index] <= 175) {
          output[index] = 0;
          continue;
        }
        const protectedMidtone = raw[index] > 175 && raw[index] <= 215;
        if (sharpened[index] > 215 && !protectedMidtone) {
          output[index] = 255;
          continue;
        }
        output[index] = 220 >= BAYER_4X4[y % 4][x % 4] * (255 / 16) ? 255 : 0;
        continue;
      }
      const gray = water ? (depth === 2 ? 85 : 102) : sharpened[index];
      const scaled = (gray * levels) / 255,
        lower = Math.floor(scaled),
        fraction = scaled - lower;
      const threshold = (BAYER_4X4[y % 4][x % 4] + 0.5) / 16;
      const level =
        depth < 4 && fraction > threshold
          ? Math.min(levels, lower + 1)
          : depth < 4
            ? lower
            : Math.round(scaled);
      output[index] = Math.round((level * 255) / levels);
    }
  return output;
}

/** Pack 256×256 grayscale pixels using the firmware's column-major MTB layout. */
export function packMtbColumnMajor(
  pixels: Uint8Array,
  depth: TileDepth,
  width = 256,
  height = 256,
): Uint8Array<ArrayBuffer> {
  if (width !== 256 || height !== 256 || pixels.length !== width * height)
    throw new Error("MTB tiles must be 256×256 pixels");
  const pixelsPerByte = 8 / depth;
  const levels = (1 << depth) - 1;
  const packed = new Uint8Array((width * height) / pixelsPerByte);
  for (let byteX = 0; byteX < width / pixelsPerByte; byteX++) {
    for (let y = 0; y < height; y++) {
      let value = 0;
      for (let pixelIndex = 0; pixelIndex < pixelsPerByte; pixelIndex++) {
        const x = byteX * pixelsPerByte + pixelIndex;
        // FastEPD contract for every MTB depth: 0=black, maximum=white,
        // with the leftmost pixel in the most-significant packed bits.
        const level = Math.round((pixels[y * width + x] * levels) / 255);
        const shift = (pixelsPerByte - 1 - pixelIndex) * depth;
        value |= level << shift;
      }
      packed[byteX * height + y] = value;
    }
  }
  return packed;
}
