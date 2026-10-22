let activePreviewTiles = 0;
let exportPending = false;
const previewIdleWaiters = new Set<() => void>();

function abortError(): DOMException {
  return new DOMException("Preview rendering paused for export", "AbortError");
}

function notifyPreviewIdle(): void {
  if (activePreviewTiles !== 0) return;
  for (const resolve of previewIdleWaiters) resolve();
  previewIdleWaiters.clear();
}

export async function renderPreviewTile<T>(render: () => Promise<T>): Promise<T> {
  if (exportPending) throw abortError();
  activePreviewTiles += 1;
  try {
    return await render();
  } finally {
    activePreviewTiles -= 1;
    notifyPreviewIdle();
  }
}

export async function renderExportTiles<T>(render: () => Promise<T>): Promise<T> {
  exportPending = true;
  if (activePreviewTiles !== 0)
    await new Promise<void>((resolve) => previewIdleWaiters.add(resolve));
  try {
    return await render();
  } finally {
    exportPending = false;
  }
}
