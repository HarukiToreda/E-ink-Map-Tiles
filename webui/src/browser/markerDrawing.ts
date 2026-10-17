import type { Marker } from "../models";

export type ProjectMarker = (marker: Marker) => { x: number; y: number } | null;

/** Draw project-owned markers into the final pixel composition. */
export function drawProjectMarkers(
  context: CanvasRenderingContext2D,
  markers: Marker[],
  project: ProjectMarker,
  scale = 1,
) {
  for (const marker of markers) {
    const point = project(marker);
    if (!point) continue;
    const label = marker.label || "Marker";
    context.save();
    context.font = `bold ${14 * scale}px sans-serif`;
    context.textAlign = marker.label_is_marker ? "center" : "left";
    context.textBaseline = "middle";
    if (!marker.label_is_marker) {
      context.fillStyle = "#dc2626";
      context.beginPath();
      context.arc(point.x, point.y, 6 * scale, 0, Math.PI * 2);
      context.fill();
      context.strokeStyle = "white";
      context.lineWidth = 2 * scale;
      context.stroke();
    }
    const textX = marker.label_is_marker ? point.x : point.x + 9 * scale;
    context.lineWidth = 3 * scale;
    context.strokeStyle = "white";
    context.strokeText(label, textX, point.y);
    context.fillStyle = "#111827";
    context.fillText(label, textX, point.y);
    context.restore();
  }
}
