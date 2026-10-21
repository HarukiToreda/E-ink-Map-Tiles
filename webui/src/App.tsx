import { useCallback, useRef, useState } from "react";
import "./app.css";
import { BrowserMap, type FitRequest } from "./BrowserMap";
import { errorMessage } from "./browser/format";
import { geoJsonBounds, isJsonObject, selectionGeometry } from "./browser/geojson";
import { sourceMaxZoom, zoomLabel } from "./browser/mapConfig";
import { boundsCenter, MAX_DISPLAY_ZOOM } from "./browser/mercator";
import { exportInBrowser } from "./browser/exporter";
import {
  resolveBrowserLocationBoundary,
  searchBrowserLocations,
  searchResultKey,
} from "./browser/search";
import { resetBrowserData } from "./browser/storage";
import { Sidebar } from "./components/Sidebar";
import { LocationSearch } from "./components/LocationSearch";
import { useProject } from "./hooks/useProject";
import { useTileEstimate } from "./hooks/useTileEstimate";
import type {
  AreaSelection,
  ExportJob,
  ExportKind,
  MapBounds,
  Marker,
  SearchResult,
} from "./models";

function sameBounds(left: MapBounds, right: MapBounds): boolean {
  return (
    left.west === right.west &&
    left.south === right.south &&
    left.east === right.east &&
    left.north === right.north
  );
}

export default function App() {
  const [error, setError] = useState<string | null>(null);
  const reportError = useCallback((message: string) => setError(message), []);
  const { project, projectRef, saving, save, saveRender, saveChainRef, updateView, importSession } =
    useProject(reportError);
  const tileEstimate = useTileEstimate(project?.session ?? null);

  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [resolvingBoundary, setResolvingBoundary] = useState<string | null>(null);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [exportJob, setExportJob] = useState<ExportJob | null>(null);
  const [placement, setPlacement] = useState<Marker | null>(null);
  const [selectedMarkerId, setSelectedMarkerId] = useState<string | null>(null);
  const [fitRequest, setFitRequest] = useState<FitRequest | null>(null);
  const fitRequestId = useRef(0);
  const searchRequestId = useRef(0);
  const exportController = useRef<AbortController | null>(null);
  const dismissSearchResults = useCallback(() => setSearchResults([]), []);

  const fitBounds = useCallback((bounds: AreaSelection["bbox"]) => {
    fitRequestId.current += 1;
    setFitRequest({ bounds, requestId: fitRequestId.current });
  }, []);

  const startExport = async (kind: ExportKind) => {
    if (!project) return;
    setError(null);
    const controller = new AbortController();
    exportController.current = controller;
    try {
      const result = await exportInBrowser({
        session: project.session,
        projectId: project.project_id,
        renderRevision: project.render_revision,
        kind,
        signal: controller.signal,
        progress: setExportJob,
        plannedTiles: tileEstimate.exactTiles ?? undefined,
      });
      setExportJob(result);
      if (result.error) setError(result.error);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      if (exportController.current === controller) exportController.current = null;
    }
  };

  const submitSearch = async () => {
    const query = searchQuery.trim();
    if (query.length < 2 || !project) return;
    const requestId = ++searchRequestId.current;
    setSearching(true);
    setError(null);
    try {
      const results = (await searchBrowserLocations(query)).results;
      if (searchRequestId.current !== requestId) return;
      setSearchResults(results);
      if (!results.length) setError("No matching location found");
    } catch (reason) {
      if (searchRequestId.current === requestId) setError(errorMessage(reason));
    } finally {
      if (searchRequestId.current === requestId) setSearching(false);
    }
  };

  const chooseSearchResult = (result: SearchResult) => {
    setSearchResults([]);
    setSearchQuery(result.display_name);
    void save((session) => {
      session.map_revealed = true;
      session.view.center_lat = result.lat;
      session.view.center_lon = result.lon;
    });
    if (result.bbox) fitBounds(result.bbox);
  };

  const addSearchSelection = async (searchResult: SearchResult) => {
    setResolvingBoundary(searchResultKey(searchResult));
    setError(null);
    let result = searchResult;
    try {
      result = await resolveBrowserLocationBoundary(searchResult);
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setResolvingBoundary(null);
    }

    if (!result.bbox) {
      setError("This search result has no area boundary or bounding box to select");
      return;
    }
    const bbox = result.bbox;
    const geometryType = result.geojson?.type;
    const exact = geometryType === "Polygon" || geometryType === "MultiPolygon";
    await save((session) => {
      const center = boundsCenter(bbox);
      session.map_revealed = true;
      session.view.center_lat = center.lat;
      session.view.center_lon = center.lon;

      const existing = session.area_selections.find(
        (selection) => selection.name === result.display_name && sameBounds(selection.bbox, bbox),
      );
      if (existing) {
        if (exact && !existing.exact) {
          existing.exact = true;
          existing.geojson = result.geojson;
        }
        return;
      }
      session.area_selections.push({
        selection_id: crypto.randomUUID(),
        name: result.display_name,
        enabled: true,
        exact,
        bbox,
        geojson: exact ? result.geojson : null,
        min_zoom: 0,
        max_zoom: Math.min(12, sourceMaxZoom(session.render.source)),
      });
    });
    fitBounds(bbox);
    setSearchResults([]);
    setSearchQuery(result.display_name);
  };

  const importGeoJson = async (files: File[]) => {
    setError(null);
    try {
      await saveChainRef.current;
      const layers = await Promise.all(
        files.map(async (file) => {
          const geojson: unknown = JSON.parse(await file.text());
          if (!isJsonObject(geojson) || !geoJsonBounds(geojson))
            throw new Error(`${file.name} has no valid coordinates`);
          return {
            layer_id: crypto.randomUUID(),
            name: file.name.replace(/\.(geo)?json$/i, ""),
            geojson,
            visible: true,
            min_zoom: 0,
            max_zoom: MAX_DISPLAY_ZOOM,
          };
        }),
      );
      await saveRender((session) => session.geojson_layers.push(...layers));
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  const fitGeoJson = () => {
    const visibleLayers =
      projectRef.current?.session.geojson_layers
        .filter((layer) => layer.visible)
        .map((layer) => layer.geojson) ?? [];
    const bounds = geoJsonBounds(visibleLayers);
    if (bounds) fitBounds(bounds);
  };

  const selectGeoJson = () => {
    void save((session) => {
      for (const layer of session.geojson_layers.filter((item) => item.visible)) {
        const bbox = geoJsonBounds(layer.geojson);
        const geojson = selectionGeometry(layer.geojson);
        if (!bbox || !geojson) continue;
        const existing = session.area_selections.find(
          (selection) => selection.source_layer_id === layer.layer_id,
        );
        const selection: AreaSelection = {
          selection_id: existing?.selection_id ?? crypto.randomUUID(),
          source_layer_id: layer.layer_id,
          name: layer.name,
          enabled: true,
          exact: true,
          bbox,
          geojson,
          min_zoom: layer.min_zoom,
          max_zoom: layer.max_zoom,
        };
        if (existing) Object.assign(existing, selection);
        else session.area_selections.push(selection);
      }
    });
  };

  const resetApplication = async () => {
    if (
      !window.confirm(
        "Clear all saved projects, settings, selections, and cached map data? This cannot be undone.",
      )
    ) {
      return;
    }
    exportController.current?.abort();
    try {
      // Let queued writes close their database connections before deleting it.
      await saveChainRef.current;
      await resetBrowserData();
      window.location.reload();
    } catch (reason) {
      setError(errorMessage(reason));
    }
  };

  return (
    <main className="app-shell">
      <aside className="sidebar" aria-label="Map controls">
        <header className="brand">
          <span className="brand-mark" aria-hidden="true">
            🗺️
          </span>
          <div>
            <h1>E-ink Map Tiles</h1>
            <p>Offline map export studio</p>
          </div>
          <button
            className="reset-app"
            onClick={() => void resetApplication()}
            title="Clear all local app data"
          >
            Reset
          </button>
        </header>

        <Sidebar
          project={project}
          save={(mutate) => void save(mutate)}
          saveRender={(mutate) => void saveRender(mutate)}
          onImportSession={(file) => {
            setError(null);
            void importSession(file);
          }}
          onGeoJsonFiles={(files) => void importGeoJson(files)}
          estimate={tileEstimate.estimate}
          estimateError={tileEstimate.error}
          estimateProgress={tileEstimate.progress}
          exportJob={exportJob}
          onStartExport={(kind) => void startExport(kind)}
          onCancelExport={() => exportController.current?.abort()}
          placement={placement}
          setPlacement={setPlacement}
          selectedMarkerId={selectedMarkerId}
          setSelectedMarkerId={setSelectedMarkerId}
          fitGeoJson={fitGeoJson}
          selectGeoJson={selectGeoJson}
          fitSelection={(selection) => fitBounds(selection.bbox)}
        />
      </aside>

      <section className="workspace" aria-label="Map workspace">
        <div className="toolbar">
          <LocationSearch
            query={searchQuery}
            searching={searching}
            results={searchResults}
            resolvingResult={resolvingBoundary}
            onQueryChange={(query) => {
              searchRequestId.current += 1;
              setSearching(false);
              setSearchQuery(query);
              dismissSearchResults();
            }}
            onSubmit={() => void submitSearch()}
            onDismiss={dismissSearchResults}
            onView={chooseSearchResult}
            onAdd={(result) => void addSearchSelection(result)}
          />
          <span
            role="status"
            aria-live="polite"
            className={`connection zoom-indicator ${error ? "error" : project ? "ready" : "loading"}`}
          >
            {error
              ? error
              : project
                ? `Zoom ${zoomLabel(project.session.view.zoom, project.session.render.source)}${saving ? " · Saving…" : ""}`
                : "Loading…"}
          </span>
        </div>

        <div className="map-region">
          {project?.session.map_revealed ? (
            <BrowserMap
              project={project}
              fitRequest={fitRequest}
              placement={placement}
              selectedMarkerId={selectedMarkerId}
              onView={updateView}
              onPlace={(lat, lon) => {
                if (!placement) return;
                void saveRender((session) => session.markers.push({ ...placement, lat, lon }));
                setPlacement(null);
              }}
              onSelectMarker={setSelectedMarkerId}
              onError={reportError}
              onMoveMarker={(markerId, lat, lon) => {
                void saveRender((session) => {
                  const marker = session.markers.find((item) => item.marker_id === markerId);
                  if (marker) Object.assign(marker, { lat, lon });
                });
              }}
            />
          ) : (
            <div className="map-placeholder">
              <strong>
                {error
                  ? "Map unavailable"
                  : project
                    ? "Search for a place to begin"
                    : "Preparing map…"}
              </strong>
              {project && !error && (
                <div className="github-plug">
                  <span>Build beautiful offline maps for e-ink devices.</span>
                  <a
                    href="https://github.com/HarukiToreda/E-ink-Map-Tiles"
                    target="_blank"
                    rel="noreferrer"
                  >
                    <span aria-hidden="true">★</span> View E-ink Map Tiles on GitHub
                  </a>
                </div>
              )}
            </div>
          )}
          {project?.session.map_revealed && <div className="target" aria-hidden="true" />}
        </div>
      </section>
    </main>
  );
}
