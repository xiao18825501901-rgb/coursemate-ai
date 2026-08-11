import path from "node:path";

export interface AgentConfig {
  databasePath: string;
  port: number;
  webOrigin: string;
  openaiApiKey: string;
  openaiChatModel: string;
  maxToolRounds: number;
  providerMode: "openai" | "deterministic";
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
  return {
    databasePath:
      configuredPath === ":memory:" ? configuredPath : path.resolve(process.cwd(), configuredPath),
    port: boundedInteger(environment.AGENT_PORT, 8001, 1, 65_535),
    webOrigin: environment.WEB_ORIGIN ?? "http://localhost:5173",
    openaiApiKey: environment.OPENAI_API_KEY ?? "",
    openaiChatModel: environment.OPENAI_CHAT_MODEL ?? "gpt-5.6-luna",
    maxToolRounds: boundedInteger(environment.AGENT_MAX_TOOL_ROUNDS, 4, 1, 10),
    providerMode,
  };
}
