import { describe, expect, it } from "vitest";
import { encodeMuiIndexedPng } from "./muiPng";

describe("MUI indexed PNG encoding", () => {
  it("writes a valid 8-bit indexed-color PNG", () => {
    const png = encodeMuiIndexedPng({
      width: 2,
      height: 1,
      data: new Uint8ClampedArray([255, 0, 0, 255, 0, 128, 255, 255]),
    });
    expect([...png.subarray(0, 8)]).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
    expect(new TextDecoder().decode(png.subarray(12, 16))).toBe("IHDR");
    expect(png[24]).toBe(8);
    expect(png[25]).toBe(3);
    expect(new TextDecoder().decode(png)).toContain("PLTE");
  });
});
