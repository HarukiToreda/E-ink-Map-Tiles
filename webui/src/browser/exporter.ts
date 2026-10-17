import { strToU8, zipSync } from "fflate";
import type { ExportJob, ExportKind, ProjectSession } from "../models";
import { ConversionWorkerClient } from "./conversionWorkerClient";
import { formatBytes } from "./format";
import { mapAttributionText, muiStyleName } from "./mapConfig";
import { renderCacheNamespace, renderTilePixels } from "./mapRenderer";
import {
  buildSparseMtbBinary,
  buildSparseMtbHeader,
  compressLz4Block,
  downloadBlob,
  type PackedTile,
} from "./mtb";
import { encodeMuiIndexedPng } from "./muiPng";
import { buildRasterPmtiles } from "./pmtilesWriter";
import { rawBytesPerTile, type TileCoordinate } from "./tiles";
import type { TilePlanRequest, TilePlanResponse } from "./workerProtocol";

type Progress = (job: ExportJob) => void;

interface BrowserExportRequest {
  session: ProjectSession;
  projectId: string;
  renderRevision: number;
  kind: ExportKind;
  signal: AbortSignal;
  progress: Progress;
  plannedTiles?: TileCoordinate[];
}

function makeJob(id: string, kind: ExportKind, sessionId: string, total: number): ExportJob {
  return {
    job_id: id,
    project_id: sessionId,
    kind,
    status: "running",
    completed: 0,
    total,
    message: "Preparing browser export…",
    error: null,
    artifact_size_bytes: null,
    compression_ratio: null,
    logs: [],
  };
}

function jobSnapshot(job: ExportJob): ExportJob {
  return { ...job, logs: [...job.logs] };
}

function blobPart(bytes: Uint8Array): BlobPart {
  // These writers always allocate ordinary ArrayBuffers. Keep that knowledge at
  // this browser API boundary instead of copying large completed artifacts.
  return bytes as Uint8Array<ArrayBuffer>;
}

function copyArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength);
  copy.set(bytes);
  return copy.buffer;
}

function uniformKind(bytes: Uint8Array): number {
  let white = true,
    black = true;
  for (const byte of bytes) {
    white &&= byte === 0xff;
    black &&= byte === 0;
    if (!white && !black) return 0;
  }
  return white ? 1 : black ? 2 : 0;
}

function planTiles(session: ProjectSession, signal: AbortSignal): Promise<TileCoordinate[]> {
  const worker = new Worker(new URL("./tilePlan.worker.ts", import.meta.url), { type: "module" });
  return new Promise((resolve, reject) => {
    const abort = () => {
      worker.terminate();
      reject(new DOMException("Export cancelled", "AbortError"));
    };
    if (signal.aborted) {
      abort();
      return;
    }
    signal.addEventListener("abort", abort, { once: true });
    worker.onmessage = (event: MessageEvent<TilePlanResponse>) => {
      signal.removeEventListener("abort", abort);
      worker.terminate();
      if (event.data.type === "error") reject(new Error(event.data.error));
      else resolve(event.data.tiles);
    };
    worker.onerror = (event) => {
      signal.removeEventListener("abort", abort);
      worker.terminate();
      reject(new Error(event.message || "Tile planning failed"));
    };
    const request: TilePlanRequest = {
      area_selections: session.area_selections,
      smooth_zoom_transitions: session.export.smooth_zoom_transitions,
    };
    worker.postMessage(request);
  });
}

export async function exportInBrowser({
  session,
  projectId,
  renderRevision,
  kind,
  signal,
  progress,
  plannedTiles,
}: BrowserExportRequest): Promise<ExportJob> {
  if (["normal-zip", "mui-pmtiles"].includes(kind) && session.render.mode !== "original")
    throw new Error("MUI tiles require None (full color) E-ink conversion");
  if (!session.export.attribution_acknowledged && ["normal-zip", "mui-pmtiles"].includes(kind))
    throw new Error("Map attribution must be retained before downloading MUI tiles");
  const id = crypto.randomUUID(),
    job = makeJob(id, kind, projectId, 0);
  const muiStyleDirectory = `maps/${muiStyleName(session.render.style)}`;
  job.message = plannedTiles ? "Loading calculated tiles…" : "Planning selected tiles…";
  progress(jobSnapshot(job));
  let tiles: TileCoordinate[];
  try {
    tiles = plannedTiles ?? (await planTiles(session, signal));
  } catch (error) {
    Object.assign(job, {
      status: signal.aborted ? "cancelled" : "failed",
      message: signal.aborted ? "Export cancelled" : "Tile planning failed",
      error: signal.aborted ? null : error instanceof Error ? error.message : String(error),
    });
    progress(jobSnapshot(job));
    return job;
  }
  if (!tiles.length) {
    Object.assign(job, {
      status: "failed",
      message: "Tile planning failed",
      error: "Add or enable at least one selection before downloading map tiles",
    });
    progress(jobSnapshot(job));
    return job;
  }
  const bytesPerTile = rawBytesPerTile(session),
    zoomCounts = new Map<number, number>();
  for (const tile of tiles) zoomCounts.set(tile.z, (zoomCounts.get(tile.z) ?? 0) + 1);
  const planLogs = [...zoomCounts]
    .sort(([left], [right]) => left - right)
    .map(
      ([zoom, count]) =>
        `z${zoom}: ${count.toLocaleString()} tiles · ${formatBytes(count * bytesPerTile)} raw`,
    );
  Object.assign(job, {
    total: tiles.length,
    message: `Planned ${tiles.length.toLocaleString()} tiles · ${formatBytes(tiles.length * bytesPerTile)} raw`,
    logs: planLogs,
  });
  progress(jobSnapshot(job));
  const cacheNamespace = renderCacheNamespace(projectId, renderRevision),
    converter = new ConversionWorkerClient(),
    packed: Array<PackedTile | undefined> = new Array(tiles.length);
  const desktop = window.einkMapDesktop,
    desktopZip =
      kind === "normal-zip" && desktop?.streamingExportKinds.includes("normal-zip")
        ? desktop
        : undefined;
  const desktopFile =
    kind !== "normal-zip" && desktop?.streamingExportKinds.includes(kind) ? desktop : undefined;
  let desktopZipJob: string | null = null,
    desktopZipFinished = false,
    desktopFileJob: string | null = null,
    desktopFileFinished = false;
  const zipFiles: Record<string, Uint8Array> = {},
    pmtilesTiles: Array<{ tile: TileCoordinate; data: Uint8Array }> = [];
  try {
    if (desktopZip) {
      desktopZipJob = await desktopZip.startZip("MUI-Tiles.zip");
      if (!desktopZipJob) {
        Object.assign(job, { status: "cancelled", message: "Export cancelled" });
        progress(jobSnapshot(job));
        return job;
      }
    }
    if (desktopFile) {
      const styleName = muiStyleDirectory.slice("maps/".length);
      const names: Record<ExportKind, string> = {
        "normal-zip": "MUI-Tiles.zip",
        "mui-pmtiles": `${styleName}.pmtiles`,
        "inkhud-header": "MapTile.h",
        "inkhud-binary": "MapTile.bin",
      };
      desktopFileJob = await desktopFile.startExport(kind, names[kind], {
        depth: session.inkhud.tile_depth,
        style: session.render.style,
        styleName,
        attribution: mapAttributionText(session),
      });
      if (!desktopFileJob) {
        Object.assign(job, { status: "cancelled", message: "Export cancelled" });
        progress(jobSnapshot(job));
        return job;
      }
    }
    let nextIndex = 0,
      completed = 0,
      lastProgressAt = 0;
    const publishRenderProgress = (force = false) => {
      const now = performance.now();
      if (!force && now - lastProgressAt < 100) return;
      lastProgressAt = now;
      progress(jobSnapshot(job));
    };
    const renderNext = async () => {
      while (true) {
        const index = nextIndex++;
        if (index >= tiles.length) return;
        if (signal.aborted) throw new DOMException("Export cancelled", "AbortError");
        const tile = tiles[index],
          pixels = await renderTilePixels(session, tile, cacheNamespace, signal);
        if (signal.aborted) throw new DOMException("Export cancelled", "AbortError");
        if (kind === "normal-zip" || kind === "mui-pmtiles") {
          const png = encodeMuiIndexedPng(pixels);
          if (kind === "normal-zip") {
            const entryName = `${muiStyleDirectory}/${tile.z}/${tile.x}/${tile.y}.png`;
            if (desktopZipJob)
              await desktopZip!.writeZipEntry(desktopZipJob, entryName, copyArrayBuffer(png));
            else zipFiles[entryName] = png;
          } else if (desktopFileJob)
            await desktopFile!.writeExportTile(desktopFileJob, tile, copyArrayBuffer(png));
          else pmtilesTiles[index] = { tile, data: png };
        } else {
          const converted = await converter.convert(pixels, session.inkhud.tile_depth, true);
          if (desktopFileJob) {
            const payloadKind = uniformKind(converted),
              payload = payloadKind ? new Uint8Array() : compressLz4Block(converted);
            await desktopFile!.writeExportTile(
              desktopFileJob,
              tile,
              copyArrayBuffer(payload),
              payloadKind,
            );
          } else packed[index] = { ...tile, pixels: converted };
        }
        completed++;
        Object.assign(job, { completed, message: `Rendered ${tile.z}/${tile.x}/${tile.y}` });
        job.logs.push(job.message);
        if (job.logs.length > 100) job.logs.splice(0, job.logs.length - 100);
        publishRenderProgress(completed === tiles.length);
      }
    };
    await Promise.all(Array.from({ length: Math.min(4, tiles.length) }, renderNext));
    const packedTiles = packed.filter((tile): tile is PackedTile => Boolean(tile));
    let artifact: Blob, name: string;
    if (desktopFileJob) {
      const saved = await desktopFile!.finishExport(desktopFileJob);
      desktopFileFinished = true;
      Object.assign(job, {
        status: "completed",
        message: `Saved export to ${saved.path}`,
        artifact_size_bytes: saved.size,
        compression_ratio: saved.size / Math.max(1, tiles.length * bytesPerTile),
      });
      progress(jobSnapshot(job));
      return job;
    }
    if (kind === "normal-zip") {
      const bounds = session.area_selections
        .filter((item) => item.enabled)
        .map((item) => item.bbox);
      const manifest = {
        created_utc: new Date().toISOString(),
        layout: "xyz",
        layout_path: `/${muiStyleDirectory}`,
        style: session.render.style,
        bbox: bounds.length
          ? {
              west: Math.min(...bounds.map((item) => item.west)),
              south: Math.min(...bounds.map((item) => item.south)),
              east: Math.max(...bounds.map((item) => item.east)),
              north: Math.max(...bounds.map((item) => item.north)),
            }
          : null,
        zooms: [...new Set(tiles.map((tile) => tile.z))],
        tile_count: tiles.length,
        source: session.render.source,
        mode: session.render.mode,
        bit_depth: session.render.mode === "original" ? null : session.inkhud.tile_depth,
        topography: session.render.style === "osm-eink-topo",
        elements: { include: session.render.elements },
        smooth_zoom_transitions: session.export.smooth_zoom_transitions,
      };
      name = "MUI-Tiles.zip";
      const manifestBytes = strToU8(`${JSON.stringify(manifest, null, 2)}\n`),
        attributionBytes = strToU8(mapAttributionText(session));
      if (desktopZipJob) {
        await desktopZip!.writeZipEntry(
          desktopZipJob,
          `${muiStyleDirectory}/manifest.json`,
          copyArrayBuffer(manifestBytes),
        );
        await desktopZip!.writeZipEntry(
          desktopZipJob,
          `${muiStyleDirectory}/ATTRIBUTION.txt`,
          copyArrayBuffer(attributionBytes),
        );
        const saved = await desktopZip!.finishZip(desktopZipJob);
        desktopZipFinished = true;
        Object.assign(job, {
          status: "completed",
          message: `Saved ${name} to ${saved.path}`,
          artifact_size_bytes: saved.size,
          compression_ratio: saved.size / Math.max(1, tiles.length * bytesPerTile),
        });
        progress(jobSnapshot(job));
        return job;
      }
      zipFiles[`${muiStyleDirectory}/manifest.json`] = manifestBytes;
      zipFiles[`${muiStyleDirectory}/ATTRIBUTION.txt`] = attributionBytes;
      artifact = new Blob([blobPart(zipSync(zipFiles, { level: 6 }))], {
        type: "application/zip",
      });
    } else if (kind === "mui-pmtiles") {
      const styleName = muiStyleDirectory.slice("maps/".length);
      artifact = new Blob(
        [blobPart(buildRasterPmtiles(pmtilesTiles, styleName, mapAttributionText(session)))],
        { type: "application/vnd.pmtiles" },
      );
      name = `${styleName}.pmtiles`;
    } else if (kind === "inkhud-header") {
      artifact = new Blob(
        [buildSparseMtbHeader(packedTiles, session.inkhud.tile_depth, session.render.style)],
        { type: "text/x-c" },
      );
      name = "MapTile.h";
    } else {
      artifact = new Blob(
        [blobPart(buildSparseMtbBinary(packedTiles, session.inkhud.tile_depth))],
        { type: "application/octet-stream" },
      );
      name = "MapTile.bin";
    }
    downloadBlob(name, artifact);
    Object.assign(job, {
      status: "completed",
      message: `Downloaded ${name}`,
      artifact_size_bytes: artifact.size,
      compression_ratio: artifact.size / Math.max(1, tiles.length * bytesPerTile),
    });
    progress(jobSnapshot(job));
    return job;
  } catch (error) {
    Object.assign(job, {
      status: signal.aborted ? "cancelled" : "failed",
      message: signal.aborted ? "Export cancelled" : "Export failed",
      error: signal.aborted ? null : error instanceof Error ? error.message : String(error),
    });
    progress(jobSnapshot(job));
    return job;
  } finally {
    if (desktopZipJob && !desktopZipFinished)
      await desktopZip?.abortZip(desktopZipJob).catch(() => {});
    if (desktopFileJob && !desktopFileFinished)
      await desktopFile?.abortExport(desktopFileJob).catch(() => {});
    converter.destroy();
  }
}
