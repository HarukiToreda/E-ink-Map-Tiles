import { describe, expect, it } from "vitest";
import { renderExportTiles, renderPreviewTile } from "./renderActivity";

describe("renderer activity coordination", () => {
  it("waits for preview rendering before starting an export", async () => {
    let finishPreview!: () => void;
    const events: string[] = [];
    const preview = renderPreviewTile(
      () =>
        new Promise<void>((resolve) => {
          finishPreview = resolve;
          events.push("preview started");
        }),
    );
    const exporting = renderExportTiles(async () => {
      events.push("export started");
    });

    await Promise.resolve();
    expect(events).toEqual(["preview started"]);
    finishPreview();
    await Promise.all([preview, exporting]);
    expect(events).toEqual(["preview started", "export started"]);
  });

  it("rejects new preview rendering while an export owns the renderer", async () => {
    let finishExport!: () => void;
    const exporting = renderExportTiles(
      () =>
        new Promise<void>((resolve) => {
          finishExport = resolve;
        }),
    );

    await expect(renderPreviewTile(async () => undefined)).rejects.toMatchObject({
      name: "AbortError",
    });
    finishExport();
    await exporting;
  });
});
