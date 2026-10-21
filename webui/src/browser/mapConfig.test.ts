import { describe, expect, it } from "vitest";
import { defaultSession } from "./session";
import { mapAttributions, mapAttributionText, muiStyleName } from "./mapConfig";

describe("map source configuration", () => {
  it("uses the same attribution entries for UI and exported text", () => {
    const session = defaultSession();
    session.render.style = "osm-eink-topo";

    const entries = mapAttributions(session);
    const text = mapAttributionText(session);

    for (const entry of entries) {
      expect(text).toContain(entry.label);
      expect(text).toContain(entry.url);
    }
    expect(entries.some((entry) => entry.label.includes("Mapzen"))).toBe(true);
  });

  it("maps each browser style to its MUI directory", () => {
    expect(muiStyleName("osm-eink")).toBe("liberty");
    expect(muiStyleName("osm-eink-topo")).toBe("liberty-topo");
  });
});
