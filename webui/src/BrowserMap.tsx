import { useEffect, useRef } from "react";
import type { AreaSelection, MapBounds, Marker, ProjectSnapshot } from "./models";
import { ConversionWorkerClient } from "./browser/conversionWorkerClient";
import { errorMessage } from "./browser/format";
import { isJsonObject } from "./browser/geojson";
import { renderCacheNamespace } from "./browser/mapRenderer";
import { renderPreviewTile } from "./browser/renderActivity";
import {
  boundsCenter,
  lonLatToWorld,
  MAX_DISPLAY_ZOOM,
  type Point,
  TILE_SIZE,
  viewport,
  worldToLonLat,
  zoomToFit,
} from "./browser/mercator";
import { renderNativeTile } from "./browser/nativeRenderer";

export interface FitRequest {
  bounds: MapBounds;
  requestId: number;
}

interface BrowserMapProps {
  project: ProjectSnapshot;
  fitRequest: FitRequest | null;
  placement: Marker | null;
  selectedMarkerId: string | null;
  exporting: boolean;
  onView: (view: ProjectSnapshot["session"]["view"]) => void;
  onPlace: (lat: number, lon: number) => void;
  onSelectMarker: (markerId: string | null) => void;
  onMoveMarker: (markerId: string, lat: number, lon: number) => void;
  onError: (message: string) => void;
}

const geometryIds = new WeakMap<object, number>();
let nextGeometryId = 1;

function geometryId(geometry: object | null): number | null {
  if (!geometry) return null;
  const existing = geometryIds.get(geometry);
  if (existing) return existing;
  const id = nextGeometryId++;
  geometryIds.set(geometry, id);
  return id;
}

function selectionOverlayKey(selections: AreaSelection[]): string {
  return JSON.stringify(
    selections.map(({ selection_id, enabled, exact, bbox, geojson }) => ({
      selection_id,
      enabled,
      exact,
      bbox,
      geometry_id: geometryId(geojson),
    })),
  );
}

function drawSelectionGeometry(
  context: CanvasRenderingContext2D,
  value: unknown,
  project: (lon: number, lat: number) => Point,
): void {
  if (!isJsonObject(value)) return;
  const object = value;
  if (object.type === "FeatureCollection" && Array.isArray(object.features)) {
    object.features.forEach((item) => drawSelectionGeometry(context, item, project));
    return;
  }
  if (object.type === "Feature") {
    drawSelectionGeometry(context, object.geometry, project);
    return;
  }
  if (object.type === "GeometryCollection" && Array.isArray(object.geometries)) {
    object.geometries.forEach((item) => drawSelectionGeometry(context, item, project));
    return;
  }

  const drawRing = (coordinates: unknown) => {
    if (!Array.isArray(coordinates)) return;
    context.beginPath();
    let started = false;
    for (const coordinate of coordinates) {
      if (
        Array.isArray(coordinate) &&
        typeof coordinate[0] === "number" &&
        typeof coordinate[1] === "number"
      ) {
        const point = project(coordinate[0], coordinate[1]);
        if (started) context.lineTo(point.x, point.y);
        else context.moveTo(point.x, point.y);
        started = true;
      }
    }
    if (started) {
      context.closePath();
      context.fill();
      context.stroke();
    }
  };

  if (object.type === "Polygon" && Array.isArray(object.coordinates)) {
    object.coordinates.forEach(drawRing);
  } else if (object.type === "MultiPolygon" && Array.isArray(object.coordinates)) {
    object.coordinates.forEach((polygon) => {
      if (Array.isArray(polygon)) polygon.forEach(drawRing);
    });
  }
}

export function BrowserMap({
  project,
  fitRequest,
  placement,
  selectedMarkerId,
  exporting,
  onView,
  onPlace,
  onSelectMarker,
  onMoveMarker,
  onError,
}: BrowserMapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sessionRef = useRef(project.session);
  const overlayKey = selectionOverlayKey(project.session.area_selections);
  const dragRef = useRef<{
    start: Point;
    moved: boolean;
    markerId: string | null;
  } | null>(null);

  useEffect(() => {
    sessionRef.current = project.session;
  });

  useEffect(() => {
    const container = containerRef.current;
    const output = canvasRef.current;
    if (!container || !output || exporting) return;

    let cancelled = false;
    let sequence = 0;
    const controller = new AbortController();
    const conversionWorker = new ConversionWorkerClient();

    const render = async () => {
      const renderId = ++sequence;
      const width = Math.max(1, Math.round(container.clientWidth));
      const height = Math.max(1, Math.round(container.clientHeight));
      const pixelRatio = Math.max(1, window.devicePixelRatio || 1);
      const outputWidth = Math.round(width * pixelRatio);
      const outputHeight = Math.round(height * pixelRatio);

      if (output.width !== outputWidth) output.width = outputWidth;
      if (output.height !== outputHeight) output.height = outputHeight;
      output.style.width = `${width}px`;
      output.style.height = `${height}px`;

      const buffer = document.createElement("canvas");
      buffer.width = width;
      buffer.height = height;
      const context = buffer.getContext("2d", { willReadFrequently: true });
      if (!context) return;

      context.fillStyle = "#f8f4f0";
      context.fillRect(0, 0, width, height);

      const session = sessionRef.current;
      const frame = viewport(session.view, width, height);
      const tileCount = 2 ** session.view.zoom;
      const visibleTiles: Array<{ z: number; x: number; y: number }> = [];
      for (
        let y = Math.floor(frame.top / TILE_SIZE);
        y <= Math.floor((frame.top + height) / TILE_SIZE);
        y++
      ) {
        if (y < 0 || y >= tileCount) continue;
        for (
          let x = Math.floor(frame.left / TILE_SIZE);
          x <= Math.floor((frame.left + width) / TILE_SIZE);
          x++
        ) {
          if (x >= 0 && x < tileCount) visibleTiles.push({ z: session.view.zoom, x, y });
        }
      }

      const cacheNamespace = renderCacheNamespace(project.project_id, project.render_revision);
      let nextTile = 0;
      const renderNextTile = async () => {
        while (!controller.signal.aborted) {
          const tile = visibleTiles[nextTile++];
          if (!tile) return;
          const image = await renderPreviewTile(() =>
            renderNativeTile(session, tile, cacheNamespace, controller.signal),
          );
          controller.signal.throwIfAborted();
          context.drawImage(
            image,
            Math.round(tile.x * TILE_SIZE - frame.left),
            Math.round(tile.y * TILE_SIZE - frame.top),
          );
        }
      };

      await Promise.all(Array.from({ length: Math.min(4, visibleTiles.length) }, renderNextTile));
      if (cancelled || renderId !== sequence) return;

      const pixels = context.getImageData(0, 0, width, height);
      if (session.render.mode !== "original") {
        const grayscale = await conversionWorker.convert(
          { data: pixels.data, width, height },
          session.inkhud.tile_depth,
          false,
        );
        if (cancelled || renderId !== sequence) return;
        for (let index = 0; index < grayscale.length; index++) {
          const offset = index * 4;
          pixels.data[offset] = grayscale[index];
          pixels.data[offset + 1] = grayscale[index];
          pixels.data[offset + 2] = grayscale[index];
          pixels.data[offset + 3] = 255;
        }
        context.putImageData(pixels, 0, 0);
      }

      // Selection outlines are editor chrome and never enter exported tile pixels.
      context.fillStyle = "rgba(124,58,237,.10)";
      context.strokeStyle = "#7c3aed";
      context.lineWidth = 2;
      context.setLineDash([6, 4]);
      const projectPoint = (lon: number, lat: number) => {
        const point = lonLatToWorld(lon, lat, session.view.zoom);
        return { x: point.x - frame.left, y: point.y - frame.top };
      };
      for (const selection of session.area_selections) {
        if (!selection.enabled) continue;
        if (selection.exact && selection.geojson) {
          drawSelectionGeometry(context, selection.geojson, projectPoint);
        } else {
          const northwest = projectPoint(selection.bbox.west, selection.bbox.north);
          const southeast = projectPoint(selection.bbox.east, selection.bbox.south);
          context.fillRect(
            northwest.x,
            northwest.y,
            southeast.x - northwest.x,
            southeast.y - northwest.y,
          );
          context.strokeRect(
            northwest.x,
            northwest.y,
            southeast.x - northwest.x,
            southeast.y - northwest.y,
          );
        }
      }
      context.setLineDash([]);

      const visible = output.getContext("2d");
      if (!visible) return;
      visible.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      visible.clearRect(0, 0, width, height);
      visible.drawImage(buffer, 0, 0);
      output.style.transform = "";
    };

    const requestRender = () => {
      void render().catch((reason: unknown) => {
        const aborted =
          reason instanceof DOMException
            ? reason.name === "AbortError"
            : reason instanceof Error && reason.message === "Conversion cancelled";
        if (!cancelled && !aborted) onError(errorMessage(reason));
      });
    };

    let observedWidth = Math.round(container.clientWidth);
    let observedHeight = Math.round(container.clientHeight);
    const observer = new ResizeObserver(() => {
      const width = Math.round(container.clientWidth);
      const height = Math.round(container.clientHeight);
      if (width === observedWidth && height === observedHeight) return;
      observedWidth = width;
      observedHeight = height;
      requestRender();
    });
    observer.observe(container);
    requestRender();

    return () => {
      cancelled = true;
      controller.abort();
      conversionWorker.destroy();
      observer.disconnect();
    };
  }, [
    onError,
    overlayKey,
    exporting,
    project.project_id,
    project.render_revision,
    project.session.view.center_lat,
    project.session.view.center_lon,
    project.session.view.zoom,
  ]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !fitRequest) return;
    const { bounds } = fitRequest;
    const width = container.clientWidth;
    const height = container.clientHeight;
    const zoom = zoomToFit(bounds, width, height, MAX_DISPLAY_ZOOM);
    const center = boundsCenter(bounds);
    onView({
      center_lon: center.lon,
      center_lat: center.lat,
      zoom,
    });
  }, [fitRequest, onView]);

  const eventPoint = (
    event: React.PointerEvent<HTMLDivElement> | React.WheelEvent<HTMLDivElement>,
  ): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };

  const pointLonLat = (point: Point, container: HTMLDivElement) => {
    const frame = viewport(project.session.view, container.clientWidth, container.clientHeight);
    return worldToLonLat(frame.left + point.x, frame.top + point.y, project.session.view.zoom);
  };

  const nearestMarker = (point: Point, container: HTMLDivElement): string | null => {
    const frame = viewport(project.session.view, container.clientWidth, container.clientHeight);
    let nearestId: string | null = null;
    let nearestDistance = 24;
    for (const marker of project.session.markers) {
      const position = lonLatToWorld(marker.lon, marker.lat, project.session.view.zoom);
      const distance = Math.hypot(
        position.x - frame.left - point.x,
        position.y - frame.top - point.y,
      );
      if (distance < nearestDistance) {
        nearestDistance = distance;
        nearestId = marker.marker_id;
      }
    }
    return nearestId;
  };

  return (
    <div
      ref={containerRef}
      className="map browser-map-wrap native-map"
      role="application"
      aria-label="Interactive map. Drag to pan and use the mouse wheel to zoom."
      tabIndex={0}
      onWheel={(event) => {
        event.preventDefault();
        const container = event.currentTarget;
        const point = eventPoint(event);
        const oldFrame = viewport(
          project.session.view,
          container.clientWidth,
          container.clientHeight,
        );
        const zoom = Math.max(
          0,
          Math.min(MAX_DISPLAY_ZOOM, project.session.view.zoom + (event.deltaY < 0 ? 1 : -1)),
        );
        if (zoom === project.session.view.zoom) return;
        const factor = 2 ** (zoom - project.session.view.zoom);
        const anchor = {
          x: (oldFrame.left + point.x) * factor,
          y: (oldFrame.top + point.y) * factor,
        };
        const center = worldToLonLat(
          anchor.x - point.x + container.clientWidth / 2,
          anchor.y - point.y + container.clientHeight / 2,
          zoom,
        );
        onView({
          center_lat: center.lat,
          center_lon: center.lon,
          zoom,
        });
      }}
      onPointerDown={(event) => {
        const point = eventPoint(event);
        const markerId = nearestMarker(point, event.currentTarget);
        dragRef.current = {
          start: point,
          moved: false,
          markerId: markerId === selectedMarkerId ? markerId : null,
        };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag) return;
        const point = eventPoint(event);
        const deltaX = point.x - drag.start.x;
        const deltaY = point.y - drag.start.y;
        if (Math.hypot(deltaX, deltaY) > 3) drag.moved = true;
        if (drag.moved && drag.markerId === null && canvasRef.current) {
          canvasRef.current.style.transform = `translate(${deltaX}px, ${deltaY}px)`;
        }
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        dragRef.current = null;
        if (!drag) return;
        const point = eventPoint(event);
        const deltaX = point.x - drag.start.x;
        const deltaY = point.y - drag.start.y;
        const container = event.currentTarget;

        if (drag.moved) {
          if (drag.markerId) {
            if (canvasRef.current) canvasRef.current.style.transform = "";
            const location = pointLonLat(point, container);
            onMoveMarker(drag.markerId, location.lat, location.lon);
          } else {
            const center = lonLatToWorld(
              project.session.view.center_lon,
              project.session.view.center_lat,
              project.session.view.zoom,
            );
            const location = worldToLonLat(
              center.x - deltaX,
              center.y - deltaY,
              project.session.view.zoom,
            );
            onView({
              ...project.session.view,
              center_lat: location.lat,
              center_lon: location.lon,
            });
          }
          return;
        }

        if (canvasRef.current) canvasRef.current.style.transform = "";
        const markerId = nearestMarker(point, container);
        if (markerId) {
          onSelectMarker(markerId);
          return;
        }
        onSelectMarker(null);
        if (placement) {
          const location = pointLonLat(point, container);
          onPlace(location.lat, location.lon);
        }
      }}
      onPointerCancel={() => {
        dragRef.current = null;
        if (canvasRef.current) canvasRef.current.style.transform = "";
      }}
    >
      <canvas ref={canvasRef} className="browser-map-canvas" />
    </div>
  );
}
