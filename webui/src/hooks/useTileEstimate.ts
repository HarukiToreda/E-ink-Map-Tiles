import { useEffect, useMemo, useState } from "react";
import type { ProjectSession } from "../models";
import { loadTilePlanEntries, saveTilePlanEntries } from "../browser/storage";
import {
  estimateBrowserExportFast,
  selectionZoomCacheIdentity,
  summarizeTiles,
  type TileCoordinate,
  type TileCoverageSession,
  type TileEstimateProgress,
  type TileFormatSession,
} from "../browser/tiles";
import type { EstimateRequest, EstimateResponse } from "../browser/workerProtocol";

interface CalculationState {
  key: string;
  tiles: TileCoordinate[] | null;
  error: string | null;
  progress: TileEstimateProgress | null;
}

interface CoverageSnapshot {
  key: string;
  coverage: TileCoverageSession;
}

const geometryIds = new WeakMap<object, number>();
const coverageCache = new Map<string, TileCoverageSession>();
let nextGeometryId = 1;

function geometryId(geometry: object | null): number | null {
  if (!geometry) return null;
  const existing = geometryIds.get(geometry);
  if (existing) return existing;
  const id = nextGeometryId++;
  geometryIds.set(geometry, id);
  return id;
}

function coverageSnapshot(session: ProjectSession): CoverageSnapshot {
  const area_selections = session.area_selections.map(
    ({ selection_id, enabled, min_zoom, max_zoom, bbox, exact, geojson }) => ({
      selection_id,
      enabled,
      min_zoom,
      max_zoom,
      bbox,
      exact,
      geojson,
    }),
  );
  const smooth_zoom_transitions = session.export.smooth_zoom_transitions;
  const key = JSON.stringify({
    smooth_zoom_transitions,
    area_selections: area_selections.map(({ geojson, ...selection }) => ({
      ...selection,
      geometry_id: geometryId(geojson),
    })),
  });
  return { key, coverage: { area_selections, smooth_zoom_transitions } };
}

function stableCoverage(snapshot: CoverageSnapshot | null): TileCoverageSession | null {
  if (!snapshot) return null;
  const existing = coverageCache.get(snapshot.key);
  if (existing) return existing;
  coverageCache.set(snapshot.key, snapshot.coverage);
  while (coverageCache.size > 8) {
    const oldestKey = coverageCache.keys().next().value;
    if (oldestKey === undefined) break;
    coverageCache.delete(oldestKey);
  }
  return snapshot.coverage;
}

export function useTileEstimate(session: ProjectSession | null) {
  const nextCoverage = session ? coverageSnapshot(session) : null;
  const key = nextCoverage?.key ?? "";
  const coverage = stableCoverage(nextCoverage);
  const mode = session?.render.mode;
  const tileDepth = session?.inkhud.tile_depth;
  const format = useMemo<TileFormatSession | null>(
    () => (mode && tileDepth ? { render: { mode }, inkhud: { tile_depth: tileDepth } } : null),
    [mode, tileDepth],
  );
  const fastEstimate = useMemo(
    () => (coverage && format ? estimateBrowserExportFast({ ...coverage, ...format }) : null),
    [coverage, format],
  );
  const [calculation, setCalculation] = useState<CalculationState>({
    key: "",
    tiles: null,
    error: null,
    progress: null,
  });

  useEffect(() => {
    if (!coverage) return;
    let active = true;
    const worker = new Worker(new URL("../browser/estimate.worker.ts", import.meta.url), {
      type: "module",
    });

    worker.onmessage = (event: MessageEvent<EstimateResponse>) => {
      if (!active) return;
      if (event.data.type === "error") {
        setCalculation({
          key,
          tiles: null,
          error: event.data.error,
          progress: null,
        });
        worker.terminate();
      } else if (event.data.type === "progress") {
        const progress = event.data.progress;
        setCalculation((current) => ({
          key,
          tiles: current.key === key ? current.tiles : null,
          error: null,
          progress,
        }));
      } else {
        setCalculation({
          key,
          tiles: event.data.tiles,
          error: null,
          progress: null,
        });
        if (event.data.cacheWrites.length) {
          void saveTilePlanEntries(event.data.cacheWrites).catch(() => undefined);
        }
        worker.terminate();
      }
    };
    worker.onerror = (event) => {
      if (active) {
        setCalculation({
          key,
          tiles: null,
          error: event.message || "Tile calculation failed",
          progress: null,
        });
      }
      worker.terminate();
    };

    const timer = window.setTimeout(() => {
      const identities = coverage.area_selections
        .filter((selection) => selection.enabled)
        .flatMap((selection) =>
          Array.from({ length: selection.max_zoom - selection.min_zoom + 1 }, (_, offset) =>
            selectionZoomCacheIdentity(selection, selection.min_zoom + offset),
          ),
        );
      void loadTilePlanEntries(identities)
        .then((cached) => {
          if (active) {
            const request: EstimateRequest = { session: coverage, cached };
            worker.postMessage(request);
          }
        })
        .catch(() => {
          if (active) {
            const request: EstimateRequest = { session: coverage, cached: {} };
            worker.postMessage(request);
          }
        });
    }, 180);

    return () => {
      active = false;
      window.clearTimeout(timer);
      worker.terminate();
    };
  }, [coverage, key]);

  const current = calculation.key === key ? calculation : null;
  const exactTiles = current?.tiles ?? null;
  const exactEstimate = useMemo(
    () => (exactTiles && format ? summarizeTiles(exactTiles, format, true) : null),
    [exactTiles, format],
  );
  return {
    key,
    estimate: exactEstimate ?? fastEstimate,
    exactTiles,
    error: current?.error ?? null,
    progress: current?.progress ?? null,
  };
}
