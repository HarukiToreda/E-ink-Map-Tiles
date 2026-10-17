import { describe, expect, it } from "vitest";
import { PMTiles } from "pmtiles";
import { buildRasterPmtiles, zxyToTileId } from "./pmtilesWriter";

describe("PMTiles v3 writer", () => {
  it("uses the specified cumulative Hilbert tile IDs", () => {
    expect(
      [
        [0, 0, 0],
        [1, 0, 0],
        [1, 0, 1],
        [1, 1, 1],
        [1, 1, 0],
      ].map(([z, x, y]) => zxyToTileId(z, x, y)),
    ).toEqual([0, 1, 2, 3, 4]);
    expect(zxyToTileId(12, 3423, 1763)).toBe(19078479);
  });

  it("writes a raster PNG PMTiles v3 header and metadata", () => {
    const archive = buildRasterPmtiles(
      [{ tile: { z: 0, x: 0, y: 0 }, data: Uint8Array.from([137, 80, 78, 71]) }],
      "liberty",
      "OpenStreetMap",
    );
    const view = new DataView(archive.buffer);
    expect(new TextDecoder().decode(archive.subarray(0, 7))).toBe("PMTiles");
    expect(archive[7]).toBe(3);
    expect(archive[99]).toBe(2);
    const metadataOffset = Number(view.getBigUint64(24, true)),
      metadataLength = Number(view.getBigUint64(32, true));
    expect(
      JSON.parse(
        new TextDecoder().decode(archive.subarray(metadataOffset, metadataOffset + metadataLength)),
      ).name,
    ).toBe("liberty");
  });

  it("is readable by the official PMTiles client", async () => {
    const png = Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]);
    const archive = buildRasterPmtiles(
      [{ tile: { z: 0, x: 0, y: 0 }, data: png }],
      "liberty",
      "OpenStreetMap",
    );
    const reader = new PMTiles({
      getKey: () => "memory://test.pmtiles",
      getBytes: async (offset, length) => ({ data: archive.slice(offset, offset + length).buffer }),
    });
    expect((await reader.getHeader()).tileType).toBe(2);
    expect(new Uint8Array((await reader.getZxy(0, 0, 0))!.data)).toEqual(png);
    expect(await reader.getMetadata()).toMatchObject({ name: "liberty", type: "baselayer" });
  });
});
