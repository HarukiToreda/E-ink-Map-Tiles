import type { ExportKind } from "./models";

export {};

declare global {
  interface Window {
    einkMapDesktop?: {
      platform: string;
      streamingExportKinds: ExportKind[];
      startZip(suggestedName: string): Promise<string | null>;
      writeZipEntry(jobId: string, name: string, bytes: ArrayBuffer): Promise<void>;
      finishZip(jobId: string): Promise<{ size: number; path: string }>;
      abortZip(jobId: string): Promise<void>;
      startExport(
        kind: ExportKind,
        suggestedName: string,
        options: Record<string, unknown>,
      ): Promise<string | null>;
      writeExportTile(
        jobId: string,
        tile: { z: number; x: number; y: number },
        bytes: ArrayBuffer,
        payloadKind?: number,
      ): Promise<void>;
      finishExport(jobId: string): Promise<{ size: number; path: string }>;
      abortExport(jobId: string): Promise<void>;
    };
  }
}
