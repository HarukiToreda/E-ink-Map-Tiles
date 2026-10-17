import type { ProjectSession } from "../models";
import type { PixelBuffer } from "./eink";
import { renderNativeTile } from "./nativeRenderer";
import type { TileCoordinate } from "./tiles";

export function renderCacheNamespace(projectId: string, renderRevision: number): string {
  return `${projectId}:${renderRevision}`;
}

export async function renderTilePixels(
  session: ProjectSession,
  tile: TileCoordinate,
  cacheNamespace: string,
  signal?: AbortSignal,
): Promise<PixelBuffer> {
  const canvas = await renderNativeTile(session, tile, cacheNamespace, signal);
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw new Error("Canvas rendering is unavailable");
  const image = context.getImageData(0, 0, canvas.width, canvas.height);
  return { data: image.data, width: canvas.width, height: canvas.height };
}
