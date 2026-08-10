import { Ajv, type ErrorObject, type ValidateFunction } from "ajv";

import { HttpError } from "../errors.js";
import type { CreateTaskInput, UpdateTaskInput } from "../types.js";


const citationSchema = {
  type: "object",
  properties: {
    filename: { type: "string", minLength: 1, maxLength: 200 },
    locator: { type: "string", minLength: 1, maxLength: 200 },
    excerpt: { type: "string", minLength: 1, maxLength: 800 },
  },
  required: ["filename", "locator", "excerpt"],
  additionalProperties: false,
};

const taskProperties = {
  title: { type: "string", minLength: 1, maxLength: 200 },
  notes: { anyOf: [{ type: "string", maxLength: 5_000 }, { type: "null" }] },
  courseId: {
    anyOf: [
      { type: "string", pattern: "^[a-z0-9][a-z0-9-]{1,49}$" },
      { type: "null" },
    ],
  },
  status: { type: "string", enum: ["todo", "in_progress", "completed"] },
  priority: { type: "string", enum: ["low", "medium", "high"] },
  dueDate: {
    anyOf: [
      { type: "string", pattern: "^[0-9]{4}-[0-9]{2}-[0-9]{2}$" },
      { type: "null" },
    ],
  },
  sourceCitation: { anyOf: [citationSchema, { type: "null" }] },
};

const ajv = new Ajv({ allErrors: true, strict: true });
const createValidator = ajv.compile({
  type: "object",
  properties: {
    title: taskProperties.title,
    notes: taskProperties.notes,
    courseId: taskProperties.courseId,
    priority: taskProperties.priority,
    dueDate: taskProperties.dueDate,
    sourceCitation: taskProperties.sourceCitation,
  },
  required: ["title"],
  additionalProperties: false,
});
const updateValidator = ajv.compile({
  type: "object",
  properties: taskProperties,
  minProperties: 1,
  additionalProperties: false,
});
const chatValidator = ajv.compile({
  type: "object",
  properties: {
    message: { type: "string", minLength: 1, maxLength: 2_000 },
  },
  required: ["message"],
  additionalProperties: false,
});

function issues(errors: ErrorObject[] | null | undefined): string[] {
  return (errors ?? []).map((error) => {
    const path = error.instancePath === "" ? "body" : `body${error.instancePath}`;
    return `${path} ${error.message ?? "is invalid"}`;
  });
}

function validated<T>(validator: ValidateFunction, body: unknown): T {
  if (!validator(body)) {
    throw new HttpError(400, "VALIDATION_ERROR", "The request did not pass validation.", {
      issues: issues(validator.errors),
    });
  }
  return body as T;
}

export function validateCreateTask(body: unknown): CreateTaskInput {
  return validated<CreateTaskInput>(createValidator, body);
}

export function validateUpdateTask(body: unknown): UpdateTaskInput {
  return validated<UpdateTaskInput>(updateValidator, body);
}

export function validateChat(body: unknown): { message: string } {
  return validated<{ message: string }>(chatValidator, body);
}
