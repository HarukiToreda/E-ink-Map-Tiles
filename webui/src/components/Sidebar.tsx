import { mapAttributions } from "../browser/mapConfig";
import type { ProjectSession } from "../models";
import { ExportSection } from "./sidebar/ExportSection";
import { MapSourceSection } from "./sidebar/MapSourceSection";
import { MarkersSection } from "./sidebar/MarkersSection";
import { SelectionsSection } from "./sidebar/SelectionsSection";
import type { SidebarProps } from "./sidebar/types";

function Attribution({ session }: { session: ProjectSession }) {
  return (
    <footer className="about-section section-note" aria-label="About and attribution">
      <strong>E-ink Map Tiles {__APP_VERSION__}</strong>
      <span>
        {mapAttributions(session).map(({ label, url }, index) => (
          <span key={url}>
            {index > 0 && " · "}
            <a href={url} target="_blank" rel="noreferrer">
              {label}
            </a>
          </span>
        ))}
      </span>
    </footer>
  );
}

export function Sidebar(props: SidebarProps) {
  if (!props.project) {
    return (
      <div className="sections">
        <p className="section-placeholder">Loading controls…</p>
      </div>
    );
  }
  const session = props.project.session;
  return (
    <div className="sections">
      <MapSourceSection session={session} save={props.save} saveRender={props.saveRender} />
      <SelectionsSection
        session={session}
        save={props.save}
        saveRender={props.saveRender}
        onGeoJsonFiles={props.onGeoJsonFiles}
        fitGeoJson={props.fitGeoJson}
        selectGeoJson={props.selectGeoJson}
        fitSelection={props.fitSelection}
      />
      <MarkersSection
        session={session}
        saveRender={props.saveRender}
        placement={props.placement}
        setPlacement={props.setPlacement}
        selectedMarkerId={props.selectedMarkerId}
        setSelectedMarkerId={props.setSelectedMarkerId}
      />
      <ExportSection
        session={session}
        estimate={props.estimate}
        estimateError={props.estimateError}
        estimateProgress={props.estimateProgress}
        exportJob={props.exportJob}
        onStartExport={props.onStartExport}
        onCancelExport={props.onCancelExport}
        onImportSession={props.onImportSession}
      />
      <Attribution session={session} />
    </div>
  );
}
