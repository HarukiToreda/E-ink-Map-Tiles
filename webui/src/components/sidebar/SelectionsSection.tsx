import { geoJsonPrimitiveCount } from "../../browser/geojson";
import { sourceMaxZoom, zoomLabel } from "../../browser/mapConfig";
import type { AreaSelection, ProjectSession } from "../../models";
import type { SaveSession } from "./types";
import { ZoomSelect } from "./ZoomSelect";

interface SelectionsSectionProps {
  session: ProjectSession;
  save: SaveSession;
  saveRender: SaveSession;
  onGeoJsonFiles: (files: File[]) => void;
  fitGeoJson: () => void;
  selectGeoJson: () => void;
  fitSelection: (selection: AreaSelection) => void;
}

export function SelectionsSection({
  session,
  save,
  saveRender,
  onGeoJsonFiles,
  fitGeoJson,
  selectGeoJson,
  fitSelection,
}: SelectionsSectionProps) {
  const sourceZoomLimit = sourceMaxZoom(session.render.source);
  return (
    <details className="selections-section">
      <summary>Selections</summary>
      <div className="section-body">
        <details className="geojson-add">
          <summary>Add GeoJSON</summary>
          <div className="section-body">
            <label className="button-link file-button">
              Choose GeoJSON files
              <input
                type="file"
                multiple
                accept="application/geo+json,application/json,.geojson,.json"
                onChange={(event) => {
                  onGeoJsonFiles(Array.from(event.currentTarget.files ?? []));
                  event.currentTarget.value = "";
                }}
              />
            </label>
            <div
              className="drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                onGeoJsonFiles(Array.from(event.dataTransfer.files));
              }}
            >
              Drop GeoJSON files here
            </div>
            {session.geojson_layers.some((layer) => layer.visible) && (
              <>
                <button onClick={fitGeoJson}>Fit visible layers</button>
                <button onClick={selectGeoJson}>Add visible layers to selections</button>
              </>
            )}
            {session.geojson_layers.map((layer) => (
              <div className="layer-row" key={layer.layer_id}>
                <strong>
                  {layer.name} <small>({geoJsonPrimitiveCount(layer.geojson)} primitives)</small>
                </strong>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={layer.visible}
                    onChange={(event) =>
                      saveRender((next) => {
                        const target = next.geojson_layers.find(
                          (item) => item.layer_id === layer.layer_id,
                        );
                        if (target) target.visible = event.currentTarget.checked;
                      })
                    }
                  />
                  Visible
                </label>
                <div className="field-grid">
                  <ZoomSelect
                    label="Min zoom"
                    value={layer.min_zoom}
                    source={session.render.source}
                    disabledAfter={layer.max_zoom}
                    onChange={(value) =>
                      saveRender((next) => {
                        const target = next.geojson_layers.find(
                          (item) => item.layer_id === layer.layer_id,
                        );
                        if (target) target.min_zoom = value;
                      })
                    }
                  />
                  <ZoomSelect
                    label="Max zoom"
                    value={layer.max_zoom}
                    source={session.render.source}
                    disabledBefore={layer.min_zoom}
                    onChange={(value) =>
                      saveRender((next) => {
                        const target = next.geojson_layers.find(
                          (item) => item.layer_id === layer.layer_id,
                        );
                        if (target) target.max_zoom = value;
                      })
                    }
                  />
                </div>
                <button
                  onClick={() =>
                    saveRender((next) => {
                      next.geojson_layers = next.geojson_layers.filter(
                        (item) => item.layer_id !== layer.layer_id,
                      );
                      next.area_selections = next.area_selections.filter(
                        (selection) => selection.source_layer_id !== layer.layer_id,
                      );
                    })
                  }
                >
                  Remove layer
                </button>
              </div>
            ))}
          </div>
        </details>

        {session.area_selections.map((selection) => (
          <div className="named-selection" key={selection.selection_id}>
            <label className="check">
              <input
                type="checkbox"
                checked={selection.enabled}
                onChange={(event) =>
                  save((next) => {
                    const target = next.area_selections.find(
                      (item) => item.selection_id === selection.selection_id,
                    );
                    if (target) target.enabled = event.currentTarget.checked;
                  })
                }
              />
              <span>
                <strong>{selection.name}</strong>
              </span>
            </label>
            <div className="field-grid">
              <ZoomSelect
                label="Min zoom"
                value={selection.min_zoom}
                source={session.render.source}
                disabledAfter={selection.max_zoom}
                onChange={(value) =>
                  save((next) => {
                    const target = next.area_selections.find(
                      (item) => item.selection_id === selection.selection_id,
                    );
                    if (target) target.min_zoom = value;
                  })
                }
              />
              <ZoomSelect
                label="Max zoom"
                value={selection.max_zoom}
                source={session.render.source}
                disabledBefore={selection.min_zoom}
                onChange={(value) =>
                  save((next) => {
                    const target = next.area_selections.find(
                      (item) => item.selection_id === selection.selection_id,
                    );
                    if (target) target.max_zoom = value;
                  })
                }
              />
            </div>
            {selection.max_zoom > sourceZoomLimit && (
              <small className="section-note">
                Maximum includes {zoomLabel(selection.max_zoom, session.render.source)} derived
                zoom.
              </small>
            )}
            <div>
              <button onClick={() => fitSelection(selection)}>Fit</button>
              <button
                className="danger"
                onClick={() =>
                  save((next) => {
                    next.area_selections = next.area_selections.filter(
                      (item) => item.selection_id !== selection.selection_id,
                    );
                  })
                }
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}
