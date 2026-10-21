const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("einkMapDesktop", {
  platform: process.platform,
  streamingExportKinds: ["normal-zip", "mui-pmtiles", "inkhud-header", "inkhud-binary"],
  startZip: (suggestedName) => ipcRenderer.invoke("desktop:zip:start", { suggestedName }),
  writeZipEntry: (jobId, name, bytes) =>
    ipcRenderer.invoke("desktop:zip:write", { jobId, name, bytes }),
  finishZip: (jobId) => ipcRenderer.invoke("desktop:zip:finish", { jobId }),
  abortZip: (jobId) => ipcRenderer.invoke("desktop:zip:abort", { jobId }),
  startExport: (kind, suggestedName, options) =>
    ipcRenderer.invoke("desktop:export:start", { kind, suggestedName, options }),
  writeExportTile: (jobId, tile, bytes, payloadKind) =>
    ipcRenderer.invoke("desktop:export:write", { jobId, tile, bytes, payloadKind }),
  finishExport: (jobId) => ipcRenderer.invoke("desktop:export:finish", { jobId }),
  abortExport: (jobId) => ipcRenderer.invoke("desktop:export:abort", { jobId }),
});
