import path from "node:path";

export interface AgentConfig {
  databasePath: string;
  host: string;
  port: number;
  webOrigin: string;
  openaiApiKey: string;
  openaiBaseUrl: string | undefined;
  openaiChatModel: string;
  maxToolRounds: number;
  providerMode: "openai" | "deterministic";
  clerkPublishableKey: string;
  clerkSecretKey: string;
  clerkJwtKey: string | undefined;
  agentChatRequestsPerMinute: number;
  agentChatRequestsPerDay: number;
  authTestUserId: string | undefined;
}

const V3_PRIMARY_MODEL = "qwen3.8-max";

function isAllowedModelStudioEndpoint(value: string): boolean {
  if (/[\u0000-\u001f\u007f]/.test(value)) return false;
  try {
    const endpoint = new URL(value);
    const path = endpoint.pathname.replace(/\/+$/, "");
    // Source: https://help.aliyun.com/en/model-studio/base-url
    const sharedHost =
      endpoint.hostname === "dashscope.aliyuncs.com" ||
      endpoint.hostname === "dashscope-intl.aliyuncs.com" ||
      endpoint.hostname === "dashscope-us.aliyuncs.com" ||
      endpoint.hostname === "cn-hongkong.dashscope.aliyuncs.com";
    const workspaceSuffixes = [
      ".cn-beijing.maas.aliyuncs.com",
      ".ap-southeast-1.maas.aliyuncs.com",
      ".ap-northeast-1.maas.aliyuncs.com",
      ".eu-central-1.maas.aliyuncs.com",
      ".us-east-1.maas.aliyuncs.com",
      ".cn-hongkong.maas.aliyuncs.com",
    ];
    const workspaceHost =
      !endpoint.hostname.startsWith("trial.") &&
      !endpoint.hostname.startsWith("token-plan.") &&
      workspaceSuffixes.some((suffix) => endpoint.hostname.endsWith(suffix));
    return (
      endpoint.protocol === "https:" &&
      (sharedHost || workspaceHost) &&
      path === "/compatible-mode/v1" &&
      endpoint.username === "" &&
      endpoint.password === "" &&
      endpoint.search === "" &&
      endpoint.hash === "" &&
      (endpoint.port === "" || endpoint.port === "443")
    );
  } catch {
    return false;
  }
}

function boundedInteger(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isInteger(parsed) || parsed < min || parsed > max) {
    throw new Error(`Expected an integer between ${min} and ${max}.`);
  }
  return parsed;
}

export function loadConfig(environment: NodeJS.ProcessEnv = process.env): AgentConfig {
  const configuredPath = environment.AGENT_DATABASE_PATH ?? "../../data/agent.sqlite3";
  const providerMode = environment.AGENT_PROVIDER_MODE ?? "openai";
  if (providerMode !== "openai" && providerMode !== "deterministic") {
    throw new Error("AGENT_PROVIDER_MODE must be openai or deterministic.");
  }
  const clerkPublishableKey = environment.CLERK_PUBLISHABLE_KEY ?? "";
  const clerkSecretKey = environment.CLERK_SECRET_KEY ?? "";
  const authTestUserId = environment.AUTH_TEST_USER_ID || undefined;
  if (
    authTestUserId !== undefined &&
    (environment.NODE_ENV !== "test" || providerMode !== "deterministic")
  ) {
    throw new Error("AUTH_TEST_USER_ID is allowed only in test deterministic mode.");
  }
  if (authTestUserId === undefined && (!clerkPublishableKey || !clerkSecretKey)) {
    throw new Error("CLERK_PUBLISHABLE_KEY and CLERK_SECRET_KEY are required.");
  }
  const openaiApiKey = environment.AGENT_MODEL_API_KEY ?? environment.OPENAI_API_KEY ?? "";
  const openaiBaseUrl =
    environment.AGENT_MODEL_BASE_URL || environment.OPENAI_BASE_URL || undefined;
  const openaiChatModel =
    environment.AGENT_MODEL_NAME ?? environment.OPENAI_CHAT_MODEL ?? "gpt-5.6-luna";
  if (
    providerMode === "openai" &&
    openaiChatModel === V3_PRIMARY_MODEL &&
    (
      !environment.AGENT_MODEL_API_KEY?.trim() ||
      !environment.AGENT_MODEL_BASE_URL ||
      !isAllowedModelStudioEndpoint(environment.AGENT_MODEL_BASE_URL)
    )
  ) {
    throw new Error(
      "qwen3.8-max requires explicit AGENT_MODEL_API_KEY and an allowlisted " +
      "AGENT_MODEL_BASE_URL.",
    );
  }
  return {
    databasePath:
      configuredPath === ":memory:" ? configuredPath : path.resolve(process.cwd(), configuredPath),
    host: environment.AGENT_HOST?.trim() || "127.0.0.1",
    port: boundedInteger(environment.AGENT_PORT ?? environment.PORT, 8001, 1, 65_535),
    webOrigin: environment.WEB_ORIGIN ?? "http://localhost:5173",
    openaiApiKey,
    openaiBaseUrl,
    openaiChatModel,
    maxToolRounds: boundedInteger(environment.AGENT_MAX_TOOL_ROUNDS, 4, 1, 10),
    providerMode,
    clerkPublishableKey,
    clerkSecretKey,
    clerkJwtKey: environment.CLERK_JWT_KEY || undefined,
    agentChatRequestsPerMinute: boundedInteger(
      environment.AGENT_CHAT_REQUESTS_PER_MINUTE,
      10,
      1,
      1_000,
    ),
    agentChatRequestsPerDay: boundedInteger(
      environment.AGENT_CHAT_REQUESTS_PER_DAY,
      30,
      1,
      1_000,
    ),
    authTestUserId,
  };
}
