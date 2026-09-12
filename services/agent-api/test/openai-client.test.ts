import type OpenAI from "openai";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentError } from "../src/errors.js";
import { OpenAIResponsesClient } from "../src/openai/client.js";
import { TOOL_DEFINITIONS } from "../src/tools/schemas.js";


const { sdkConstructor } = vi.hoisted(() => ({ sdkConstructor: vi.fn() }));

vi.mock("openai", () => ({
  default: class MockOpenAI {
    readonly responses = { create: vi.fn() };

    constructor(options: unknown) {
      sdkConstructor(options);
    }
  },
}));

const request = {
  model: "test-model",
  instructions: "Use tools when needed.",
  input: [{ role: "user", content: "List my tasks" }],
  tools: TOOL_DEFINITIONS,
  parallelToolCalls: false as const,
};

describe("OpenAIResponsesClient", () => {
  beforeEach(() => sdkConstructor.mockClear());

  it("passes a custom base URL to the OpenAI SDK", () => {
    new OpenAIResponsesClient(
      "placeholder-key",
      undefined,
      "https://workspace.example.com/compatible-mode/v1",
    );

    expect(sdkConstructor).toHaveBeenCalledWith({
      apiKey: "placeholder-key",
      baseURL: "https://workspace.example.com/compatible-mode/v1",
      maxRetries: 0,
      timeout: 90_000,
    });
  });

  it("preserves the SDK default when the base URL is absent", () => {
    new OpenAIResponsesClient("placeholder-key");

    expect(sdkConstructor).toHaveBeenCalledWith({
      apiKey: "placeholder-key",
      maxRetries: 0,
      timeout: 90_000,
    });
  });

  it("keeps an injected client and existing Responses request behavior", async () => {
    const create = vi.fn().mockResolvedValue({ output_text: "Done", output: [] });
    const injected = { responses: { create } } as unknown as OpenAI;
    const client = new OpenAIResponsesClient(
      "placeholder-key",
      injected,
      "https://ignored.example.com/v1",
    );

    const response = await client.create(request);

    expect(sdkConstructor).not.toHaveBeenCalled();
    expect(create).toHaveBeenCalledWith(expect.objectContaining({
      model: "test-model",
      parallel_tool_calls: false,
      max_output_tokens: 1_200,
      store: false,
    }));
    expect(response).toEqual({ outputText: "Done", output: [] });
  });

  it("turns provider failures into a content-free Agent error", async () => {
    const create = vi.fn().mockRejectedValue(
      new Error("secret provider body containing private student material"),
    );
    const injected = { responses: { create } } as unknown as OpenAI;
    const client = new OpenAIResponsesClient("placeholder-key", injected);

    let failure: unknown;
    try {
      await client.create(request);
    } catch (error) {
      failure = error;
    }

    expect(failure).toBeInstanceOf(AgentError);
    expect(failure).toMatchObject({ code: "MODEL_PROVIDER_FAILURE" });
    expect(String(failure)).not.toContain("private student material");
  });
});
