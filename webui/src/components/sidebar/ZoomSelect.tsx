import { zoomLabel } from "../../browser/mapConfig";
import { MAX_DISPLAY_ZOOM } from "../../browser/mercator";
import type { MapSource } from "../../models";

interface ZoomSelectProps {
  label: string;
  value: number;
  source: MapSource;
  disabledBefore?: number;
  disabledAfter?: number;
  onChange: (value: number) => void;
}

export function ZoomSelect({
  label,
  value,
  source,
  disabledBefore = 0,
  disabledAfter = MAX_DISPLAY_ZOOM,
  onChange,
}: ZoomSelectProps) {
  return (
    <label className="field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(Number(event.currentTarget.value))}>
        {Array.from({ length: MAX_DISPLAY_ZOOM + 1 }, (_, zoom) => (
          <option key={zoom} value={zoom} disabled={zoom < disabledBefore || zoom > disabledAfter}>
            {zoomLabel(zoom, source)}
          </option>
        ))}
      </select>
    </label>
  );
}
