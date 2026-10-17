import { deleteDB, openDB, type DBSchema } from "idb";
import type { ProjectSession, ProjectSnapshot } from "../models";
import { isJsonObject } from "./geojson";
import { MAX_DISPLAY_ZOOM, MAX_MERCATOR_LATITUDE } from "./mercator";
import { defaultSession, normalizeSession } from "./session";
import type { TileCoordinate, TilePlanCacheEntry } from "./tiles";

const DATABASE_NAME = "eink-map-tiles";
const CURRENT_PROJECT_KEY = "eink-map-browser-project";
const VIEW_KEY_PREFIX = "eink-map-browser-view:";
const CACHE_PREFIX = "eink-map-";

interface StoredTilePlan extends TilePlanCacheEntry {
  saved_at: number;
}

interface AppDatabase extends DBSchema {
  projects: {
    key: string;
    value: ProjectSnapshot;
  };
  "tile-plans": {
    key: string;
    value: StoredTilePlan;
  };
}

function database() {
  return openDB<AppDatabase>(DATABASE_NAME, 2, {
    upgrade(db) {
      if (!db.objectStoreNames.contains("projects")) {
        db.createObjectStore("projects", { keyPath: "project_id" });
      }
      if (!db.objectStoreNames.contains("tile-plans")) {
        db.createObjectStore("tile-plans", { keyPath: "key" });
      }
    },
  });
}

export async function loadTilePlanEntries(
  entries: Array<{ key: string; signature: string }>,
): Promise<Record<string, TileCoordinate[]>> {
  const db = await database();
  const cached: Record<string, TileCoordinate[]> = {};
  try {
    const records = await Promise.all(entries.map(({ key }) => db.get("tile-plans", key)));
    records.forEach((record, index) => {
      if (record?.signature === entries[index].signature) cached[record.key] = record.tiles;
    });
    return cached;
  } finally {
    db.close();
  }
}

export async function saveTilePlanEntries(entries: TilePlanCacheEntry[]): Promise<void> {
  if (!entries.length) return;
  const db = await database();
  try {
    const transaction = db.transaction("tile-plans", "readwrite");
    await Promise.all([
      ...entries.map((entry) => transaction.store.put({ ...entry, saved_at: Date.now() })),
      transaction.done,
    ]);
  } finally {
    db.close();
  }
}

const viewKey = (projectId: string) => `${VIEW_KEY_PREFIX}${projectId}`;

export function checkpointBrowserView(projectId: string, view: ProjectSession["view"]): void {
  try {
    localStorage.setItem(viewKey(projectId), JSON.stringify(view));
  } catch {
    // IndexedDB remains the durable copy if localStorage is unavailable or full.
  }
}

function checkpointedView(projectId: string): ProjectSession["view"] | null {
  try {
    const value = localStorage.getItem(viewKey(projectId));
    if (!value) return null;
    const parsed: unknown = JSON.parse(value);
    if (!isJsonObject(parsed)) return null;
    const { center_lat, center_lon, zoom } = parsed;
    if (
      typeof center_lat !== "number" ||
      !Number.isFinite(center_lat) ||
      typeof center_lon !== "number" ||
      !Number.isFinite(center_lon) ||
      typeof zoom !== "number" ||
      !Number.isFinite(zoom)
    )
      return null;
    return {
      center_lat: Math.max(-MAX_MERCATOR_LATITUDE, Math.min(MAX_MERCATOR_LATITUDE, center_lat)),
      center_lon: Math.max(-180, Math.min(180, center_lon)),
      zoom: Math.round(Math.max(0, Math.min(MAX_DISPLAY_ZOOM, zoom))),
    };
  } catch {
    return null;
  }
}

function localStorageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function localStorageSet(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // IndexedDB remains the source of truth when localStorage is unavailable.
  }
}

function withCheckpointedView(project: ProjectSnapshot): ProjectSnapshot {
  const view = checkpointedView(project.project_id);
  return view ? { ...project, session: { ...project.session, view } } : project;
}

export async function loadBrowserProject(): Promise<ProjectSnapshot> {
  const db = await database();
  try {
    const currentId = localStorageGet(CURRENT_PROJECT_KEY);
    if (currentId) {
      const stored = await db.get("projects", currentId);
      if (stored) {
        const normalized = withCheckpointedView({
          ...stored,
          session: normalizeSession(stored.session),
        });
        return normalized;
      }
    }

    const project: ProjectSnapshot = {
      project_id: crypto.randomUUID(),
      revision: 0,
      render_revision: 0,
      session: defaultSession(),
    };
    await db.put("projects", project);
    localStorageSet(CURRENT_PROJECT_KEY, project.project_id);
    return project;
  } finally {
    db.close();
  }
}

export async function saveBrowserProject(
  current: ProjectSnapshot,
  session: ProjectSession,
  changesRenderedPixels = false,
): Promise<ProjectSnapshot> {
  const next = {
    ...current,
    revision: current.revision + 1,
    render_revision: current.render_revision + Number(changesRenderedPixels),
    session,
  };
  const db = await database();
  try {
    await db.put("projects", next);
  } finally {
    db.close();
  }
  return next;
}

export async function importBrowserProject(session: unknown): Promise<ProjectSnapshot> {
  const project: ProjectSnapshot = {
    project_id: crypto.randomUUID(),
    revision: 0,
    render_revision: 0,
    session: normalizeSession(session),
  };
  const db = await database();
  try {
    await db.put("projects", project);
  } finally {
    db.close();
  }
  localStorageSet(CURRENT_PROJECT_KEY, project.project_id);
  return project;
}

export function setCurrentProject(projectId: string): void {
  localStorageSet(CURRENT_PROJECT_KEY, projectId);
}

export async function resetBrowserData(): Promise<void> {
  try {
    const ownedKeys = Object.keys(localStorage).filter(
      (key) => key === CURRENT_PROJECT_KEY || key.startsWith(VIEW_KEY_PREFIX),
    );
    ownedKeys.forEach((key) => localStorage.removeItem(key));
  } catch {
    // Continue clearing IndexedDB and Cache Storage.
  }
  await deleteDB(DATABASE_NAME);
  if ("caches" in globalThis) {
    const names = await caches.keys();
    await Promise.all(
      names.filter((name) => name.startsWith(CACHE_PREFIX)).map((name) => caches.delete(name)),
    );
  }
}
