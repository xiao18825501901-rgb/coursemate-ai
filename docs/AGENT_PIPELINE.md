# Function Calling Agent Pipeline

## Purpose

The Agent converts natural-language study planning requests into persistent task operations. It is not a CRUD parser in the route: the model selects tools, the server validates and executes them, then the model explains the result.

## End-to-end flow

1. POST /api/agent/chat validates a non-empty message of at most 2,000 characters.
2. AgentService.chat sends system instructions, the user message, and TOOL_DEFINITIONS to the configured model client.
3. OpenAIResponsesClient calls the Responses API with strict function tools. The deterministic client supplies the same response shape for offline acceptance tests.
4. AgentService inspects output items. Plain text is returned only when no tool calls remain.
5. Each function_call name and JSON argument string is parsed. Invalid JSON becomes a structured INVALID_TOOL_ARGUMENTS result.
6. ToolExecutor.execute calls validateToolArguments. Ajv rejects unknown properties, missing required properties, invalid enums, bad dates, oversized text, and unknown tool names.
7. An explicit switch dispatches to TaskRepository. There is no eval, reflection, arbitrary SQL, or model-selected endpoint.
8. The executor serializes a ToolResult as function_call_output linked by call_id.
9. AgentService calls the model again with prior input/output plus tool results. Multiple tool calls in a round are supported.
10. The loop ends on final text or fails after AGENT_MAX_TOOL_ROUNDS, preventing runaway actions.

## Tool catalogue

### create_task

Creates one task. Required: title. Optional nullable fields: notes, courseId, dueDate, priority, and sourceCitation. Defaults are todo and medium. Dates use YYYY-MM-DD.

### search_tasks

Searches with optional status, courseId, free-text query, page, and pageSize. Every property is required by the strict OpenAI schema but may be null when it is intentionally omitted. Results are paginated and consistently ordered.

### update_task

Updates an identified task. All mutable fields are present in the strict schema and may be null where clearing is supported. The executor requires at least one real change besides taskId.

### complete_task

Marks taskId completed and sets completedAt. The repository's update path also clears completedAt when a task is reopened.

### delete_task

Deletes taskId and reports TASK_NOT_FOUND when no row changed. The web UI requires a separate confirmation for direct deletion.

## Schema and execution locations

| Concern | File |
|---|---|
| strict JSON Schemas and Responses definitions | services/agent-api/src/tools/schemas.ts |
| Ajv compilation and errors | services/agent-api/src/tools/validator.ts |
| allow-listed dispatch and business checks | services/agent-api/src/tools/executor.ts |
| tool/model loop | services/agent-api/src/services/agent.ts |
| OpenAI adapter | services/agent-api/src/openai/client.ts |
| deterministic adapter | services/agent-api/src/openai/deterministic-client.ts |
| parameterized persistence | services/agent-api/src/repositories/tasks.ts |

## Why strict schemas matter

Model output is untrusted input. additionalProperties=false prevents accidental or adversarial fields from silently entering the executor. Required nullable fields match strict Structured Outputs expectations while still representing omission. The database repeats important checks so invalid state is blocked at both application and persistence layers.

## Error contract

Tools return either { ok: true, data } or { ok: false, error: { code, message } }. Expected failures such as TASK_NOT_FOUND are sent back to the model so it can ask for clarification or explain what happened. HTTP validation failures remain 400-class error envelopes; unexpected failures are logged server-side and returned without stack traces.

## Direct CRUD and agent behavior

The UI uses direct CRUD for deterministic card interactions and agent chat for natural language. Both paths share TaskRepository, constraints, and response types. This proves Function Calling has a real role without making routine controls depend on a model round trip.

## Acceptance prompts

- Add a high priority GE2324 revision task due 2026-08-20.
- Find all incomplete CS3481 tasks.
- Change the due date of <task title> to 2026-08-25 and set medium priority.
- Complete <task title>.
- Delete <task title>.

Verify the database changes, final natural-language reply, no duplicate mutation across tool rounds, and a structured failure when a task cannot be uniquely identified.
