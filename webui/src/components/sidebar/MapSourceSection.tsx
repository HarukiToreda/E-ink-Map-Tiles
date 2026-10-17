import { isMapSource, MAP_SOURCES, mapSourceDefinition } from "../../browser/mapConfig";
import { isTileDepth } from "../../browser/session";
import type { MapElement, ProjectSession } from "../../models";
import type { SaveSession } from "./types";

const ELEMENT_OPTIONS: ReadonlyArray<{ id: MapElement; label: string }> = [
  { id: "land", label: "Land" },
  { id: "water", label: "Water" },
  { id: "roads", label: "Roads" },
  { id: "highways", label: "Highways" },
  { id: "paths", label: "Paths" },
  { id: "buildings", label: "Buildings" },
  { id: "boundaries", label: "Boundaries" },
  { id: "labels", label: "Labels" },
  { id: "pois", label: "POI" },
  { id: "transit", label: "Transit" },
];

interface MapSourceSectionProps {
  session: ProjectSession;
  save: SaveSession;
  saveRender: SaveSession;
}

export function MapSourceSection({ session, save, saveRender }: MapSourceSectionProps) {
  const sourceDefinition = mapSourceDefinition(session.render.source);
  const setRender = <Key extends keyof ProjectSession["render"]>(
    key: Key,
    value: ProjectSession["render"][Key],
  ) =>
    saveRender((next) => {
      next.render[key] = value;
    });

  return (
    <details className="map-source-section">
      <summary>Map Source</summary>
      <div className="section-body">
        <label className="field">
          <span>Map Tile Source</span>
          <select
            value={session.render.source}
            onChange={(event) => {
              const source = event.currentTarget.value;
              if (!isMapSource(source)) return;
              saveRender((next) => {
                next.render.source = source;
                if (source === "usgs-topo") next.render.style = "osm-eink";
              });
            }}
          >
            {MAP_SOURCES.map((source) => (
              <option value={source.id} key={source.id}>
                {source.label}
              </option>
            ))}
          </select>
        </label>

        <details className="map-rendering-subsection">
          <summary>Map Rendering</summary>
          <div className="section-body">
            <label className="field">
              <span>E-ink conversion</span>
              <select
                value={session.render.mode === "original" ? "none" : session.inkhud.tile_depth}
                onChange={(event) => {
                  const conversion = event.currentTarget.value;
                  saveRender((next) => {
                    next.render.mode = conversion === "none" ? "original" : "inkhud";
                    const depth = Number(conversion);
                    if (isTileDepth(depth)) next.inkhud.tile_depth = depth;
                  });
                }}
              >
                <option value="none">None (full color)</option>
                <option value="1">MTB1 (Monochrome)</option>
                <option value="2">MTB2 (Grayscale, 4 shades)</option>
                <option value="4">MTB4 (Grayscale, 16 shades)</option>
              </select>
            </label>
            {sourceDefinition.optionalTopography ? (
              <label className="check">
                <input
                  type="checkbox"
                  checked={session.render.style === "osm-eink-topo"}
                  onChange={(event) =>
                    setRender("style", event.currentTarget.checked ? "osm-eink-topo" : "osm-eink")
                  }
                />
                Topography (Mapzen)
              </label>
            ) : (
              <p className="section-note">Topography is included by the USGS source.</p>
            )}
            <label className="check">
              <input
                type="checkbox"
                checked={session.export.smooth_zoom_transitions}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  save((next) => {
                    next.export.smooth_zoom_transitions = checked;
                  });
                }}
              />
              Smooth Zoom Transitions
              <span
                className="help-tooltip"
                tabIndex={0}
                title="Add stepped tile rings so overlapping regions change detail one zoom level at a time."
                aria-label="Add stepped tile rings so overlapping regions change detail one zoom level at a time."
              >
                ?
              </span>
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={session.export.attribution_acknowledged}
                onChange={(event) =>
                  save((next) => {
                    next.export.attribution_acknowledged = event.currentTarget.checked;
                  })
                }
              />
              Keep required map attribution
            </label>
          </div>
        </details>

        {sourceDefinition.configurableElements && (
          <details className="map-elements-subsection">
            <summary>Map Elements</summary>
            <div className="section-body checks">
              {ELEMENT_OPTIONS.map(({ id, label }) => (
                <label className="check" key={id}>
                  <input
                    type="checkbox"
                    checked={session.render.elements.includes(id)}
                    onChange={(event) =>
                      setRender(
                        "elements",
                        event.currentTarget.checked
                          ? [...session.render.elements, id]
                          : session.render.elements.filter((element) => element !== id),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
              <button
                onClick={() =>
                  setRender(
                    "elements",
                    ELEMENT_OPTIONS.map(({ id }) => id),
                  )
                }
              >
                Select all
              </button>
              <button onClick={() => setRender("elements", [])}>Clear all</button>
            </div>
          </details>
        )}
      </div>
    </details>
  );
}
