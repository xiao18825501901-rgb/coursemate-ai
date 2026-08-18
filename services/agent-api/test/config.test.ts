import { describe, expect, it } from "vitest";

import { loadConfig } from "../src/config.js";


describe("Agent security configuration", () => {
  it("fails closed without Clerk credentials", () => {
    expect(() => loadConfig({})).toThrow(/CLERK_PUBLISHABLE_KEY/);
  });

  it("allows the fixed test adapter only in test deterministic mode", () => {
    const config = loadConfig({
      NODE_ENV: "test",
      AGENT_PROVIDER_MODE: "deterministic",
      AUTH_TEST_USER_ID: "e2e-user",
    });
    expect(config.authTestUserId).toBe("e2e-user");
    expect(() => loadConfig({
      NODE_ENV: "production",
      AGENT_PROVIDER_MODE: "deterministic",
      AUTH_TEST_USER_ID: "e2e-user",
    })).toThrow(/only in test deterministic mode/);
  });

  it("uses the platform PORT when AGENT_PORT is absent", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      PORT: "10000",
    });
    expect(config.port).toBe(10_000);
  });

  it("binds to loopback by default", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
    });
    expect(config.host).toBe("127.0.0.1");
  });

  it("allows an explicit Agent bind host", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      AGENT_HOST: "0.0.0.0",
    });
    expect(config.host).toBe("0.0.0.0");
  });
  it("loads a custom OpenAI-compatible base URL", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      OPENAI_BASE_URL: "https://workspace.example.com/compatible-mode/v1",
    });

    expect(config.openaiBaseUrl).toBe("https://workspace.example.com/compatible-mode/v1");
  });

  it.each([undefined, ""])("leaves an absent or empty OpenAI base URL undefined", (baseUrl) => {
    const environment: NodeJS.ProcessEnv = {
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      ...(baseUrl === undefined ? {} : { OPENAI_BASE_URL: baseUrl }),
    };

    expect(loadConfig(environment).openaiBaseUrl).toBeUndefined();
  });

  it("supports independent Agent provider variables", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      OPENAI_API_KEY: "legacy-key",
      OPENAI_BASE_URL: "https://legacy.example/v1",
      OPENAI_CHAT_MODEL: "legacy-model",
      AGENT_MODEL_API_KEY: "agent-key",
      AGENT_MODEL_BASE_URL: "https://agent.example/v1",
      AGENT_MODEL_NAME: "agent-model",
    });

    expect(config.openaiApiKey).toBe("agent-key");
    expect(config.openaiBaseUrl).toBe("https://agent.example/v1");
    expect(config.openaiChatModel).toBe("agent-model");
  });
});
