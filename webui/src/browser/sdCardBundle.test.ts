import { describe, expect, it } from "vitest";
import { defaultSession } from "./session";
import { sdCardAttributionText, sdCardLicenseText } from "./sdCardBundle";

describe("SD card bundle notices", () => {
  it("describes the rendered tile set and settings", () => {
    const session = defaultSession();
    session.render.style = "osm-eink-topo";
    session.inkhud.tile_depth = 2;
    const text = sdCardAttributionText(session, [
      { z: 8, x: 1, y: 2 },
      { z: 7, x: 0, y: 1 },
    ]);

    expect(text).toContain("Style: osm-eink-topo");
    expect(text).toContain("E-ink bit depth: 2");
    expect(text).toContain("Tile count: 2");
    expect(text).toContain("Zoom levels: 7, 8");
    expect(text).toContain("Terrain overlay: enabled");
    expect(text).toContain("OpenStreetMap contributors");
    expect(sdCardLicenseText(session)).toContain("Mapzen terrain data");
  });
});
