import { createHash, timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";

const PROVIDER = "open-jev-selfhost";
const TRANSFORM_VERSION = "coursejesus-openjev-input.v1";
const MAX_SEQUENCE_TOKENS = 512;
const MAX_STATE_TOKENS = 256;
const RESERVED_MARKER = /\[(?:STATE|Q|OPT)\]/u;

function json(response, status, payload) {
  const body = JSON.stringify(payload);
  response.writeHead(status, {
    "cache-control": "no-store",
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

function authorized(request, token) {
  const value = request.headers.authorization ?? "";
  const expected = `Bearer ${token}`;
  const left = Buffer.from(value);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(
        ([key, item]) => [key, sorted(item)],
      ),
    );
  }
  return value;
}

function canonical(value) {
  return JSON.stringify(sorted(value));
}

function detectLanguage(text) {
  const hasChinese = /[\u3400-\u9fff]/u.test(text);
  const hasLatin = /[A-Za-z]/u.test(text);
  if (hasChinese && hasLatin) return "mixed";
  return hasChinese ? "zh" : "en";
}

function contentText(value) {
  if (typeof value === "string") {
    // Structured state contains enum/id values such as `short_answer` and
    // node ids. They are schema, not learner language, and must not turn an
    // otherwise Chinese payload into a mixed-language claim.
    return /^[A-Za-z0-9_.:-]+$/u.test(value) ? "" : value;
  }
  if (Array.isArray(value)) return value.map(contentText).join(" ");
  if (value && typeof value === "object") {
    return Object.values(value).map(contentText).join(" ");
  }
  return "";
}

function validId(value, min = 1, max = 160) {
  return typeof value === "string" && value.length >= min && value.length <= max &&
    /^[A-Za-z0-9_.:-]+$/u.test(value);
}

function safeText(value, max = 16_000) {
  return typeof value === "string" && value.length > 0 && value.length <= max &&
    !RESERVED_MARKER.test(value);
}

function parseQuestion(key, value) {
  if (!value || typeof value !== "object" || !safeText(value.instructions, 4_000)) {
    throw new RequestError("INVALID_QUESTION", `Invalid question ${key}`);
  }
  if (value.primitive === "Choice") {
    if (!Array.isArray(value.options) || value.options.length < 2 || value.options.length > 16) {
      throw new RequestError("INVALID_QUESTION", `Invalid Choice options for ${key}`);
    }
    const options = value.options.map(String);
    if (new Set(options).size !== options.length || options.some((item) => !safeText(item, 160))) {
      throw new RequestError("INVALID_QUESTION", `Invalid Choice option for ${key}`);
    }
    const descriptions = value.descriptions;
    if (descriptions && (
      typeof descriptions !== "object" ||
      Object.entries(descriptions).some(([option, description]) =>
        !options.includes(option) || !safeText(description, 1_000)
      )
    )) {
      throw new RequestError("INVALID_QUESTION", `Invalid Choice descriptions for ${key}`);
    }
    return {
      type: "choice",
      instructions: value.instructions,
      options,
      ...(descriptions ? { descriptions } : {}),
    };
  }
  if (value.primitive === "Score") {
    if (!Array.isArray(value.options) || value.options.length < 2 || value.options.length > 16) {
      throw new RequestError("INVALID_QUESTION", `Invalid Score levels for ${key}`);
    }
    return { type: "score", instructions: value.instructions, options: value.options.map(String) };
  }
  if (value.primitive === "Noul") {
    return { type: "noul", instructions: value.instructions };
  }
  throw new RequestError("INVALID_QUESTION", `Unknown primitive for ${key}`);
}

function parseRequest(payload, model) {
  if (!payload || typeof payload !== "object") {
    throw new RequestError("INVALID_REQUEST", "Request body must be an object");
  }
  for (const field of ["request_id", "operation_id"]) {
    if (!validId(payload[field], 8)) throw new RequestError("INVALID_REQUEST", `Invalid ${field}`);
  }
  if (!validId(payload.case_id, 3) || !validId(payload.case_version, 1)) {
    throw new RequestError("INVALID_REQUEST", "Invalid case identity");
  }
  if (typeof payload.scope_digest !== "string" || !/^[a-f0-9]{64}$/u.test(payload.scope_digest)) {
    throw new RequestError("INVALID_REQUEST", "Invalid scope_digest");
  }
  if (payload.truncation !== "error") {
    throw new RequestError("TRUNCATION_FORBIDDEN", "truncation must be error");
  }
  if (!["en", "zh", "mixed"].includes(payload.source_language)) {
    throw new RequestError("INVALID_LANGUAGE", "Invalid source_language");
  }
  if (payload.input_transform_version !== TRANSFORM_VERSION) {
    throw new RequestError("INVALID_TRANSFORM", "Unsupported input transform");
  }
  if (!payload.state || typeof payload.state !== "object" || Array.isArray(payload.state)) {
    throw new RequestError("INVALID_STATE", "state must be an object");
  }
  const state = canonical(payload.state);
  if (state.length > 64_000 || RESERVED_MARKER.test(state)) {
    throw new RequestError("INVALID_STATE", "State is too large or contains reserved markers");
  }
  if (detectLanguage(contentText(payload.state)) !== payload.source_language) {
    throw new RequestError("LANGUAGE_MISMATCH", "source_language does not match the state");
  }
  if (!payload.questions || typeof payload.questions !== "object" || Array.isArray(payload.questions)) {
    throw new RequestError("INVALID_QUESTIONS", "questions must be an object");
  }
  const entries = Object.entries(payload.questions);
  if (entries.length !== 1 || entries[0][0] !== payload.case_id) {
    throw new RequestError("INVALID_QUESTIONS", "Exactly one case-matched question is required");
  }
  const questions = Object.fromEntries(entries.map(([key, value]) => [key, parseQuestion(key, value)]));
  const stateTokens = model.countTokens(state);
  const questionTokens = entries.reduce((total, [, value]) => {
    const optionText = Array.isArray(value.options) ? value.options.join(" ") : "no yes";
    const descriptions = value.descriptions ? canonical(value.descriptions) : "";
    return total + model.countTokens(`${value.instructions} ${optionText} ${descriptions}`) + 8;
  }, 4);
  if (stateTokens > MAX_STATE_TOKENS || stateTokens + questionTokens > MAX_SEQUENCE_TOKENS) {
    throw new RequestError("INPUT_TOO_LONG", "Input does not fit the fixed 512-token model context");
  }
  const servedLanguage = detectLanguage(`${state} ${canonical(payload.questions)}`);
  return { state, stateTokens, questionTokens, questions, servedLanguage };
}

function validateAnswers(answers, questions) {
  if (!answers || typeof answers !== "object") {
    throw new Error("Model returned no answer object");
  }
  for (const [key, question] of Object.entries(questions)) {
    const answer = answers[key];
    if (!answer || answer.type !== question.type) throw new Error(`Invalid answer ${key}`);
    if (question.type === "choice") {
      const probabilities = answer.probabilities;
      if (!probabilities || new Set(Object.keys(probabilities)).size !== question.options.length ||
          question.options.some((option) => !(option in probabilities))) {
        throw new Error(`Invalid answer distribution ${key}`);
      }
      const values = Object.values(probabilities);
      if (values.some((value) => typeof value !== "number" || !Number.isFinite(value) || value < 0 || value > 1) ||
          Math.abs(values.reduce((sum, value) => sum + value, 0) - 1) > 1e-6 ||
          !question.options.includes(answer.choice)) {
        throw new Error(`Invalid answer probability contract ${key}`);
      }
    }
  }
}

async function readBody(request, maxBodyBytes) {
  const chunks = [];
  let size = 0;
  for await (const chunk of request) {
    size += chunk.length;
    if (size > maxBodyBytes) throw new RequestError("PAYLOAD_TOO_LARGE", "Request body too large", 413);
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new RequestError("INVALID_JSON", "Request body is not valid JSON");
  }
}

class RequestError extends Error {
  constructor(code, message, status = 422) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function createOpenJevServer({
  token,
  modelManifest,
  loadModel,
  queueLimit = 8,
  maxBodyBytes = 128 * 1024,
}) {
  if (!token || token.length < 8) throw new Error("A protected service token is required");
  if (!modelManifest?.revision || !modelManifest?.weightsHash || !modelManifest?.tokenizerHash) {
    throw new Error("A frozen model manifest is required");
  }
  let model = null;
  let loadError = null;
  let outstanding = 0;
  let inferenceTail = Promise.resolve();
  const ready = Promise.resolve().then(loadModel).then(async (loaded) => {
    if (loaded.runtime?.family !== "open-jev" || loaded.runtime?.dtype !== modelManifest.dtype) {
      throw new Error("Loaded runtime does not match the frozen DeBERTa manifest");
    }
    model = loaded;
    return loaded;
  }).catch((error) => {
    loadError = error;
    throw error;
  });
  // A rejected readiness promise is observed here as well as by /ready so the
  // process does not emit an unhandled-rejection warning before the first probe.
  ready.catch(() => undefined);

  const server = createServer(async (request, response) => {
    try {
      const url = new URL(request.url ?? "/", "http://127.0.0.1");
      if (request.method === "GET" && url.pathname === "/health") {
        return json(response, 200, { status: "alive", service: "coursejesus-openjev" });
      }
      if (request.method === "GET" && url.pathname === "/ready") {
        if (loadError) return json(response, 503, { status: "not_ready", code: "MODEL_LOAD_FAILED" });
        if (!model) return json(response, 503, { status: "loading" });
        return json(response, 200, { status: "ready", saturated: outstanding >= queueLimit });
      }
      if (request.method === "GET" && url.pathname === "/version") {
        if (!authorized(request, token)) return json(response, 401, { error: { code: "UNAUTHORIZED" } });
        return json(response, 200, { provider: PROVIDER, model: modelManifest });
      }
      if (request.method !== "POST" || url.pathname !== "/v1/decisions") {
        return json(response, 404, { error: { code: "NOT_FOUND" } });
      }
      if (!authorized(request, token)) return json(response, 401, { error: { code: "UNAUTHORIZED" } });
      if (!model) return json(response, 503, { error: { code: "MODEL_NOT_READY" } });
      if (outstanding >= queueLimit) return json(response, 429, { error: { code: "QUEUE_FULL" } });
      const payload = await readBody(request, maxBodyBytes);
      const prepared = parseRequest(payload, model);
      outstanding += 1;
      const queuedAt = performance.now();
      const previous = inferenceTail;
      let releaseInference;
      inferenceTail = new Promise((resolveRelease) => {
        releaseInference = resolveRelease;
      });
      try {
        await previous.catch(() => undefined);
        const startedAt = performance.now();
        try {
          const answers = await model.decide(prepared.state, prepared.questions, {
            maxStateTokens: MAX_STATE_TOKENS,
            truncation: "error",
          });
          validateAnswers(answers, prepared.questions);
          return json(response, 200, {
            status: "COMPLETED",
            provider: PROVIDER,
            request_id: payload.request_id,
            model: {
              id: modelManifest.id,
              revision: modelManifest.revision,
              dtype: modelManifest.dtype,
              library_commit: modelManifest.libraryCommit,
              tokenizer_hash: modelManifest.tokenizerHash,
              weights_hash: modelManifest.weightsHash,
            },
            input: {
              truncated: false,
              source_language: payload.source_language,
              served_language: prepared.servedLanguage,
              transform_version: TRANSFORM_VERSION,
              state_tokens: prepared.stateTokens,
              estimated_total_tokens: prepared.stateTokens + prepared.questionTokens,
              model_input_hash: createHash("sha256").update(
                canonical({ state: prepared.state, questions: payload.questions }),
              ).digest("hex"),
            },
            answers,
            timing: {
              queue_ms: Math.max(0, startedAt - queuedAt),
              inference_ms: Math.max(0, performance.now() - startedAt),
            },
          });
        } finally {
          releaseInference();
        }
      } finally {
        outstanding -= 1;
      }
    } catch (error) {
      if (error instanceof RequestError) {
        return json(response, error.status, { error: { code: error.code, message: error.message } });
      }
      return json(response, 503, { error: { code: "INFERENCE_FAILED" } });
    }
  });

  return {
    server,
    ready,
    async close() {
      await new Promise((resolve) => server.close(resolve));
      try { await ready; } catch { return; }
      await model?.dispose?.();
    },
  };
}

export const constants = Object.freeze({
  PROVIDER,
  TRANSFORM_VERSION,
  MAX_SEQUENCE_TOKENS,
  MAX_STATE_TOKENS,
});
