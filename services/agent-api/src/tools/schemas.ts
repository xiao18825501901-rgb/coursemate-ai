export const TOOL_NAMES = [
  "createTask",
  "searchTask",
  "updateTask",
  "completeTask",
  "deleteTask",
] as const;

export type ToolName = (typeof TOOL_NAMES)[number];

export interface StrictObjectSchema {
  readonly type: "object";
  readonly properties: Readonly<Record<string, unknown>>;
  readonly required: readonly string[];
  readonly additionalProperties: false;
}

const nullableString = (maxLength: number): object => ({
  anyOf: [{ type: "string", maxLength }, { type: "null" }],
});

const nullableCourseId = {
  anyOf: [
    { type: "string", pattern: "^[a-z0-9][a-z0-9-]{1,49}$" },
    { type: "null" },
  ],
};

const nullableDate = {
  anyOf: [
    { type: "string", pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" },
    { type: "null" },
  ],
};

const nullablePriority = {
  anyOf: [
    { type: "string", enum: ["low", "medium", "high"] },
    { type: "null" },
  ],
};

const nullableStatus = {
  anyOf: [
    { type: "string", enum: ["todo", "in_progress", "completed"] },
    { type: "null" },
  ],
};

const nullableCitation = {
  anyOf: [
    {
      type: "object",
      properties: {
        filename: { type: "string", minLength: 1, maxLength: 200 },
        locator: { type: "string", minLength: 1, maxLength: 200 },
        excerpt: { type: "string", minLength: 1, maxLength: 800 },
      },
      required: ["filename", "locator", "excerpt"],
      additionalProperties: false,
    },
    { type: "null" },
  ],
};

export const TOOL_SCHEMAS = {
  createTask: {
    type: "object",
    properties: {
      title: { type: "string", minLength: 1, maxLength: 200 },
      notes: nullableString(5_000),
      courseId: nullableCourseId,
      priority: nullablePriority,
      dueDate: nullableDate,
      sourceCitation: nullableCitation,
    },
    required: ["title", "notes", "courseId", "priority", "dueDate", "sourceCitation"],
    additionalProperties: false,
  },
  searchTask: {
    type: "object",
    properties: {
      query: nullableString(200),
      courseId: nullableCourseId,
      status: nullableStatus,
      page: { type: "integer", minimum: 1, maximum: 10_000 },
      pageSize: { type: "integer", minimum: 1, maximum: 100 },
    },
    required: ["query", "courseId", "status", "page", "pageSize"],
    additionalProperties: false,
  },
  updateTask: {
    type: "object",
    properties: {
      taskId: { type: "string", minLength: 1, maxLength: 100 },
      updateFields: {
        type: "array",
        items: {
          type: "string",
          enum: ["title", "notes", "courseId", "status", "priority", "dueDate"],
        },
        minItems: 1,
        maxItems: 6,
        uniqueItems: true,
      },
      title: nullableString(200),
      notes: nullableString(5_000),
      courseId: nullableCourseId,
      status: nullableStatus,
      priority: nullablePriority,
      dueDate: nullableDate,
    },
    required: [
      "taskId",
      "updateFields",
      "title",
      "notes",
      "courseId",
      "status",
      "priority",
      "dueDate",
    ],
    additionalProperties: false,
  },
  completeTask: {
    type: "object",
    properties: {
      taskId: { type: "string", minLength: 1, maxLength: 100 },
    },
    required: ["taskId"],
    additionalProperties: false,
  },
  deleteTask: {
    type: "object",
    properties: {
      taskId: { type: "string", minLength: 1, maxLength: 100 },
    },
    required: ["taskId"],
    additionalProperties: false,
  },
} as const satisfies Record<ToolName, StrictObjectSchema>;

const descriptions: Record<ToolName, string> = {
  createTask: "Create one study task after the user has provided a clear task title.",
  searchTask: "Find study tasks before updating, completing, or deleting an ambiguous task.",
  updateTask: "Update explicitly selected fields on one task identified by its exact task ID.",
  completeTask: "Mark one task, identified by its exact task ID, as completed.",
  deleteTask: "Delete one task only when its exact task ID is known.",
};

export const TOOL_DEFINITIONS = TOOL_NAMES.map((name) => ({
  type: "function" as const,
  name,
  description: descriptions[name],
  strict: true as const,
  parameters: TOOL_SCHEMAS[name],
}));

export function isToolName(value: string): value is ToolName {
  return (TOOL_NAMES as readonly string[]).includes(value);
}
