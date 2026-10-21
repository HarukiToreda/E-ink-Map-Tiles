import { zlibSync } from "fflate";
import type { PixelBuffer } from "./eink";

const crcTable = new Uint32Array(256);
for (let value = 0; value < 256; value++) {
  let crc = value;
  for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? 0xedb88320 ^ (crc >>> 1) : crc >>> 1;
  crcTable[value] = crc >>> 0;
}

function writeUint32(target: Uint8Array, offset: number, value: number): void {
  new DataView(target.buffer, target.byteOffset, target.byteLength).setUint32(offset, value >>> 0);
}

function chunk(type: string, data: Uint8Array): Uint8Array {
  const result = new Uint8Array(12 + data.length);
  writeUint32(result, 0, data.length);
  const typeBytes = new TextEncoder().encode(type);
  result.set(typeBytes, 4);
  result.set(data, 8);
  let crc = 0xffffffff;
  for (let index = 4; index < 8 + data.length; index++)
    crc = crcTable[(crc ^ result[index]) & 0xff] ^ (crc >>> 8);
  writeUint32(result, 8 + data.length, (crc ^ 0xffffffff) >>> 0);
  return result;
}

function concatenate(parts: Uint8Array[]): Uint8Array {
  const result = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

/** Encode an opaque, MUI-friendly PNG with a fixed 256-color RGB palette. */
export function encodeMuiIndexedPng(pixels: PixelBuffer): Uint8Array {
  const palette = new Uint8Array(256 * 3);
  for (let index = 0; index < 256; index++) {
    palette[index * 3] = Math.round((((index >>> 5) & 7) * 255) / 7);
    palette[index * 3 + 1] = Math.round((((index >>> 2) & 7) * 255) / 7);
    palette[index * 3 + 2] = Math.round(((index & 3) * 255) / 3);
  }
  const scanlines = new Uint8Array((pixels.width + 1) * pixels.height);
  for (let y = 0; y < pixels.height; y++) {
    const row = y * (pixels.width + 1);
    scanlines[row] = 0;
    for (let x = 0; x < pixels.width; x++) {
      const source = (y * pixels.width + x) * 4,
        alpha = pixels.data[source + 3] / 255;
      const red = pixels.data[source] * alpha + 255 * (1 - alpha);
      const green = pixels.data[source + 1] * alpha + 255 * (1 - alpha);
      const blue = pixels.data[source + 2] * alpha + 255 * (1 - alpha);
      scanlines[row + x + 1] =
        (Math.round((red * 7) / 255) << 5) |
        (Math.round((green * 7) / 255) << 2) |
        Math.round((blue * 3) / 255);
    }
  }
  const header = new Uint8Array(13);
  writeUint32(header, 0, pixels.width);
  writeUint32(header, 4, pixels.height);
  header[8] = 8;
  header[9] = 3; // 8-bit indexed color
  return concatenate([
    Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("PLTE", palette),
    chunk("IDAT", zlibSync(scanlines, { level: 6 })),
    chunk("IEND", new Uint8Array()),
  ]);
}
