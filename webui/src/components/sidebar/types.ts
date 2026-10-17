import type { TileEstimateProgress } from "../../browser/tiles";
import type {
  AreaSelection,
  ExportEstimate,
  ExportJob,
  ExportKind,
  Marker,
  ProjectSession,
  ProjectSnapshot,
} from "../../models";

export type SaveSession = (mutate: (session: ProjectSession) => void) => void;

export interface SidebarProps {
  project: ProjectSnapshot | null;
  save: SaveSession;
  saveRender: SaveSession;
  onImportSession: (file: File) => void;
  onGeoJsonFiles: (files: File[]) => void;
  estimate: ExportEstimate | null;
  estimateError: string | null;
  estimateProgress: TileEstimateProgress | null;
  exportJob: ExportJob | null;
  onStartExport: (kind: ExportKind) => void;
  onCancelExport: () => void;
  placement: Marker | null;
  setPlacement: (marker: Marker | null) => void;
  selectedMarkerId: string | null;
  setSelectedMarkerId: (markerId: string | null) => void;
  fitGeoJson: () => void;
  selectGeoJson: () => void;
  fitSelection: (selection: AreaSelection) => void;
}
