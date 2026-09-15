import { createApp } from "./app.js";
import { createClerkAuthStrategy, createTestAuthStrategy } from "./auth.js";
import { loadConfig } from "./config.js";
import { AgentDatabase } from "./db.js";
import { AgentError } from "./errors.js";
import {
  type AgentModelClient,
  OpenAIResponsesClient,
} from "./openai/client.js";
import { DeterministicAgentModelClient } from "./openai/deterministic-client.js";
import { TaskRepository } from "./repositories/tasks.js";
import { SqliteModelRateLimiter } from "./rate-limit.js";
import { AgentService } from "./services/agent.js";
import { ToolExecutor } from "./tools/executor.js";


const config = loadConfig();
// Production environment guard: a test identity or a deterministic provider must
// never serve real traffic. This is the same boundary rag-api's settings
// validator enforces for the UI extension.
if (process.env.NODE_ENV === "production") {
  if (config.authTestUserId !== undefined) {
    console.error(
      "AUTH_TEST_USER_ID is forbidden in production: the test identity would be live.",
    );
    process.exit(1);
  }
  if (config.providerMode === "deterministic") {
    console.error("AGENT_PROVIDER_MODE=deterministic is forbidden in production.");
    process.exit(1);
  }
}
const database = new AgentDatabase(config.databasePath);
database.initialize();
const repository = new TaskRepository(database.connection);
const unavailableClient: AgentModelClient = {
  create: async () => {
    throw new AgentError(
      "OPENAI_NOT_CONFIGURED",
      "OPENAI_API_KEY is required for natural-language agent chat.",
    );
  },
};
const modelClient = config.providerMode === "deterministic"
  ? new DeterministicAgentModelClient()
  : config.openaiApiKey
    ? new OpenAIResponsesClient(config.openaiApiKey, undefined, config.openaiBaseUrl)
    : unavailableClient;
const agentService = new AgentService(modelClient, new ToolExecutor(repository), {
  model: config.openaiChatModel,
  maxToolRounds: config.maxToolRounds,
});
const application = createApp({
  repository,
  agentService,
  webOrigin: config.webOrigin,
  authStrategy: config.authTestUserId === undefined
    ? createClerkAuthStrategy({
        publishableKey: config.clerkPublishableKey,
        secretKey: config.clerkSecretKey,
        ...(config.clerkJwtKey === undefined ? {} : { jwtKey: config.clerkJwtKey }),
        authorizedParties: [config.webOrigin],
      })
    : createTestAuthStrategy(config.authTestUserId),
  modelRateLimiter: new SqliteModelRateLimiter(database.connection, {
    limitPerMinute: config.agentChatRequestsPerMinute,
    limitPerDay: config.agentChatRequestsPerDay,
  }),
  readinessCheck: () => database.isReady(),
});
const server = application.listen(config.port, config.host, () => {
  console.log(`CourseMate Agent API listening on http://${config.host}:${config.port}`);
});

function shutdown(): void {
  server.close(() => {
    database.close();
  });
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
