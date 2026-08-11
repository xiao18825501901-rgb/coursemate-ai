import { describe, expect, it } from "vitest";

import { DeterministicAgentModelClient } from "../src/openai/deterministic-client.js";
import { TOOL_DEFINITIONS } from "../src/tools/schemas.js";


function request(input: unknown[]) {
  return {
    model: "demo",
    instructions: "test",
    input,
    tools: TOOL_DEFINITIONS,
    parallelToolCalls: false as const,
  };
}

describe("DeterministicAgentModelClient", () => {
  it("turns a natural-language create request into strict tool arguments", async () => {
    const client = new DeterministicAgentModelClient();
    const first = await client.create(request([
      { role: "user", content: "Add a high priority GE2324 reading task due 2026-08-20" },
    ]));
    const call = first.output[0] as { name: string; arguments: string };

    expect(call.name).toBe("createTask");
    expect(JSON.parse(call.arguments)).toMatchObject({
      courseId: "ge2324",
      priority: "high",
      dueDate: "2026-08-20",
    });

    const second = await client.create(request([
      { role: "user", content: "Add a high priority GE2324 reading task due 2026-08-20" },
      ...first.output,
      { type: "function_call_output", call_id: "demo-call-1", output: '{"ok":true}' },
    ]));
    expect(second.outputText).toContain("completed");
  });

  it("searches before completing a described task", async () => {
    const client = new DeterministicAgentModelClient();
    const first = await client.create(request([
      { role: "user", content: "Complete the lighting review task" },
    ]));
    expect((first.output[0] as { name: string }).name).toBe("searchTask");

    const second = await client.create(request([
      { role: "user", content: "Complete the lighting review task" },
      ...first.output,
      {
        type: "function_call_output",
        call_id: "demo-call-1",
        output: JSON.stringify({
          ok: true,
          data: { items: [{ id: "task-1", title: "Lighting review" }] },
          error: null,
        }),
      },
    ]));
    expect(second.output[0]).toMatchObject({ name: "completeTask" });
  });
});
