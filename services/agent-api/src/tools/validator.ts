import { Ajv, type ErrorObject, type ValidateFunction } from "ajv";

import { isToolName, TOOL_NAMES, TOOL_SCHEMAS, type ToolName } from "./schemas.js";


export interface ValidationResult {
  ok: boolean;
  errors: string[];
}

const ajv = new Ajv({ allErrors: true, strict: true });
const validators = Object.fromEntries(
  TOOL_NAMES.map((name) => [name, ajv.compile(TOOL_SCHEMAS[name])]),
) as Record<ToolName, ValidateFunction>;

function formatError(error: ErrorObject): string {
  const location = error.instancePath === "" ? "arguments" : `arguments${error.instancePath}`;
  return `${location} ${error.message ?? "is invalid"}`;
}

export function validateToolArguments(toolName: string, value: unknown): ValidationResult {
  if (!isToolName(toolName)) {
    return { ok: false, errors: [`Unknown tool: ${toolName}`] };
  }
  const validator = validators[toolName];
  const ok = validator(value);
  return {
    ok: Boolean(ok),
    errors: ok ? [] : (validator.errors ?? []).map(formatError),
  };
}
