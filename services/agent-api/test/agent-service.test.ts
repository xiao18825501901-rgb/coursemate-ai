import { afterEach, beforeEach, describe, expect, it } from "vitest";

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
  readonly requests: AgentModelRequest[] = [];

  constructor(private readonly responses: AgentModelResponse[]) {}

  async create(request: AgentModelRequest): Promise<AgentModelResponse> {
    this.requests.push(structuredClone(request));
    const response = this.responses.shift();
    if (response === undefined) {
      throw new Error("Fake response queue exhausted.");
    }
    return response;
  }
}

function functionCall(callId: string, name: string, argumentsValue: object | string) {
  return {
    type: "function_call" as const,
    call_id: callId,
    name,
    arguments:
      typeof argumentsValue === "string" ? argumentsValue : JSON.stringify(argumentsValue),
  };
}

const createArguments = {
  title: "Review Phong lighting",
  notes: null,
  courseId: "cs3481",
  priority: "high",
  dueDate: "2026-08-20",
  sourceCitation: null,
};

describe("AgentService", () => {
  let database: AgentDatabase;
  let repository: TaskRepository;
  let executor: ToolExecutor;

  beforeEach(() => {
    database = new AgentDatabase(":memory:");
    database.initialize();
    repository = new TaskRepository(database.connection, {
      clock: () => new Date("2026-08-11T00:00:00.000Z"),
      idFactory: () => "task-1",
    });
    executor = new ToolExecutor(repository);
  });

  afterEach(() => database.close());

  it("runs function_call through SQLite and sends function_call_output", async () => {
    const model = new FakeModelClient([
      { outputText: "", output: [functionCall("call-1", "createTask", createArguments)] },
      { outputText: "Created your CS3481 lighting task.", output: [] },
    ]);
    const service = new AgentService(model, executor, { model: "test-model", maxToolRounds: 4 });

    const result = await service.chat("Add a lighting review task for CS3481.");

    expect(result.message).toBe("Created your CS3481 lighting task.");
    expect(result.toolResults).toHaveLength(1);
    expect(repository.get("task-1")).toMatchObject({ title: "Review Phong lighting" });
    expect(model.requests).toHaveLength(2);
    expect(model.requests[0]?.tools.every((tool) => tool.strict)).toBe(true);
    expect(model.requests[1]?.input).toContainEqual(
      expect.objectContaining({ type: "function_call", call_id: "call-1" }),
    );
    expect(model.requests[1]?.input).toContainEqual(
      expect.objectContaining({ type: "function_call_output", call_id: "call-1" }),
    );
  });

  it("returns invalid JSON to the model so it can repair the call", async () => {
    const model = new FakeModelClient([
      { outputText: "", output: [functionCall("bad", "createTask", "{not-json")] },
      { outputText: "", output: [functionCall("good", "createTask", createArguments)] },
      { outputText: "Task created after correcting the arguments.", output: [] },
    ]);
    const service = new AgentService(model, executor, { model: "test-model", maxToolRounds: 4 });

    const result = await service.chat("Create a lighting task.");

    expect(result.toolResults[0]).toMatchObject({
      ok: false,
      error: { code: "INVALID_JSON_ARGUMENTS" },
    });
    expect(result.toolResults[1]).toMatchObject({ ok: true });
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(1);
  });

  it("stops after the configured tool round bound", async () => {
    const calls = [
      { outputText: "", output: [functionCall("call-1", "searchTask", {
        query: null, courseId: null, status: null, page: 1, pageSize: 20,
      })] },
      { outputText: "", output: [functionCall("call-2", "searchTask", {
        query: null, courseId: null, status: null, page: 1, pageSize: 20,
      })] },
    ];
    const service = new AgentService(new FakeModelClient(calls), executor, {
      model: "test-model",
      maxToolRounds: 2,
    });

    await expect(service.chat("Keep searching forever.")).rejects.toMatchObject({
      code: "TOOL_LOOP_LIMIT",
    });
  });

  it("allows a direct clarification response without mutating tasks", async () => {
    repository.create({ title: "Review lecture one" });
    const model = new FakeModelClient([
      { outputText: "Which exact task should I delete?", output: [] },
    ]);
    const service = new AgentService(model, executor, { model: "test-model", maxToolRounds: 4 });

    const result = await service.chat("Delete the review task.");

    expect(result.message).toContain("Which exact task");
    expect(result.toolResults).toEqual([]);
    expect(repository.list({ page: 1, pageSize: 10 }).total).toBe(1);
  });
});
