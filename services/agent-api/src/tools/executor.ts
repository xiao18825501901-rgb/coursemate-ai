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

function success<T>(data: T): ToolResult<T> {
  return { ok: true, data, error: null };
}

function failure(code: string, message: string): ToolResult<never> {
  return { ok: false, data: null, error: { code, message } };
}

export class ToolExecutor {
  constructor(private readonly repository: TaskRepository) {}

  execute(toolName: string, argumentsValue: unknown): ToolResult<unknown> {
    if (!isToolName(toolName)) {
      return failure("UNKNOWN_TOOL", `Tool ${toolName} is not allowed.`);
    }
    const validation = validateToolArguments(toolName, argumentsValue);
    if (!validation.ok) {
      return failure("INVALID_TOOL_ARGUMENTS", validation.errors.join("; "));
    }

    switch (toolName) {
      case "createTask":
        return this.create(argumentsValue as CreateTaskArguments);
      case "searchTask":
        return this.search(argumentsValue as SearchTaskArguments);
      case "updateTask":
        return this.update(argumentsValue as UpdateTaskArguments);
      case "completeTask":
        return this.complete(argumentsValue as TaskIdArguments);
      case "deleteTask":
        return this.delete(argumentsValue as TaskIdArguments);
    }
  }

  private create(argumentsValue: CreateTaskArguments): ToolResult<unknown> {
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
    return success(this.repository.create(input));
  }

  private search(argumentsValue: SearchTaskArguments): ToolResult<unknown> {
    const query: TaskListQuery = {
      page: argumentsValue.page,
      pageSize: argumentsValue.pageSize,
    };
    if (argumentsValue.query !== null) query.query = argumentsValue.query;
    if (argumentsValue.courseId !== null) query.courseId = argumentsValue.courseId;
    if (argumentsValue.status !== null) query.status = argumentsValue.status;
    return success(this.repository.list(query));
  }

  private update(argumentsValue: UpdateTaskArguments): ToolResult<unknown> {
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
    const task = this.repository.update(argumentsValue.taskId, input);
    return task === null
      ? failure("TASK_NOT_FOUND", "The selected task was not found.")
      : success(task);
  }

  private complete(argumentsValue: TaskIdArguments): ToolResult<unknown> {
    const task = this.repository.complete(argumentsValue.taskId);
    return task === null
      ? failure("TASK_NOT_FOUND", "The selected task was not found.")
      : success(task);
  }

  private delete(argumentsValue: TaskIdArguments): ToolResult<unknown> {
    if (!this.repository.delete(argumentsValue.taskId)) {
      return failure("TASK_NOT_FOUND", "The selected task was not found.");
    }
    return success({ taskId: argumentsValue.taskId, deleted: true });
  }
}
