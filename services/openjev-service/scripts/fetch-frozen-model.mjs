import { createHash } from "node:crypto";
import { createWriteStream } from "node:fs";
import { mkdir, rename, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { Readable } from "node:stream";

import { digestFile, groupHash } from "../src/snapshot.mjs";

const MODEL_ID = "onnx-community/open-jev-deberta-v3-large-ONNX";
const REVISION = "7c79f25b5ac496089f448a969c801872ad59d31c";
const FILES = [
  {
    path: "config.json",
    bytes: 1563,
    sha256: "2ec35432332ee6b5880509eefe44e6279fd9d3543f6ba96098119ffe0b0c2d5e",
  },
  {
    path: "onnx/model_q4.onnx",
    bytes: 601293,
    sha256: "5be15f8076cc2c16d76fb2e9c8703a0d7d355950422ce47e8dae072ce9ca3b8e",
  },
  {
    path: "onnx/model_q4.onnx_data",
    bytes: 477415936,
    sha256: "886cf56af0dd14b6938415af724eb48e5a5d5db3c728c05b50702585c0ea29ab",
  },
  {
    path: "tokenizer.json",
    bytes: 8657170,
    sha256: "cd119378b0160677b7a1e561ba29ada83918c1d420b326516a585382e83d9d39",
  },
  {
    path: "tokenizer_config.json",
    bytes: 1907,
    sha256: "52e0421535dd20e51dd25f4ce965cf2689a7392956f84ca4867667efab600340",
  },
];
const root = resolve(process.argv[2] ?? "model/open-jev-deberta-v3-large-ONNX");
await mkdir(root, { recursive: true });

const entries = [];
for (const expected of FILES) {
  const relative = expected.path;
  const destination = join(root, ...relative.split("/"));
  const partial = `${destination}.part`;
  await mkdir(dirname(destination), { recursive: true });
  await rm(partial, { force: true });
  try {
    const saved = await stat(destination);
    if (saved.isFile() && saved.size > 0) {
      const sha256 = await digestFile(destination);
      if (saved.size !== expected.bytes || sha256 !== expected.sha256) {
        throw new Error(`existing frozen file mismatch for ${relative}`);
      }
      entries.push(expected);
      process.stdout.write(`${relative} ${saved.size} reused\n`);
      continue;
    }
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
  const url = `https://huggingface.co/${MODEL_ID}/resolve/${REVISION}/${relative}`;
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok || !response.body) {
    throw new Error(`download failed ${response.status} for ${relative}`);
  }
  const hash = createHash("sha256");
  let bytes = 0;
  const output = createWriteStream(partial, { flags: "wx", mode: 0o600 });
  const source = Readable.fromWeb(response.body);
  source.on("data", (chunk) => {
    bytes += chunk.length;
    hash.update(chunk);
  });
  await new Promise((resolveCopy, reject) => {
    source.on("error", reject);
    output.on("error", reject);
    output.on("finish", resolveCopy);
    source.pipe(output);
  });
  await rename(partial, destination);
  const saved = await stat(destination);
  if (saved.size !== bytes) throw new Error(`saved size mismatch for ${relative}`);
  const sha256 = hash.digest("hex");
  if (bytes !== expected.bytes || sha256 !== expected.sha256) {
    await rm(destination, { force: true });
    throw new Error(`downloaded frozen file mismatch for ${relative}`);
  }
  entries.push(expected);
  process.stdout.write(`${relative} ${bytes}\n`);
}

const manifest = {
  schema: "coursejesus.openjev-model-snapshot.v1",
  id: MODEL_ID,
  revision: REVISION,
  libraryCommit: "52667199e8a55553e1865a41f43fcb7d4dd92779",
  transformersVersion: "4.3.0",
  dtype: "q4",
  maxLength: 512,
  maxStateTokens: 256,
  weightsHash: groupHash(entries, ["onnx/"]),
  tokenizerHash: groupHash(entries, ["tokenizer"]),
  files: entries,
};
await writeFile(
  join(root, "COURSEJESUS_MODEL_MANIFEST.json"),
  `${JSON.stringify(manifest, null, 2)}\n`,
  { encoding: "utf8", mode: 0o600 },
);
process.stdout.write(`${join(root, "COURSEJESUS_MODEL_MANIFEST.json")}\n`);
