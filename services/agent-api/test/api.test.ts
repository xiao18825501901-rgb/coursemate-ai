import { afterEach, beforeEach, describe, expect, it } from "vitest";
import request from "supertest";

import { createApp } from "../src/app.js";
import { AgentDatabase } from "../src/db.js";
import type {
  AgentModelClient,
  AgentModelRequest,
  AgentModelResponse,
} from "../src/openai/client.js";
import { TaskRepository } from "../src/repositories/tasks.js";
import { AgentService } from "../src/services/agent.js";
import { ToolExecutor } from "../src/tools/executor.js";


class FakeModelClient implements AgentModelClient {
  constructor(private readonly responses: AgentModelResponse[]) {}

  async create(_request: AgentModelRequest): Promise<AgentModelResponse> {
    const response = this.responses.shift();
    if (response === undefined) throw new Error("Fake response queue exhausted.");
    return response;
  }
}

describe("Agent API", () => {
  let database: AgentDatabase;
  let repository: TaskRepository;

  beforeEach(() => {
    database = new AgentDatabase(":memory:");
    database.initialize();
    let id = 0;
    repository = new TaskRepository(database.connection, {
      clock: () => new Date("2026-08-11T00:00:00.000Z"),
      idFactory: () => `task-${++id}`,
    });
  });

  afterEach(() => database.close());

  it("returns health, CORS, and security headers", async () => {
    const app = createApp({
      repository,
      agentService: new AgentService(new FakeModelClient([]), new ToolExecutor(repository), {
        model: "test-model",
        maxToolRounds: 4,
      }),
      webOrigin: "http://localhost:5173",
    });

    const response = await request(app)
      .get("/health")
      .set("Origin", "http://localhost:5173");

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ status: "ok", service: "agent-api" });
    expect(response.headers["access-control-allow-origin"]).toBe("http://localhost:5173");
    expect(response.headers["x-content-type-options"]).toBe("nosniff");
    expect(response.headers["x-powered-by"]).toBeUndefined();
  });

  it("supports REST create, list filters, patch, completion, and deletion", async () => {
    const app = createApp({
      repository,
      agentService: new AgentService(new FakeModelClient([]), new ToolExecutor(repository), {
        model: "test-model",
        maxToolRounds: 4,
      }),
      webOrigin: "http://localhost:5173",
    });

    const created = await request(app).post("/api/tasks").send({
      title: "Review lighting",
      courseId: "cs3481",
      priority: "high",
      dueDate: "2026-08-20",
    });
    const listed = await request(app).get("/api/tasks?courseId=cs3481&status=todo");
    const updated = await request(app)
      .patch(`/api/tasks/${created.body.id as string}`)
      .send({ status: "completed" });
    const deleted = await request(app).delete(`/api/tasks/${created.body.id as string}`);

    expect(created.status).toBe(201);
    expect(listed.body).toMatchObject({ total: 1, page: 1, pageSize: 50 });
    expect(updated.body).toMatchObject({ status: "completed" });
    expect(deleted.status).toBe(204);
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(0);
  });

  it("runs agent chat through function calling and persistence", async () => {
    const createArguments = {
      title: "Read heritage notes",
      notes: null,
      courseId: "ge2324",
      priority: "medium",
      dueDate: null,
      sourceCitation: null,
    };
    const model = new FakeModelClient([
      {
        outputText: "",
        output: [
          {
            type: "function_call",
            call_id: "call-1",
            name: "createTask",
            arguments: JSON.stringify(createArguments),
          },
        ],
      },
      { outputText: "Created the GE2324 reading task.", output: [] },
    ]);
    const app = createApp({
      repository,
      agentService: new AgentService(model, new ToolExecutor(repository), {
        model: "test-model",
        maxToolRounds: 4,
      }),
      webOrigin: "http://localhost:5173",
    });

    const response = await request(app)
      .post("/api/agent/chat")
      .send({ message: "Add a GE2324 reading task." });

    expect(response.status).toBe(200);
    expect(response.body.message).toContain("Created");
    expect(response.body.toolResults[0]).toMatchObject({ ok: true });
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(1);
  });

  it("uses the standard error envelope for invalid and missing tasks", async () => {
    const app = createApp({
      repository,
      agentService: new AgentService(new FakeModelClient([]), new ToolExecutor(repository), {
        model: "test-model",
        maxToolRounds: 4,
      }),
      webOrigin: "http://localhost:5173",
    });

    const invalid = await request(app).post("/api/tasks").send({
      title: "",
      extra: "not allowed",
    });
    const missing = await request(app).patch("/api/tasks/missing").send({ status: "completed" });
    const badQuery = await request(app).get("/api/tasks?page=0");

    expect(invalid.status).toBe(400);
    expect(invalid.body.error.code).toBe("VALIDATION_ERROR");
    expect(missing.status).toBe(404);
    expect(missing.body.error.code).toBe("TASK_NOT_FOUND");
    expect(badQuery.status).toBe(400);
    expect(badQuery.body.error.code).toBe("VALIDATION_ERROR");
  });
});
