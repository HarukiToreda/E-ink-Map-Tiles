const { createHash } = require("node:crypto");
const fs = require("node:fs");
const { open, unlink } = require("node:fs/promises");
const archiverModule = require("archiver");

function createZipWriter(tempPath) {
  const output = fs.createWriteStream(tempPath, { flags: "wx" }),
    archive = new archiverModule.ZipArchive({ forceZip64: true, zlib: { level: 6 } });
  archive.pipe(output);
  const failure = new Promise((_, reject) => {
    archive.once("error", reject);
    output.once("error", reject);
  });
  failure.catch(() => {});
  return { archive, output, failure };
}

function planMtbPayload(job, data, payloadKind) {
  if (payloadKind) return { length: 0, offset: 0, payloadKind, writePayload: false };
  const payloadKey = `${data.length}:${createHash("sha256").update(data).digest("hex")}`,
    existingOffset = job.payloadOffsets.get(payloadKey);
  if (existingOffset !== undefined)
    return { length: data.length, offset: existingOffset, payloadKind: 0, writePayload: false };
  const offset = job.offset;
  job.payloadOffsets.set(payloadKey, offset);
  job.offset += data.length;
  return { length: data.length, offset, payloadKind: 0, writePayload: true };
}

function varint(output, value) {
  while (value >= 128) {
    output.push((value % 128) | 128);
    value = Math.floor(value / 128);
  }
  output.push(value);
}

function encodeDirectory(entries) {
  const output = [];
  varint(output, entries.length);
  let previousId = 0;
  for (const entry of entries) {
    varint(output, entry.tileId - previousId);
    previousId = entry.tileId;
  }
  for (const entry of entries) varint(output, entry.runLength);
  for (const entry of entries) varint(output, entry.length);
  let nextOffset = 0;
  entries.forEach((entry, index) => {
    varint(output, index && entry.offset === nextOffset ? 0 : entry.offset + 1);
    nextOffset = entry.offset + entry.length;
  });
  return Buffer.from(output);
}

function zxyToTileId(z, x, y) {
  const base = ((1 << z) * (1 << z) - 1) / 3;
  let order = 0,
    tx = x,
    ty = y;
  for (let size = 1 << (z - 1); size > 0; size >>= 1) {
    const rx = tx & size ? 1 : 0,
      ry = ty & size ? 1 : 0;
    order += size * size * ((3 * rx) ^ ry);
    if (!ry) {
      if (rx) [tx, ty] = [size - 1 - tx, size - 1 - ty];
      [tx, ty] = [ty, tx];
    }
  }
  return base + order;
}

function bounds(z, x, y) {
  const scale = 2 ** z,
    lon = (value) => (value / scale) * 360 - 180,
    lat = (value) => (180 / Math.PI) * Math.atan(Math.sinh(Math.PI * (1 - (2 * value) / scale)));
  return [lon(x), lat(y + 1), lon(x + 1), lat(y)];
}

async function copyRange(source, output, offset, length) {
  const buffer = Buffer.allocUnsafe(Math.min(1024 * 1024, length));
  let position = offset,
    remaining = length;
  while (remaining) {
    const count = Math.min(buffer.length, remaining);
    const { bytesRead } = await source.read(buffer, 0, count, position);
    if (!bytesRead) throw new Error("Unexpected end of export spool");
    if (!output.write(buffer.subarray(0, bytesRead)))
      await new Promise((resolve) => output.once("drain", resolve));
    position += bytesRead;
    remaining -= bytesRead;
  }
}

function header(records, root, metadata, leaves, tileBytes) {
  const result = Buffer.alloc(127),
    view = new DataView(result.buffer, result.byteOffset, result.byteLength);
  result.write("PMTiles");
  result[7] = 3;
  const rootOffset = 127,
    metadataOffset = rootOffset + root.length,
    leafOffset = metadataOffset + metadata.length,
    dataOffset = leafOffset + leaves.length;
  [
    rootOffset,
    root.length,
    metadataOffset,
    metadata.length,
    leafOffset,
    leaves.length,
    dataOffset,
    tileBytes,
    records.length,
    records.length,
    records.length,
  ].forEach((value, index) => view.setBigUint64(8 + index * 8, BigInt(value), true));
  result[96] = result[97] = result[98] = 1;
  result[99] = 2;
  let minZoom = 255,
    maxZoom = 0,
    west = 180,
    south = 90,
    east = -180,
    north = -90;
  for (const item of records) {
    minZoom = Math.min(minZoom, item.z);
    maxZoom = Math.max(maxZoom, item.z);
    const itemBounds = bounds(item.z, item.x, item.y);
    west = Math.min(west, itemBounds[0]);
    south = Math.min(south, itemBounds[1]);
    east = Math.max(east, itemBounds[2]);
    north = Math.max(north, itemBounds[3]);
  }
  result[100] = minZoom;
  result[101] = maxZoom;
  view.setInt32(102, Math.round(west * 1e7), true);
  view.setInt32(106, Math.round(south * 1e7), true);
  view.setInt32(110, Math.round(east * 1e7), true);
  view.setInt32(114, Math.round(north * 1e7), true);
  result[118] = Math.min(maxZoom, minZoom + 2);
  view.setInt32(119, Math.round(((west + east) / 2) * 1e7), true);
  view.setInt32(123, Math.round(((south + north) / 2) * 1e7), true);
  return result;
}

async function finishPmtiles(job) {
  const records = job.records.sort((a, b) => a.tileId - b.tileId);
  let dataOffset = 0;
  const entries = records.map((record) => ({
    tileId: record.tileId,
    offset: dataOffset,
    length: record.length,
    runLength: 1,
  }));
  for (const entry of entries) dataOffset += entry.length;
  let leafSize = 4096,
    root,
    leaves;
  for (;;) {
    const leafParts = [],
      rootEntries = [];
    let offset = 0;
    for (let start = 0; start < entries.length; start += leafSize) {
      const leaf = encodeDirectory(entries.slice(start, start + leafSize));
      leafParts.push(leaf);
      rootEntries.push({
        tileId: entries[start].tileId,
        offset,
        length: leaf.length,
        runLength: 0,
      });
      offset += leaf.length;
    }
    leaves = Buffer.concat(leafParts);
    root = encodeDirectory(rootEntries);
    if (root.length <= 16257) break;
    leafSize *= 2;
  }
  const metadata = Buffer.from(
    JSON.stringify({
      name: job.options.styleName,
      description: "MUI raster map tiles",
      attribution: job.options.attribution,
      type: "baselayer",
      version: "1.0.0",
    }),
  );
  const output = fs.createWriteStream(job.tempPath, { flags: "w" }),
    source = await open(job.spoolPath, "r");
  output.write(header(records, root, metadata, leaves, dataOffset));
  output.write(root);
  output.write(metadata);
  output.write(leaves);
  for (const record of records) await copyRange(source, output, record.offset, record.length);
  output.end();
  await new Promise((resolve, reject) => {
    output.once("close", resolve);
    output.once("error", reject);
  });
  await source.close();
}

function numberType(maximum) {
  return maximum <= 0xff ? "uint8_t" : maximum <= 0xffff ? "uint16_t" : "uint32_t";
}

function cString(value) {
  return JSON.stringify(value || "").replace(/\\u00a9/gi, "©");
}

async function writeText(output, text) {
  if (!output.write(text)) await new Promise((resolve) => output.once("drain", resolve));
}

async function writeArray(output, records, value) {
  await writeText(output, "{ ");
  for (let start = 0; start < records.length; start += 4096)
    await writeText(
      output,
      records
        .slice(start, start + 4096)
        .map((record, index) => `${start || index ? ", " : ""}${value(record)}`)
        .join(""),
    );
  await writeText(output, " };\n");
}
async function finishMtb(job) {
  const count = job.records.length,
    payloadBytes = job.offset;
  if (payloadBytes > 0xffffffff)
    throw new Error("InkHUD's MTB format uses 32-bit payload offsets and cannot exceed 4 GiB");
  if (job.kind === "inkhud-binary") {
    const output = await open(job.tempPath, "w"),
      fixed = Buffer.alloc(16 + count * 12),
      view = new DataView(fixed.buffer, fixed.byteOffset, fixed.byteLength);
    fixed.write(`MTB${job.options.depth}`);
    view.setUint32(8, count, true);
    view.setUint32(12, payloadBytes, true);
    let position = 16;
    for (const item of job.records) {
      fixed[position++] = item.z;
      view.setUint16(position, item.x, true);
      position += 2;
      view.setUint16(position, item.y, true);
      position += 2;
    }
    for (const item of job.records) {
      fixed[position++] = item.payloadKind;
      view.setUint16(position, item.length, true);
      position += 2;
      view.setUint32(position, item.payloadKind ? 0 : item.offset, true);
      position += 4;
    }
    await output.write(fixed);
    const source = await open(job.spoolPath, "r"),
      buffer = Buffer.allocUnsafe(Math.min(1024 * 1024, Math.max(1, payloadBytes)));
    let copied = 0;
    while (copied < payloadBytes) {
      const { bytesRead } = await source.read(
        buffer,
        0,
        Math.min(buffer.length, payloadBytes - copied),
        copied,
      );
      if (!bytesRead) throw new Error("Unexpected end of export spool");
      await output.write(buffer, 0, bytesRead);
      copied += bytesRead;
    }
    await source.close();
    await output.close();
  } else {
    const output = fs.createWriteStream(job.tempPath, { flags: "w" }),
      source = await open(job.spoolPath, "r"),
      maxima = job.records.reduce(
        (result, item) => ({
          z: Math.max(result.z, item.z),
          x: Math.max(result.x, item.x),
          y: Math.max(result.y, item.y),
        }),
        { z: 0, x: 0, y: 0 },
      );
    await writeText(
      output,
      `#pragma once\n#include <stdint.h>\n\n// ${job.options.style} InkHUD sparse tile export: ${count} tiles\nstatic const char map_tile_attribution[] = ${cString(job.options.sdCardAttribution)};\nstatic const char map_tile_license[] = ${cString(job.options.sdCardLicense)};\n\nstatic const uint8_t map_tile_bit_depth = ${job.options.depth};\nstatic const uint8_t map_tile_layout = 0;\nstatic const uint8_t map_tile_grid_cols = 0;\nstatic const uint8_t map_tile_grid_rows = 0;\nstatic const uint8_t map_tile_block_count = 0;\nstatic const ${count <= 0xffff ? "uint16_t" : "uint32_t"} map_tile_count = ${count};\nstatic const ${numberType(maxima.z)} map_tile_zooms[] = `,
    );
    await writeArray(output, job.records, (item) => item.z);
    await writeText(output, `static const ${numberType(maxima.x)} map_tile_tx[] = `);
    await writeArray(output, job.records, (item) => item.x);
    await writeText(output, `static const ${numberType(maxima.y)} map_tile_ty[] = `);
    await writeArray(output, job.records, (item) => item.y);
    await writeText(
      output,
      "static const uint8_t map_tile_block_zooms[] = {};\nstatic const uint16_t map_tile_block_tx[] = {};\nstatic const uint16_t map_tile_block_ty[] = {};\nstatic const uint8_t map_tile_kinds[] = ",
    );
    await writeArray(output, job.records, (item) => item.payloadKind);
    await writeText(output, "static const uint16_t map_tile_sizes[] = ");
    await writeArray(output, job.records, (item) => item.length);
    await writeText(output, "static const uint32_t map_tile_offsets[] = ");
    await writeArray(output, job.records, (item) => {
      return item.payloadKind ? 0 : item.offset;
    });
    await writeText(output, "\nstatic const uint8_t map_tile_data[] = {\n");
    const buffer = Buffer.allocUnsafe(4096);
    let position = 0;
    while (position < payloadBytes) {
      const { bytesRead } = await source.read(
        buffer,
        0,
        Math.min(buffer.length, payloadBytes - position),
        position,
      );
      await writeText(
        output,
        [...buffer.subarray(0, bytesRead)]
          .map((byte) => `0x${byte.toString(16).toUpperCase().padStart(2, "0")},`)
          .join(" ") + "\n",
      );
      position += bytesRead;
    }
    if (!payloadBytes) output.write("0x00,\n");
    output.end("};\n");
    await new Promise((resolve, reject) => {
      output.once("close", resolve);
      output.once("error", reject);
    });
    await source.close();
  }
}

async function finishMtbBundle(job) {
  const binaryPath = `${job.tempPath}.bin`;
  await finishMtb({ ...job, tempPath: binaryPath });
  const { archive, output, failure } = createZipWriter(job.tempPath),
    closed = new Promise((resolve, reject) => {
      output.once("close", resolve);
      output.once("error", reject);
    });
  archive.file(binaryPath, { name: "Map/MapTile.bin" });
  archive.append(job.options.sdCardLicense, { name: "LICENSE.txt" });
  archive.append(job.options.sdCardAttribution, { name: "ATTRIBUTION.txt" });
  try {
    await archive.finalize();
    await Promise.race([closed, failure]);
  } finally {
    await unlink(binaryPath).catch(() => {});
  }
}

module.exports = {
  createZipWriter,
  finishMtb,
  finishMtbBundle,
  finishPmtiles,
  planMtbPayload,
  zxyToTileId,
};
