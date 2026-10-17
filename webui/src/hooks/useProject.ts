import { useCallback, useEffect, useRef, useState } from "react";
import type { MapView, ProjectSession, ProjectSnapshot } from "../models";
import {
  checkpointBrowserView,
  importBrowserProject,
  loadBrowserProject,
  saveBrowserProject,
  setCurrentProject,
} from "../browser/storage";
import { errorMessage } from "../browser/format";

export type SessionMutation = (session: ProjectSession) => void;

function editableSessionCopy(session: ProjectSession): ProjectSession {
  return {
    ...session,
    view: { ...session.view },
    render: { ...session.render, elements: [...session.render.elements] },
    export: { ...session.export },
    inkhud: { ...session.inkhud },
    markers: session.markers.map((marker) => ({ ...marker })),
    geojson_layers: session.geojson_layers.map((layer) => ({ ...layer })),
    area_selections: session.area_selections.map((selection) => ({
      ...selection,
      bbox: { ...selection.bbox },
    })),
  };
}

export function useProject(onError: (message: string) => void) {
  const [project, setProject] = useState<ProjectSnapshot | null>(null);
  const [saving, setSaving] = useState(false);
  const projectRef = useRef<ProjectSnapshot | null>(null);
  const saveChainRef = useRef<Promise<void>>(Promise.resolve());
  const pendingSavesRef = useRef(0);
  const viewSaveTimerRef = useRef<number | null>(null);

  const acceptProject = useCallback((next: ProjectSnapshot) => {
    projectRef.current = next;
    setCurrentProject(next.project_id);
    setProject(next);
  }, []);

  const save = useCallback(
    (mutate: SessionMutation, changesRenderedPixels = false) => {
      const current = projectRef.current;
      if (!current) return Promise.resolve();

      // Geometry payloads are immutable after import. Copy editable containers
      // while retaining those potentially large payloads by reference.
      const session = editableSessionCopy(current.session);
      mutate(session);
      const transient: ProjectSnapshot = {
        ...current,
        revision: current.revision + 1,
        render_revision: current.render_revision + Number(changesRenderedPixels),
        session,
      };
      projectRef.current = transient;
      setProject(transient);
      pendingSavesRef.current += 1;
      setSaving(true);

      const persistence = saveChainRef.current.then(async () => {
        try {
          let saved = await saveBrowserProject(current, session, changesRenderedPixels);
          const latest = projectRef.current;
          if (latest?.project_id === saved.project_id && latest.revision === saved.revision) {
            saved = { ...saved, session: { ...saved.session, view: latest.session.view } };
            acceptProject(saved);
          }
        } catch (reason) {
          const latest = projectRef.current;
          if (
            latest?.project_id === transient.project_id &&
            latest.revision === transient.revision
          ) {
            acceptProject({
              ...current,
              session: { ...current.session, view: latest.session.view },
            });
          }
          onError(errorMessage(reason));
        } finally {
          pendingSavesRef.current -= 1;
          if (pendingSavesRef.current === 0) setSaving(false);
        }
      });
      saveChainRef.current = persistence;
      return persistence;
    },
    [acceptProject, onError],
  );

  const saveRender = useCallback((mutate: SessionMutation) => save(mutate, true), [save]);

  const updateView = useCallback(
    (view: MapView) => {
      const current = projectRef.current;
      if (!current) return;
      const transient = {
        ...current,
        session: { ...current.session, view },
      };
      projectRef.current = transient;
      setProject(transient);
      checkpointBrowserView(current.project_id, view);

      if (viewSaveTimerRef.current) window.clearTimeout(viewSaveTimerRef.current);
      viewSaveTimerRef.current = window.setTimeout(() => {
        viewSaveTimerRef.current = null;
        const settledView = projectRef.current?.session.view;
        if (settledView) void save((session) => void (session.view = settledView));
      }, 200);
    },
    [save],
  );

  const importSession = useCallback(
    async (file: File) => {
      setSaving(true);
      try {
        const data: unknown = JSON.parse(await file.text());
        acceptProject(await importBrowserProject(data));
      } catch (reason) {
        onError(errorMessage(reason));
      } finally {
        setSaving(false);
      }
    },
    [acceptProject, onError],
  );

  useEffect(() => {
    let active = true;
    void loadBrowserProject()
      .then((loaded) => {
        if (active) acceptProject(loaded);
      })
      .catch((reason: unknown) => {
        if (active) onError(errorMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [acceptProject, onError]);

  useEffect(
    () => () => {
      if (viewSaveTimerRef.current) window.clearTimeout(viewSaveTimerRef.current);
    },
    [],
  );

  return {
    project,
    projectRef,
    saving,
    save,
    saveRender,
    saveChainRef,
    updateView,
    importSession,
  };
}
