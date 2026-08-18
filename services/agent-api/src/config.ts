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
  authTestUserId: string | undefined;
}

function boundedInteger(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = value === undefined ? fallback : Number.parseInt(value, 10);
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
  return {
    databasePath:
      configuredPath === ":memory:" ? configuredPath : path.resolve(process.cwd(), configuredPath),
    host: environment.AGENT_HOST?.trim() || "127.0.0.1",
    port: boundedInteger(environment.AGENT_PORT ?? environment.PORT, 8001, 1, 65_535),
    webOrigin: environment.WEB_ORIGIN ?? "http://localhost:5173",
    openaiApiKey: environment.AGENT_MODEL_API_KEY ?? environment.OPENAI_API_KEY ?? "",
    openaiBaseUrl:
      environment.AGENT_MODEL_BASE_URL || environment.OPENAI_BASE_URL || undefined,
    openaiChatModel:
      environment.AGENT_MODEL_NAME ?? environment.OPENAI_CHAT_MODEL ?? "gpt-5.6-luna",
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
    authTestUserId,
  };
}
