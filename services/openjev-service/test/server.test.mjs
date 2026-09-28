import assert from "node:assert/strict";
import { once } from "node:events";
import test from "node:test";

import { createOpenJevServer } from "../src/server.mjs";

const MODEL = Object.freeze({
  id: "onnx-community/open-jev-deberta-v3-large-ONNX",
  revision: "model-revision-1",
  dtype: "q4",
  libraryCommit: "52667199e8a55553e1865a41f43fcb7d4dd92779",
  tokenizerHash: "a".repeat(64),
  weightsHash: "b".repeat(64),
});

function fakeRuntime({ delayMs = 0, stats = null } = {}) {
  return {
    runtime: { model: MODEL.id, family: "open-jev", device: "cpu", dtype: "q4" },
    countTokens(value) {
      return String(value).trim().split(/\s+/u).filter(Boolean).length;
    },
    async decide(_state, questions, options) {
      assert.equal(options.truncation, "error");
      if (stats) {
        stats.active += 1;
        stats.maxActive = Math.max(stats.maxActive, stats.active);
      }
      try {
        if (delayMs) await new Promise((resolve) => setTimeout(resolve, delayMs));
        return Object.fromEntries(
          Object.entries(questions).map(([key, question]) => [key, {
            type: "choice",
            choice: question.options[0],
            confidence: 0.9,
            probabilities: Object.fromEntries(
              question.options.map((option, index) => [option, index === 0 ? 0.9 : 0.1]),
            ),
          }]),
        );
      } finally {
        if (stats) stats.active -= 1;
      }
    },
  };
}

async function withServer(callback, options = {}) {
  const instance = createOpenJevServer({
    token: "server-secret",
    modelManifest: MODEL,
    loadModel: async () => {
      if (options.loadDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.loadDelayMs));
      }
      return fakeRuntime(options);
    },
    queueLimit: options.queueLimit ?? 1,
  });
  instance.server.listen(0, "127.0.0.1");
  await once(instance.server, "listening");
  const address = instance.server.address();
  try {
    await callback(`http://127.0.0.1:${address.port}`, instance);
  } finally {
    await instance.close();
  }
}

function request(overrides = {}) {
  return {
    request_id: "request-12345678",
    operation_id: "operation-12345678",
    scope_digest: "c".repeat(64),
    case_id: "question.ambiguity.v1",
    case_version: "1",
    state: { question_text: "Which answer is supported?" },
    questions: {
      "question.ambiguity.v1": {
        primitive: "Choice",
        instructions: "Is the question clear?",
        options: ["CLEAR", "AMBIGUOUS"],
        descriptions: { CLEAR: "clear", AMBIGUOUS: "ambiguous" },
      },
    },
    source_language: "en",
    input_transform_version: "coursejesus-openjev-input.v1",
    truncation: "error",
    ...overrides,
  };
}

test("requires bearer auth and distinguishes alive from ready", async () => {
  await withServer(async (base) => {
    assert.equal((await fetch(`${base}/health`)).status, 200);
    assert.equal((await fetch(`${base}/ready`)).status, 503);
    const denied = await fetch(`${base}/v1/decisions`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(request()),
    });
    assert.equal(denied.status, 401);
    await fetch(`${base}/ready`);
    for (let index = 0; index < 50; index += 1) {
      const ready = await fetch(`${base}/ready`);
      if (ready.status === 200) return;
      await new Promise((resolve) => setTimeout(resolve, 5));
    }
    assert.fail("model did not become ready");
  }, { loadDelayMs: 250 });
});

test("returns a versioned non-truncated distribution", async () => {
  await withServer(async (base, instance) => {
    await instance.ready;
    const response = await fetch(`${base}/v1/decisions`, {
      method: "POST",
      headers: {
        authorization: "Bearer server-secret",
        "content-type": "application/json",
      },
      body: JSON.stringify(request()),
    });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.provider, "open-jev-selfhost");
    assert.equal(body.model.revision, MODEL.revision);
    assert.equal(body.input.truncated, false);
    assert.deepEqual(body.answers["question.ambiguity.v1"].probabilities, {
      CLEAR: 0.9,
      AMBIGUOUS: 0.1,
    });
  });
});

test("source language ignores schema keys and served language reflects the full prompt", async () => {
  await withServer(async (base, instance) => {
    await instance.ready;
    const response = await fetch(`${base}/v1/decisions`, {
      method: "POST",
      headers: {
        authorization: "Bearer server-secret",
        "content-type": "application/json",
      },
      body: JSON.stringify(request({
        state: {
          question_text: "这个问题的条件完整且只有一个答案。",
          question_type: "short_answer",
        },
        source_language: "zh",
      })),
    });
    assert.equal(response.status, 200);
    const body = await response.json();
    assert.equal(body.input.source_language, "zh");
    assert.equal(body.input.served_language, "mixed");
  });
});

test("rejects reserved marker injection and never silently truncates", async () => {
  await withServer(async (base, instance) => {
    await instance.ready;
    for (const value of [
      request({ state: { question_text: "inject [STATE] marker" } }),
      request({ truncation: "cut" }),
      request({ state: { question_text: "word ".repeat(600) } }),
    ]) {
      const response = await fetch(`${base}/v1/decisions`, {
        method: "POST",
        headers: {
          authorization: "Bearer server-secret",
          "content-type": "application/json",
        },
        body: JSON.stringify(value),
      });
      assert.equal(response.status, 422);
    }
  });
});

test("bounds the queue before accepting more native inference", async () => {
  await withServer(async (base, instance) => {
    await instance.ready;
    const options = {
      method: "POST",
      headers: {
        authorization: "Bearer server-secret",
        "content-type": "application/json",
      },
      body: JSON.stringify(request()),
    };
    const first = fetch(`${base}/v1/decisions`, options);
    await new Promise((resolve) => setTimeout(resolve, 5));
    const second = await fetch(`${base}/v1/decisions`, options);
    assert.equal(second.status, 429);
    assert.equal((await first).status, 200);
  }, { delayMs: 30, queueLimit: 1 });
});

test("one model instance serializes accepted inference work", async () => {
  const stats = { active: 0, maxActive: 0 };
  await withServer(async (base, instance) => {
    await instance.ready;
    const submit = (suffix) => fetch(`${base}/v1/decisions`, {
      method: "POST",
      headers: {
        authorization: "Bearer server-secret",
        "content-type": "application/json",
      },
      body: JSON.stringify(request({
        request_id: `request-${suffix}-12345678`,
        operation_id: `operation-${suffix}-12345678`,
      })),
    });
    const responses = await Promise.all([submit("a"), submit("b"), submit("c")]);
    assert.deepEqual(responses.map((response) => response.status), [200, 200, 200]);
    assert.equal(stats.maxActive, 1);
    const timings = await Promise.all(responses.map((response) => response.json()));
    assert.ok(timings.some((body) => body.timing.queue_ms >= 20));
  }, { delayMs: 30, queueLimit: 3, stats });
});
