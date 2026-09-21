import type { TaskRepository } from "../repositories/tasks.js";
import type {
  CreateTaskInput,
  SourceCitation,
  TaskListQuery,
  TaskPriority,
  TaskStatus,
  ToolResult,
  UpdateTaskInput,
} from "../types.js";
import type { JevToolIntentGate, ToolIntentRecord } from "./intent-gate.js";
import { isToolName } from "./schemas.js";
import { validateToolArguments } from "./validator.js";


interface CreateTaskArguments {
  title: string;
  notes: string | null;
  courseId: string | null;
  priority: TaskPriority | null;
  dueDate: string | null;
  sourceCitation: SourceCitation | null;
}

interface SearchTaskArguments {
  query: string | null;
  courseId: string | null;
  status: TaskStatus | null;
  page: number;
  pageSize: number;
}

type UpdateField = "title" | "notes" | "courseId" | "status" | "priority" | "dueDate";

interface UpdateTaskArguments {
  taskId: string;
  updateFields: UpdateField[];
  title: string | null;
  notes: string | null;
  courseId: string | null;
  status: TaskStatus | null;
  priority: TaskPriority | null;
  dueDate: string | null;
}

interface TaskIdArguments {
  taskId: string;
}

export interface ToolCallContext {
  userMessage: string;
  courseId?: string;
  objectRevision?: string;
  currentRevision?: string;
}

const WRITE_TOOLS = new Set<string>(["createTask", "updateTask", "completeTask", "deleteTask"]);

function isWriteTool(toolName: string): boolean {
  return WRITE_TOOLS.has(toolName);
}

function success<T>(data: T): ToolResult<T> {
  return { ok: true, data, error: null };
}

function failure(code: string, message: string): ToolResult<never> {
  return { ok: false, data: null, error: { code, message } };
}

export class ToolExecutor {
  constructor(
    private readonly repository: TaskRepository,
    private readonly intentGate: JevToolIntentGate | undefined = undefined,
  ) {}

  execute(ownerUserId: string, toolName: string, argumentsValue: unknown): ToolResult<unknown>;
  execute(
    ownerUserId: string,
    toolName: string,
    argumentsValue: unknown,
    context: ToolCallContext,
  ): Promise<ToolResult<unknown>>;
  execute(
    ownerUserId: string,
    toolName: string,
    argumentsValue: unknown,
    context?: ToolCallContext,
  ): ToolResult<unknown> | Promise<ToolResult<unknown>> {
    if (this.intentGate !== undefined && isWriteTool(toolName)) {
      return this.executeGuarded(ownerUserId, toolName, argumentsValue, context);
    }
    return this.dispatch(ownerUserId, toolName, argumentsValue);
  }

  private dispatch(ownerUserId: string, toolName: string, argumentsValue: unknown): ToolResult<unknown> {
    if (!isToolName(toolName)) {
      return failure("UNKNOWN_TOOL", `Tool ${toolName} is not allowed.`);
    }
    const validation = validateToolArguments(toolName, argumentsValue);
    if (!validation.ok) {
      return failure("INVALID_TOOL_ARGUMENTS", validation.errors.join("; "));
    }

    switch (toolName) {
      case "createTask":
        return this.create(ownerUserId, argumentsValue as CreateTaskArguments);
      case "searchTask":
        return this.search(ownerUserId, argumentsValue as SearchTaskArguments);
      case "updateTask":
        return this.update(ownerUserId, argumentsValue as UpdateTaskArguments);
      case "completeTask":
        return this.complete(ownerUserId, argumentsValue as TaskIdArguments);
      case "deleteTask":
        return this.delete(ownerUserId, argumentsValue as TaskIdArguments);
    }
  }

  private async executeGuarded(
    ownerUserId: string,
    toolName: string,
    argumentsValue: unknown,
    context: ToolCallContext | undefined,
  ): Promise<ToolResult<unknown>> {
    const gate = this.intentGate;
    if (gate === undefined) {
      return this.dispatch(ownerUserId, toolName, argumentsValue);
    }
    const record = await gate.checkToolIntent({
      userMessage: context?.userMessage ?? "",
      proposedTool: toolName,
      toolArguments: argumentsValue as Record<string, unknown>,
      actorScope: "owner",
      actorPermissions: ["tasks:write"],
      requiredPermissions: ["tasks:write"],
      isReadOnly: false,
      explicit: false,
      objectRevision: context?.objectRevision ?? null,
      currentRevision: context?.currentRevision ?? null,
      ownerUserId,
      authorizationScope: "tasks",
      courseId: context?.courseId ?? null,
      workspaceId: null,
      materialRevision: null,
      nodeId: null,
      specVersion: null,
    });
    if (record.mode === "enforce" && record.verdict !== "ALLOW") {
      return this.blockedResult(record);
    }
    const result = this.dispatch(ownerUserId, toolName, argumentsValue);
    result.intent = record;
    return result;
  }

  private blockedResult(record: ToolIntentRecord): ToolResult<never> {
    const refused =
      record.verdict === "REFUSE_UNAUTHORIZED" || record.verdict === "REFUSE_STALE";
    const result = failure(
      refused ? "INTENT_REFUSED" : "CONFIRMATION_REQUIRED",
      refused
        ? "The requested change was refused because it was not authorized."
        : "The requested change needs your explicit confirmation.",
    );
    result.intent = record;
    return result;
  }

  private create(ownerUserId: string, argumentsValue: CreateTaskArguments): ToolResult<unknown> {
    const input: CreateTaskInput = {
      title: argumentsValue.title,
      notes: argumentsValue.notes,
      courseId: argumentsValue.courseId,
      dueDate: argumentsValue.dueDate,
      sourceCitation: argumentsValue.sourceCitation,
    };
    if (argumentsValue.priority !== null) {
      input.priority = argumentsValue.priority;
    }
    return success(this.repository.create(ownerUserId, input));
  }

  private search(ownerUserId: string, argumentsValue: SearchTaskArguments): ToolResult<unknown> {
    const query: TaskListQuery = {
      page: argumentsValue.page,
      pageSize: argumentsValue.pageSize,
    };
    if (argumentsValue.query !== null) query.query = argumentsValue.query;
    if (argumentsValue.courseId !== null) query.courseId = argumentsValue.courseId;
    if (argumentsValue.status !== null) query.status = argumentsValue.status;
    return success(this.repository.list(ownerUserId, query));
  }

  private update(ownerUserId: string, argumentsValue: UpdateTaskArguments): ToolResult<unknown> {
    const input: UpdateTaskInput = {};
    for (const field of argumentsValue.updateFields) {
      switch (field) {
        case "title":
          if (argumentsValue.title === null) {
            return failure("INVALID_UPDATE_VALUE", "title cannot be null when selected.");
          }
          input.title = argumentsValue.title;
          break;
        case "notes":
          input.notes = argumentsValue.notes;
          break;
        case "courseId":
          input.courseId = argumentsValue.courseId;
          break;
        case "status":
          if (argumentsValue.status === null) {
            return failure("INVALID_UPDATE_VALUE", "status cannot be null when selected.");
          }
          input.status = argumentsValue.status;
          break;
        case "priority":
          if (argumentsValue.priority === null) {
            return failure("INVALID_UPDATE_VALUE", "priority cannot be null when selected.");
          }
          input.priority = argumentsValue.priority;
          break;
        case "dueDate":
          input.dueDate = argumentsValue.dueDate;
          break;
      }
    }
    const task = this.repository.update(ownerUserId, argumentsValue.taskId, input);
    return task === null
      ? failure("TASK_NOT_FOUND", "The selected task was not found.")
      : success(task);
  }

  private complete(ownerUserId: string, argumentsValue: TaskIdArguments): ToolResult<unknown> {
    const task = this.repository.complete(ownerUserId, argumentsValue.taskId);
    return task === null
      ? failure("TASK_NOT_FOUND", "The selected task was not found.")
      : success(task);
  }

  private delete(ownerUserId: string, argumentsValue: TaskIdArguments): ToolResult<unknown> {
    if (!this.repository.delete(ownerUserId, argumentsValue.taskId)) {
      return failure("TASK_NOT_FOUND", "The selected task was not found.");
    }
    return success({ taskId: argumentsValue.taskId, deleted: true });
  }
}
