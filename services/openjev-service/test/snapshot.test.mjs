import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { groupHash, verifySnapshot } from "../src/snapshot.mjs";

test("a frozen snapshot requires every exact file hash", async () => {
  const root = await mkdtemp(join(tmpdir(), "openjev-snapshot-"));
  await mkdir(join(root, "onnx"));
  await writeFile(join(root, "onnx", "model_q4.onnx"), "fixed-content");
  await writeFile(join(root, "tokenizer.json"), "fixed-content");
  const sha256 = createHash("sha256").update("fixed-content").digest("hex");
  const manifest = {
    id: "onnx-community/open-jev-deberta-v3-large-ONNX",
    revision: "hf-commit-1",
    libraryCommit: "52667199e8a55553e1865a41f43fcb7d4dd92779",
    transformersVersion: "4.3.0",
    dtype: "q4",
    files: [
      { path: "onnx/model_q4.onnx", bytes: 13, sha256 },
      { path: "tokenizer.json", bytes: 13, sha256 },
    ],
  };
  manifest.weightsHash = groupHash(manifest.files, ["onnx/"]);
  manifest.tokenizerHash = groupHash(manifest.files, ["tokenizer"]);

  await assert.doesNotReject(verifySnapshot(root, manifest));
  await writeFile(join(root, "undeclared.json"), "{}\n");
  await assert.rejects(verifySnapshot(root, manifest), /undeclared files/);
  await rm(join(root, "undeclared.json"));
  await writeFile(join(root, "onnx", "model_q4.onnx"), "tampered-data");
  await assert.rejects(verifySnapshot(root, manifest), /hash mismatch/);
});

test("snapshot paths cannot escape the frozen root", async () => {
  const root = await mkdtemp(join(tmpdir(), "openjev-snapshot-"));
  await assert.rejects(
    verifySnapshot(root, {
      weightsHash: "0".repeat(64),
      tokenizerHash: "0".repeat(64),
      files: [{ path: "../secret", bytes: 1, sha256: "0".repeat(64) }],
    }),
    /unsafe model file path/,
  );
});
