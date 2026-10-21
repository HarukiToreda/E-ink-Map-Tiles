const { randomUUID } = require("node:crypto");
const fs = require("node:fs");
const { unlink } = require("node:fs/promises");
const path = require("node:path");
const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const {
  createZipWriter,
  finishMtb,
  finishPmtiles,
  planMtbPayload,
  zxyToTileId,
} = require("./streaming-writers.cjs");

const zipJobs = new Map();

function senderWindow(event) {
  const window = BrowserWindow.fromWebContents(event.sender);
  if (!window || window.isDestroyed()) throw new Error("Export window is no longer available");
  return window;
}

function zipJob(event, jobId) {
  senderWindow(event);
  const job = zipJobs.get(jobId);
  if (!job || job.senderId !== event.sender.id) throw new Error("Unknown ZIP export");
  return job;
}

function safeEntryName(name) {
  if (typeof name !== "string" || !name || name.includes("\\") || name.startsWith("/"))
    throw new Error("Invalid ZIP entry name");
  const parts = name.split("/");
  if (parts.some((part) => !part || part === "." || part === ".."))
    throw new Error("Invalid ZIP entry name");
  return name;
}

async function discardJob(jobId, job) {
  zipJobs.delete(jobId);
  job.archive.abort();
  job.output.destroy();
  await unlink(job.tempPath).catch(() => {});
}

ipcMain.handle("desktop:zip:start", async (event, { suggestedName } = {}) => {
  const window = senderWindow(event);
  const defaultName =
    typeof suggestedName === "string" && suggestedName.toLowerCase().endsWith(".zip")
      ? path.basename(suggestedName)
      : "MUI-Tiles.zip";
  const result = await dialog.showSaveDialog(window, {
    title: "Save map tiles",
    defaultPath: defaultName,
    filters: [{ name: "ZIP archive", extensions: ["zip"] }],
  });
  if (result.canceled || !result.filePath) return null;

  const jobId = randomUUID();
  const tempPath = `${result.filePath}.${jobId}.partial`;
  const { archive, output, failure } = createZipWriter(tempPath);
  const job = {
    archive,
    finalPath: result.filePath,
    output,
    senderId: event.sender.id,
    tempPath,
    queue: Promise.resolve(),
  };
  job.failure = failure;
  zipJobs.set(jobId, job);
  return jobId;
});

ipcMain.handle("desktop:zip:write", async (event, { jobId, name, bytes } = {}) => {
  const job = zipJob(event, jobId);
  const entryName = safeEntryName(name);
  if (!(bytes instanceof ArrayBuffer) && !ArrayBuffer.isView(bytes))
    throw new Error("Invalid ZIP entry data");
  const data = Buffer.from(
    bytes instanceof ArrayBuffer ? bytes : bytes.buffer,
    bytes instanceof ArrayBuffer ? 0 : bytes.byteOffset,
    bytes instanceof ArrayBuffer ? bytes.byteLength : bytes.byteLength,
  );
  job.queue = job.queue.then(
    () =>
      new Promise((resolve, reject) => {
        const cleanup = () => {
          job.archive.off("entry", onEntry);
          job.archive.off("error", onError);
        };
        const onEntry = (entry) => {
          if (entry.name !== entryName) return;
          cleanup();
          resolve();
        };
        const onError = (error) => {
          cleanup();
          reject(error);
        };
        job.archive.once("error", onError);
        job.archive.on("entry", onEntry);
        job.archive.append(data, { name: entryName });
      }),
  );
  await Promise.race([job.queue, job.failure]);
});

ipcMain.handle("desktop:zip:finish", async (event, { jobId } = {}) => {
  const job = zipJob(event, jobId);
  await Promise.race([job.queue, job.failure]);
  const closed = new Promise((resolve, reject) => {
    job.output.once("close", resolve);
    job.output.once("error", reject);
  });
  await job.archive.finalize();
  await Promise.race([closed, job.failure]);
  await unlink(job.finalPath).catch((error) => {
    if (error.code !== "ENOENT") throw error;
  });
  await fs.promises.rename(job.tempPath, job.finalPath);
  const { size } = await fs.promises.stat(job.finalPath);
  zipJobs.delete(jobId);
  return { path: job.finalPath, size };
});

ipcMain.handle("desktop:zip:abort", async (event, { jobId } = {}) => {
  const job = zipJob(event, jobId);
  await discardJob(jobId, job);
});

ipcMain.handle("desktop:export:start", async (event, { kind, suggestedName, options } = {}) => {
  if (!["mui-pmtiles", "inkhud-header", "inkhud-binary"].includes(kind))
    throw new Error("Unsupported export kind");
  const window = senderWindow(event),
    result = await dialog.showSaveDialog(window, {
      title: "Save map tiles",
      defaultPath: path.basename(suggestedName),
    });
  if (result.canceled || !result.filePath) return null;
  const jobId = randomUUID(),
    tempPath = `${result.filePath}.${jobId}.partial`,
    spoolPath = `${tempPath}.spool`;
  const output = fs.createWriteStream(spoolPath, { flags: "wx" });
  zipJobs.set(jobId, {
    kind,
    finalPath: result.filePath,
    tempPath,
    spoolPath,
    output,
    senderId: event.sender.id,
    options,
    records: [],
    payloadOffsets: new Map(),
    offset: 0,
    queue: Promise.resolve(),
  });
  return jobId;
});

ipcMain.handle(
  "desktop:export:write",
  async (event, { jobId, tile, bytes, payloadKind = 0 } = {}) => {
    const job = zipJob(event, jobId);
    if (
      !job.kind ||
      !tile ||
      !(bytes instanceof ArrayBuffer) ||
      ![tile.z, tile.x, tile.y].every(Number.isSafeInteger)
    )
      throw new Error("Invalid streamed tile");
    const data = Buffer.from(bytes);
    let record,
      writePayload = true;
    if (job.kind === "mui-pmtiles") {
      record = {
        ...tile,
        offset: job.offset,
        length: data.length,
        payloadKind,
        tileId: zxyToTileId(tile.z, tile.x, tile.y),
      };
      job.offset += data.length;
    } else {
      const planned = planMtbPayload(job, data, payloadKind);
      record = { ...tile, ...planned };
      writePayload = planned.writePayload;
      delete record.writePayload;
    }
    job.records.push(record);
    if (writePayload)
      job.queue = job.queue.then(
        () =>
          new Promise((resolve, reject) => {
            const done = () => {
              job.output.off("error", reject);
              resolve();
            };
            job.output.once("error", reject);
            if (job.output.write(data)) done();
            else job.output.once("drain", done);
          }),
      );
    await job.queue;
  },
);

ipcMain.handle("desktop:export:finish", async (event, { jobId } = {}) => {
  const job = zipJob(event, jobId);
  await job.queue;
  job.output.end();
  await new Promise((resolve, reject) => {
    job.output.once("close", resolve);
    job.output.once("error", reject);
  });
  if (job.kind === "mui-pmtiles") await finishPmtiles(job);
  else await finishMtb(job);
  await unlink(job.finalPath).catch((error) => {
    if (error.code !== "ENOENT") throw error;
  });
  await fs.promises.rename(job.tempPath, job.finalPath);
  await unlink(job.spoolPath).catch(() => {});
  const { size } = await fs.promises.stat(job.finalPath);
  zipJobs.delete(jobId);
  return { path: job.finalPath, size };
});

ipcMain.handle("desktop:export:abort", async (event, { jobId } = {}) => {
  const job = zipJob(event, jobId);
  zipJobs.delete(jobId);
  job.output.destroy();
  await Promise.all([unlink(job.tempPath).catch(() => {}), unlink(job.spoolPath).catch(() => {})]);
});

function createWindow() {
  const window = new BrowserWindow({
    width: 1440,
    height: 960,
    minWidth: 980,
    minHeight: 640,
    title: "E-ink Map Tiles",
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("https://")) void shell.openExternal(url);
    return { action: "deny" };
  });
  window.webContents.on("will-navigate", (event, url) => {
    if (url !== window.webContents.getURL()) event.preventDefault();
  });
  void window.loadFile(path.join(__dirname, "..", "dist", "index.html"));
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  for (const [jobId, job] of zipJobs) {
    if (job.archive) void discardJob(jobId, job);
    else {
      zipJobs.delete(jobId);
      job.output.destroy();
      void unlink(job.tempPath).catch(() => {});
      void unlink(job.spoolPath).catch(() => {});
    }
  }
});
