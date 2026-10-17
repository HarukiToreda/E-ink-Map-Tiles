import { describe, expect, it } from "vitest";
import type { ExportEstimate } from "../models";
import {
  DESKTOP_RECOMMENDATION_BYTES,
  desktopDownloadUrl,
  desktopPlatform,
  shouldRecommendDesktop,
} from "./desktopRecommendation";

function estimate(raw_bytes: number, tile_count = 1): ExportEstimate {
  return {
    exact: true,
    raw_bytes,
    tile_count,
    transition_tile_count: 0,
    transition_raw_bytes: 0,
    zooms: [],
  };
}

describe("desktop export recommendation", () => {
  it("recommends desktop for large byte estimates or very large tile counts", () => {
    expect(shouldRecommendDesktop(estimate(DESKTOP_RECOMMENDATION_BYTES))).toBe(true);
    expect(shouldRecommendDesktop(estimate(1, 50_000))).toBe(true);
    expect(shouldRecommendDesktop(estimate(32 * 1024 * 1024, 2_000))).toBe(false);
  });

  it("chooses the matching release artifact", () => {
    expect(desktopPlatform("Mozilla/5.0 (Windows NT 10.0; Win64; x64)")).toBe("windows");
    expect(desktopPlatform("Mozilla/5.0 (Macintosh; Intel Mac OS X)")).toBe("macos");
    expect(desktopPlatform("Mozilla/5.0 (X11; Linux x86_64)")).toBe("linux");
    expect(desktopDownloadUrl("windows")).toMatch(/EinkMapTiles-electron-windows\.zip$/);
  });
});
