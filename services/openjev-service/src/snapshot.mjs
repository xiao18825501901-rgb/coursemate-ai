import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { lstat, readdir } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";

export const digestFile = (path) => new Promise((resolveDigest, reject) => {
  const hash = createHash("sha256");
  const stream = createReadStream(path);
  stream.on("error", reject);
  stream.on("data", (chunk) => hash.update(chunk));
  stream.on("end", () => resolveDigest(hash.digest("hex")));
});

export function groupHash(entries, prefixes) {
  const selected = entries
    .filter((entry) => prefixes.some((prefix) => entry.path.startsWith(prefix)))
    .sort((left, right) => left.path.localeCompare(right.path));
  if (selected.length === 0) throw new Error("model manifest hash group is empty");
  const canonical = selected
    .map((entry) => `${entry.path}\0${entry.bytes}\0${entry.sha256}\n`)
    .join("");
  return createHash("sha256").update(canonical).digest("hex");
}

async function snapshotFiles(root, directory = root) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isSymbolicLink()) {
      throw new Error(`model snapshot contains symlink: ${entry.name}`);
    }
    if (entry.isDirectory()) {
      files.push(...await snapshotFiles(root, path));
    } else if (entry.isFile()) {
      files.push(relative(root, path).split(sep).join("/"));
    } else {
      throw new Error(`model snapshot contains non-regular entry: ${entry.name}`);
    }
  }
  return files;
}

export async function verifySnapshot(root, manifest) {
  if (!Array.isArray(manifest.files) || manifest.files.length === 0) {
    throw new Error("model manifest must list frozen files");
  }
  const absoluteRoot = resolve(root);
  const declared = new Set(manifest.files.map((entry) => entry.path));
  const actualFiles = await snapshotFiles(absoluteRoot);
  const unexpected = actualFiles.filter(
    (path) => path !== "COURSEJESUS_MODEL_MANIFEST.json" && !declared.has(path),
  );
  if (unexpected.length > 0) {
    throw new Error(`model snapshot contains undeclared files: ${unexpected.join(", ")}`);
  }
  for (const entry of manifest.files) {
    const relative = typeof entry?.path === "string" ? entry.path.replaceAll("\\", "/") : "";
    const path = resolve(absoluteRoot, relative);
    if (!relative || relative.startsWith("/") || relative.includes("../") ||
        (path !== absoluteRoot && !path.startsWith(`${absoluteRoot}${sep}`))) {
      throw new Error(`unsafe model file path: ${relative || "<empty>"}`);
    }
    const status = await lstat(path);
    if (!status.isFile() || status.isSymbolicLink()) {
      throw new Error(`model snapshot entry is not a regular file: ${relative}`);
    }
    if (status.size !== entry.bytes) {
      throw new Error(`model file size mismatch: ${relative}`);
    }
    const actual = await digestFile(path);
    if (actual !== entry.sha256) {
      throw new Error(`model file hash mismatch: ${relative}`);
    }
  }
  if (manifest.weightsHash !== groupHash(manifest.files, ["onnx/"]) ||
      manifest.tokenizerHash !== groupHash(manifest.files, ["tokenizer"])) {
    throw new Error("model manifest aggregate hash mismatch");
  }
}
