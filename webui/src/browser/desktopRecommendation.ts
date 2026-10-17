import type { ExportEstimate } from "../models";

export const DESKTOP_RECOMMENDATION_BYTES = 512 * 1024 * 1024;
export const DESKTOP_RECOMMENDATION_TILES = 50_000;

export type DesktopPlatform = "windows" | "macos" | "linux";

export function shouldRecommendDesktop(estimate: ExportEstimate | null): boolean {
  return Boolean(
    estimate &&
    (estimate.raw_bytes >= DESKTOP_RECOMMENDATION_BYTES ||
      estimate.tile_count >= DESKTOP_RECOMMENDATION_TILES),
  );
}

export function desktopPlatform(userAgent: string): DesktopPlatform {
  if (/windows/i.test(userAgent)) return "windows";
  if (/macintosh|mac os/i.test(userAgent)) return "macos";
  return "linux";
}

export function desktopDownloadUrl(platform: DesktopPlatform): string {
  return `https://github.com/HarukiToreda/E-ink-Map-Tiles/releases/latest/download/EinkMapTiles-electron-${platform}.zip`;
}
