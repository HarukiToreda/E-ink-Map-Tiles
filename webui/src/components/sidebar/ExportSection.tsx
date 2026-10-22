import { useEffect, useRef } from "react";
import {
  desktopDownloadUrl,
  desktopPlatform,
  shouldRecommendDesktop,
} from "../../browser/desktopRecommendation";
import { formatBytes } from "../../browser/format";
import { muiStyleName, zoomLabel } from "../../browser/mapConfig";
import { downloadBlob } from "../../browser/mtb";
import type { TileEstimateProgress } from "../../browser/tiles";
import type { ExportEstimate, ExportJob, ExportKind, ProjectSession } from "../../models";

interface ExportSectionProps {
  session: ProjectSession;
  estimate: ExportEstimate | null;
  estimateError: string | null;
  estimateProgress: TileEstimateProgress | null;
  exportJob: ExportJob | null;
  onStartExport: (kind: ExportKind) => void;
  onCancelExport: () => void;
  onImportSession: (file: File) => void;
}

function ExportLog({ logs }: { logs: string[] }) {
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const logRef = useRef<HTMLPreElement | null>(null);
  const scrollToLatest = () => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  };

  useEffect(() => {
    if (detailsRef.current?.open) scrollToLatest();
  }, [logs]);

  return (
    <details
      ref={detailsRef}
      onToggle={(event) => {
        if (event.currentTarget.open) requestAnimationFrame(scrollToLatest);
      }}
    >
      <summary>Export log</summary>
      <pre ref={logRef}>{logs.join("\n")}</pre>
    </details>
  );
}

export function ExportSection({
  session,
  estimate,
  estimateError,
  estimateProgress,
  exportJob,
  onStartExport,
  onCancelExport,
  onImportSession,
}: ExportSectionProps) {
  const exportIdle = !exportJob || ["completed", "cancelled", "failed"].includes(exportJob.status);
  const styleDirectory = muiStyleName(session.render.style);
  const recommendDesktop = !window.einkMapDesktop && shouldRecommendDesktop(estimate);
  const platform = desktopPlatform(navigator.userAgent);
  const platformLabel = { windows: "Windows", macos: "macOS", linux: "Linux" }[platform];
  return (
    <details className="export-section">
      <summary>Export</summary>
      <div className="section-body">
        {session.render.mode !== "original" && session.inkhud.tile_depth > 1 && (
          <p className="section-note">
            Requires firmware support for {session.inkhud.tile_depth}-bit map tiles.
          </p>
        )}
        <p className="section-note">
          {estimate
            ? `${estimate.exact ? "" : "About "}${estimate.tile_count.toLocaleString()} tiles · ${formatBytes(estimate.raw_bytes)} raw tile data total`
            : "No tiles selected"}
        </p>
        {estimate?.exact && estimate.transition_tile_count > 0 && (
          <p className="section-note">
            Smooth transitions added {estimate.transition_tile_count.toLocaleString()} tiles ·{" "}
            {formatBytes(estimate.transition_raw_bytes)} raw
          </p>
        )}
        {!estimate?.exact && estimateProgress && estimateProgress.total > 0 && (
          <div className="estimate-progress">
            <strong>Calculating tiles…</strong>
            <progress max={estimateProgress.total} value={estimateProgress.completed} />
            <span>{Math.floor((estimateProgress.completed / estimateProgress.total) * 100)}%</span>
          </div>
        )}
        {estimate && (
          <div className="zoom-size-list">
            {estimate.zooms.map((item) => (
              <div key={item.zoom}>
                <span>{zoomLabel(item.zoom, session.render.source)}</span>
                <span>
                  {estimate.exact ? "" : "≈ "}
                  {item.tile_count.toLocaleString()} tiles
                </span>
                <strong>{formatBytes(item.raw_bytes)}</strong>
              </div>
            ))}
          </div>
        )}
        {estimateError && <p className="section-note error">{estimateError}</p>}
        {recommendDesktop && (
          <aside className="desktop-recommendation" aria-label="Desktop app recommendation">
            <strong>This export may be too large for your browser</strong>
            <span>
              The desktop app streams tiles directly to disk without holding the completed export in
              browser memory. Browser export remains available below.
            </span>
            <a className="button-link" href={desktopDownloadUrl(platform)}>
              Download desktop app for {platformLabel}
            </a>
            <a
              className="desktop-other-downloads"
              href="https://github.com/HarukiToreda/E-ink-Map-Tiles/releases/latest"
              target="_blank"
              rel="noreferrer"
            >
              Other operating systems
            </a>
          </aside>
        )}
        {exportJob && (
          <div className="export-status" aria-live="polite">
            <strong>{exportJob.message}</strong>
            {exportJob.total > 0 && (
              <div className="export-progress">
                <progress max={exportJob.total} value={exportJob.completed} />
                <strong>
                  {Math.max(0, exportJob.total - exportJob.completed).toLocaleString()} tiles
                </strong>
              </div>
            )}
            {exportJob.artifact_size_bytes !== null && (
              <span>
                {formatBytes(exportJob.artifact_size_bytes)}
                {exportJob.compression_ratio !== null
                  ? ` compressed from ${formatBytes(exportJob.artifact_size_bytes / exportJob.compression_ratio)} (${(exportJob.compression_ratio * 100).toFixed(1)}%)`
                  : ""}
              </span>
            )}
            {exportJob.error && <span>{exportJob.error}</span>}
            <ExportLog logs={exportJob.logs} />
          </div>
        )}

        {exportIdle && (
          <div className="export-actions">
            {session.render.mode === "original" ? (
              <>
                <div className="export-action">
                  <button
                    onClick={() => onStartExport("normal-zip")}
                    disabled={!session.export.attribution_acknowledged}
                  >
                    Download MUI Tiles (SD Card)
                  </button>
                  {exportJob?.kind === "normal-zip" && exportJob.status === "completed" && (
                    <div className="file-destination">
                      <span>SD card destination</span>
                      <code>/maps/{styleDirectory}/</code>
                      <small>
                        Extract MUI-Tiles.zip at the SD card root and preserve its folders.
                      </small>
                    </div>
                  )}
                </div>
                <div className="export-action">
                  <button
                    onClick={() => onStartExport("mui-pmtiles")}
                    disabled={!session.export.attribution_acknowledged}
                  >
                    MUI PMTiles (SD Card)
                  </button>
                  {exportJob?.kind === "mui-pmtiles" && exportJob.status === "completed" && (
                    <div className="file-destination">
                      <span>SD card destination</span>
                      <code>
                        /maps/{styleDirectory}/{styleDirectory}.pmtiles
                      </code>
                      <small>Copy the downloaded file to this exact path.</small>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <>
                <div className="export-action">
                  <button onClick={() => onStartExport("inkhud-header")}>
                    Download MapTile.h (Headers)
                  </button>
                  {exportJob?.kind === "inkhud-header" && exportJob.status === "completed" && (
                    <div className="file-destination">
                      <span>Firmware source destination</span>
                      <code>src/graphics/niche/InkHUD/Applets/Bases/Map/MapTile.h</code>
                      <small>Rebuild and flash the firmware after replacing this file.</small>
                    </div>
                  )}
                </div>
                <div className="export-action">
                  <button onClick={() => onStartExport("inkhud-binary")}>
                    Download SD Card Bundle (.zip)
                  </button>
                  {exportJob?.kind === "inkhud-binary" && exportJob.status === "completed" && (
                    <div className="file-destination">
                      <span>SD card destination</span>
                      <code>Extract ZIP to SD card root</code>
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        )}
        {exportJob?.status === "running" && <button onClick={onCancelExport}>Cancel export</button>}

        <button
          className="button-link"
          onClick={() =>
            downloadBlob(
              "eink-map-session.json",
              new Blob([JSON.stringify(session, null, 2)], { type: "application/json" }),
            )
          }
        >
          Export Session
        </button>
        <label className="button-link file-button">
          Load Session
          <input
            type="file"
            accept="application/json,.json"
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              if (file) onImportSession(file);
              event.currentTarget.value = "";
            }}
          />
        </label>
      </div>
    </details>
  );
}
