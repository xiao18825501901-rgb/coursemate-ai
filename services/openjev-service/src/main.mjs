import { readFile } from "node:fs/promises";
import process from "node:process";

import { env } from "@huggingface/transformers";
import { OpenJev } from "open-jev";

import { createOpenJevServer } from "./server.mjs";
import { verifySnapshot } from "./snapshot.mjs";

const required = (name) => {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required`);
  return value;
};

const manifestPath = required("OPENJEV_MODEL_MANIFEST");
const modelPath = required("OPENJEV_MODEL_PATH");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
if (manifest.id !== "onnx-community/open-jev-deberta-v3-large-ONNX" ||
    manifest.revision !== "7c79f25b5ac496089f448a969c801872ad59d31c" ||
    manifest.libraryCommit !== "52667199e8a55553e1865a41f43fcb7d4dd92779" ||
    manifest.transformersVersion !== "4.3.0" ||
    manifest.dtype !== "q4") {
  throw new Error("The model manifest does not match the reviewed OpenJev candidate");
}
await verifySnapshot(modelPath, manifest);

env.allowRemoteModels = false;
env.allowLocalModels = true;
env.useBrowserCache = false;
env.cacheDir = required("OPENJEV_CACHE_DIR");

const queueLimit = Number(process.env.OPENJEV_QUEUE_LIMIT ?? "8");
const instance = createOpenJevServer({
  token: required("OPENJEV_BEARER_TOKEN"),
  modelManifest: manifest,
  queueLimit,
  maxBodyBytes: Number(process.env.OPENJEV_MAX_BODY_BYTES ?? String(128 * 1024)),
  loadModel: () => OpenJev.load({
    model: modelPath,
    device: "cpu",
    dtype: "q4",
    maxLength: 512,
    maxStateTokens: 256,
    truncation: "error",
  }),
});

const host = process.env.OPENJEV_HOST ?? "127.0.0.1";
const port = Number(process.env.OPENJEV_PORT ?? "8765");
// Native ONNX inference is synchronous on CPU. Keep the kernel pending-connection
// backlog equal to the service admission bound so a busy model cannot accumulate
// hundreds of hidden requests while the event loop is inside native inference.
instance.server.listen(port, host, queueLimit);
await instance.ready;

const stop = async () => {
  await instance.close();
  process.exit(0);
};
process.once("SIGTERM", stop);
process.once("SIGINT", stop);
