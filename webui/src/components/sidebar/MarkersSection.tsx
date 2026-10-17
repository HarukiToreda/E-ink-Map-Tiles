import type { Marker, ProjectSession } from "../../models";
import type { SaveSession } from "./types";

interface MarkersSectionProps {
  session: ProjectSession;
  saveRender: SaveSession;
  placement: Marker | null;
  setPlacement: (marker: Marker | null) => void;
  selectedMarkerId: string | null;
  setSelectedMarkerId: (markerId: string | null) => void;
}

export function MarkersSection({
  session,
  saveRender,
  placement,
  setPlacement,
  selectedMarkerId,
  setSelectedMarkerId,
}: MarkersSectionProps) {
  const selectedMarker = session.markers.find((marker) => marker.marker_id === selectedMarkerId);
  return (
    <details className="markers-section">
      <summary>Markers</summary>
      <div className="section-body">
        {placement && (
          <>
            <label className="field">
              <span>Label (can include emoji)</span>
              <input
                value={placement.label}
                onChange={(event) =>
                  setPlacement({ ...placement, label: event.currentTarget.value })
                }
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={placement.label_is_marker}
                onChange={(event) =>
                  setPlacement({ ...placement, label_is_marker: event.currentTarget.checked })
                }
              />
              Label is marker
            </label>
          </>
        )}
        <button
          onClick={() =>
            setPlacement(
              placement
                ? null
                : {
                    marker_id: crypto.randomUUID(),
                    lat: 0,
                    lon: 0,
                    label: "Marker",
                    label_is_marker: false,
                  },
            )
          }
        >
          {placement ? "Cancel placement" : "Add marker"}
        </button>

        {selectedMarker && (
          <div className="marker-editor">
            <label className="field">
              <span>Label (can include emoji)</span>
              <input
                value={selectedMarker.label}
                onChange={(event) =>
                  saveRender((next) => {
                    const marker = next.markers.find(
                      (item) => item.marker_id === selectedMarker.marker_id,
                    );
                    if (marker) marker.label = event.currentTarget.value || "Marker";
                  })
                }
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={selectedMarker.label_is_marker}
                onChange={(event) =>
                  saveRender((next) => {
                    const marker = next.markers.find(
                      (item) => item.marker_id === selectedMarker.marker_id,
                    );
                    if (marker) marker.label_is_marker = event.currentTarget.checked;
                  })
                }
              />
              Label is marker
            </label>
            <p className="section-note">
              Drag the highlighted map handle to reposition this marker.
            </p>
          </div>
        )}

        {session.markers.map((marker) => (
          <div
            className={`marker-row ${selectedMarkerId === marker.marker_id ? "selected" : ""}`}
            key={marker.marker_id}
          >
            <button className="marker-select" onClick={() => setSelectedMarkerId(marker.marker_id)}>
              <span>{marker.label}</span>
              <small>
                {marker.label_is_marker ? "label marker" : "pin + label"} · {marker.lat.toFixed(5)},{" "}
                {marker.lon.toFixed(5)}
              </small>
            </button>
            <button
              aria-label={`Delete marker ${marker.label}`}
              onClick={() => {
                saveRender((next) => {
                  next.markers = next.markers.filter((item) => item.marker_id !== marker.marker_id);
                });
                setSelectedMarkerId(null);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </details>
  );
}
