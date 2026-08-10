import { describe, expect, it } from "vitest";

import { TOOL_DEFINITIONS, TOOL_NAMES, TOOL_SCHEMAS } from "../src/tools/schemas.js";
import { validateToolArguments } from "../src/tools/validator.js";


const validArguments: Record<(typeof TOOL_NAMES)[number], Record<string, unknown>> = {
  createTask: {
    title: "Review lighting",
    notes: null,
    courseId: "cs3481",
    priority: "high",
    dueDate: "2026-08-20",
    sourceCitation: null,
  },
  searchTask: {
    query: "lighting",
    courseId: "cs3481",
    status: null,
    page: 1,
    pageSize: 20,
  },
  updateTask: {
    taskId: "task-1",
    updateFields: ["title", "priority"],
    title: "Review Phong lighting",
    notes: null,
    courseId: null,
    status: null,
    priority: "high",
    dueDate: null,
  },
  completeTask: { taskId: "task-1" },
  deleteTask: { taskId: "task-1" },
};

describe("strict tool schemas", () => {
  it("uses the same closed schema objects for every OpenAI tool definition", () => {
    expect(TOOL_DEFINITIONS.map((tool) => tool.name)).toEqual(TOOL_NAMES);
    for (const definition of TOOL_DEFINITIONS) {
      const schema = TOOL_SCHEMAS[definition.name];
      expect(definition.strict).toBe(true);
      expect(definition.parameters).toBe(schema);
      expect(schema.additionalProperties).toBe(false);
      expect(new Set(schema.required)).toEqual(new Set(Object.keys(schema.properties)));
    }
  });

  it.each(TOOL_NAMES)("accepts valid %s arguments", (toolName) => {
    const result = validateToolArguments(toolName, validArguments[toolName]);

    expect(result.ok).toBe(true);
    expect(result.errors).toEqual([]);
  });

  it("rejects missing and additional createTask properties", () => {
    const missing = { ...validArguments.createTask };
    delete missing.notes;
    const additional = { ...validArguments.createTask, sql: "DROP TABLE tasks" };

    expect(validateToolArguments("createTask", missing).ok).toBe(false);
    expect(validateToolArguments("createTask", additional).ok).toBe(false);
  });

  it.each([
    ["priority", { ...validArguments.createTask, priority: "urgent" }],
    ["date", { ...validArguments.createTask, dueDate: "20/08/2026" }],
    ["page", { ...validArguments.searchTask, page: 0 }],
    ["empty update", { ...validArguments.updateTask, updateFields: [] }],
  ])("rejects malformed %s arguments", (_label, value) => {
    expect(validateToolArguments("priority" === _label || "date" === _label ? "createTask" : _label === "page" ? "searchTask" : "updateTask", value).ok).toBe(false);
  });

  it("rejects unknown tool names", () => {
    const result = validateToolArguments("runSql", {});

    expect(result.ok).toBe(false);
    expect(result.errors[0]).toContain("Unknown tool");
  });
});
