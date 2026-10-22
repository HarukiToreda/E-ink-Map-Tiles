const assert = require("node:assert/strict");
const { mkdtemp, readFile, rm, writeFile } = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const { afterEach, test } = require("node:test");
const { unzipSync } = require("fflate");
const {
  createZipWriter,
  finishMtb,
  finishMtbBundle,
  finishPmtiles,
  planMtbPayload,
  zxyToTileId,
} = require("./streaming-writers.cjs");

const temporaryDirectories = [];

async function temporaryDirectory() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "eink-map-tiles-"));
  temporaryDirectories.push(directory);
  return directory;
}

afterEach(async () => {
  await Promise.all(
    temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true })),
  );
});

test("creates a forced ZIP64 archive", async () => {
  const directory = await temporaryDirectory(),
    outputPath = path.join(directory, "tiles.zip"),
    { archive, output, failure } = createZipWriter(outputPath),
    closed = new Promise((resolve, reject) => {
      output.once("close", resolve);
      output.once("error", reject);
    });
  archive.append(Buffer.from("tile"), { name: "maps/test/0/0/0.png" });
  await archive.finalize();
  await Promise.race([closed, failure]);
  const result = await readFile(outputPath);
  assert.notEqual(result.indexOf(Buffer.from([0x50, 0x4b, 0x06, 0x06])), -1);
});

test("writes PMTiles readable by the official client", async () => {
  const directory = await temporaryDirectory(),
    spoolPath = path.join(directory, "tiles.spool"),
    outputPath = path.join(directory, "tiles.pmtiles"),
    png = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  await writeFile(spoolPath, png);
  await finishPmtiles({
    records: [{ z: 0, x: 0, y: 0, tileId: zxyToTileId(0, 0, 0), offset: 0, length: png.length }],
    options: { styleName: "test", attribution: "OpenStreetMap" },
    spoolPath,
    tempPath: outputPath,
  });
  const data = await readFile(outputPath),
    { PMTiles } = await import("pmtiles"),
    reader = new PMTiles({
      getKey: () => "native-test.pmtiles",
      getBytes: async (offset, length) => ({
        data: data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + length),
      }),
    });
  assert.equal((await reader.getHeader()).tileType, 2);
  assert.deepEqual(Buffer.from((await reader.getZxy(0, 0, 0)).data), png);
});

test("deduplicates InkHUD payloads in binary and header exports", async () => {
  const directory = await temporaryDirectory(),
    spoolPath = path.join(directory, "tiles.spool"),
    payload = Buffer.from([1, 2, 3]),
    state = { offset: 0, payloadOffsets: new Map() },
    first = planMtbPayload(state, payload, 0),
    duplicate = planMtbPayload(state, payload, 0),
    records = [
      {
        z: 7,
        x: 1,
        y: 2,
        length: first.length,
        offset: first.offset,
        payloadKind: first.payloadKind,
      },
      {
        z: 7,
        x: 2,
        y: 2,
        length: duplicate.length,
        offset: duplicate.offset,
        payloadKind: duplicate.payloadKind,
      },
    ];
  assert.equal(first.writePayload, true);
  assert.equal(duplicate.writePayload, false);
  assert.equal(state.offset, payload.length);
  assert.equal(first.offset, duplicate.offset);
  await writeFile(spoolPath, payload);

  const binaryPath = path.join(directory, "MapTile.bin");
  await finishMtb({
    kind: "inkhud-binary",
    records,
    offset: state.offset,
    options: { depth: 1 },
    spoolPath,
    tempPath: binaryPath,
  });
  const binary = await readFile(binaryPath);
  assert.equal(binary.readUInt32LE(12), payload.length);
  assert.equal(binary.readUInt32LE(29), 0);
  assert.equal(binary.readUInt32LE(36), 0);
  assert.deepEqual(binary.subarray(40), payload);

  const headerPath = path.join(directory, "MapTile.h");
  await finishMtb({
    kind: "inkhud-header",
    records,
    offset: state.offset,
    options: {
      depth: 1,
      style: "test",
      sdCardAttribution: "OpenStreetMap contributors\nhttps://example.test",
      sdCardLicense: "ODbL terms",
    },
    spoolPath,
    tempPath: headerPath,
  });
  const header = await readFile(headerPath, "utf8");
  assert.match(header, /map_tile_offsets\[\] = \{ 0, 0 \};/);
  assert.match(
    header,
    /map_tile_attribution\[\] = "OpenStreetMap contributors\\nhttps:\/\/example\.test";/,
  );
  assert.match(header, /map_tile_license\[\] = "ODbL terms";/);
  assert.equal(header.match(/0x01/g)?.length, 1);
});

test("represents white and black InkHUD tiles without payload bytes", () => {
  const state = { offset: 0, payloadOffsets: new Map() };
  assert.deepEqual(planMtbPayload(state, Buffer.alloc(0), 1), {
    length: 0,
    offset: 0,
    payloadKind: 1,
    writePayload: false,
  });
  assert.deepEqual(planMtbPayload(state, Buffer.alloc(0), 2), {
    length: 0,
    offset: 0,
    payloadKind: 2,
    writePayload: false,
  });
  assert.equal(state.offset, 0);
});

test("packages an SD card binary with license and attribution files", async () => {
  const directory = await temporaryDirectory(),
    spoolPath = path.join(directory, "tiles.spool"),
    bundlePath = path.join(directory, "MapTiles.zip");
  await writeFile(spoolPath, Buffer.from([1, 2, 3]));
  await finishMtbBundle({
    kind: "inkhud-binary",
    records: [{ z: 7, x: 1, y: 2, length: 3, offset: 0, payloadKind: 0 }],
    offset: 3,
    options: {
      depth: 1,
      sdCardLicense: "license details",
      sdCardAttribution: "attribution details",
    },
    spoolPath,
    tempPath: bundlePath,
  });
  const files = unzipSync(await readFile(bundlePath));
  assert.equal(Buffer.from(files["Map/MapTile.bin"]).subarray(0, 4).toString(), "MTB1");
  assert.equal(Buffer.from(files["LICENSE.txt"]).toString(), "license details");
  assert.equal(Buffer.from(files["ATTRIBUTION.txt"]).toString(), "attribution details");
});
