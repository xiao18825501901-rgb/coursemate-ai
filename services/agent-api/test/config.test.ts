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
    expect(config.agentChatRequestsPerDay).toBe(30);
  });

  it("validates the explicit daily Agent chat budget", () => {
    const environment = {
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      AGENT_CHAT_REQUESTS_PER_DAY: "12",
    };
    expect(loadConfig(environment).agentChatRequestsPerDay).toBe(12);
    expect(() => loadConfig({
      ...environment,
      AGENT_CHAT_REQUESTS_PER_DAY: "0",
    })).toThrow(/between 1 and 1000/);
    expect(() => loadConfig({
      ...environment,
      AGENT_CHAT_REQUESTS_PER_DAY: "12requests",
    })).toThrow(/between 1 and 1000/);
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
  it("defaults the model and base URL to DeepSeek when nothing is set", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
    });

    expect(config.openaiChatModel).toBe("deepseek-flash");
    expect(config.openaiBaseUrl).toBe("https://api.deepseek.com");
  });

  it.each([undefined, ""])("defaults an absent or empty base URL to the DeepSeek host", (baseUrl) => {
    const environment: NodeJS.ProcessEnv = {
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      ...(baseUrl === undefined ? {} : { OPENAI_BASE_URL: baseUrl }),
    };

    expect(loadConfig(environment).openaiBaseUrl).toBe("https://api.deepseek.com");
  });

  it.each([
    "https://api.deepseek.com",
    "https://api.deepseek.com/",
  ])("accepts the official DeepSeek base URL %s", (endpoint) => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      AGENT_MODEL_NAME: "deepseek-flash",
      OPENAI_BASE_URL: endpoint,
    });

    expect(config.openaiBaseUrl).toBe(endpoint);
    expect(config.openaiChatModel).toBe("deepseek-flash");
  });

  it.each([
    "https://workspace.example.com/compatible-mode/v1",
    "https://api.deepseek.com/v1",
    "http://api.deepseek.com",
  ])("rejects a non-DeepSeek base URL for deepseek-flash: %s", (endpoint) => {
    expect(() => loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      AGENT_MODEL_NAME: "deepseek-flash",
      OPENAI_BASE_URL: endpoint,
    })).toThrow(/deepseek-flash requires/);
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

  it.each([
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
    "https://workspace.eu-central-1.maas.aliyuncs.com/compatible-mode/v1",
  ])("accepts qwen3.8-max with explicit credentials and endpoint %s", (endpoint) => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      AGENT_MODEL_API_KEY: "agent-key",
      AGENT_MODEL_BASE_URL: endpoint,
      AGENT_MODEL_NAME: "qwen3.8-max",
    });

    expect(config.openaiChatModel).toBe("qwen3.8-max");
    expect(config.openaiBaseUrl).toBe(endpoint);
  });

  it.each([
    {},
    { AGENT_MODEL_API_KEY: "agent-key" },
    {
      AGENT_MODEL_API_KEY: "agent-key",
      AGENT_MODEL_BASE_URL: "https://provider.example/compatible-mode/v1",
    },
    {
      AGENT_MODEL_API_KEY: "agent-key",
      AGENT_MODEL_BASE_URL: "http://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    {
      AGENT_MODEL_API_KEY: "agent-key",
      AGENT_MODEL_BASE_URL:
        "https://trial.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
    },
    {
      AGENT_MODEL_API_KEY: "agent-key",
      AGENT_MODEL_BASE_URL:
        "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    },
  ])("fails closed for incomplete or unsafe qwen3.8-max configuration", (modelConfig) => {
    expect(() => loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      AGENT_MODEL_NAME: "qwen3.8-max",
      ...modelConfig,
    })).toThrow(/qwen3\.8-max requires explicit/);
  });
});
