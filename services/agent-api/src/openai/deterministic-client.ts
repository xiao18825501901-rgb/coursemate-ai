import type {
  AgentModelClient,
  AgentModelRequest,
  AgentModelResponse,
} from "./client.js";


interface FunctionCallOutput {
  type: "function_call_output";
  output: string;
}

interface SearchData {
  items?: Array<{ id?: string; title?: string }>;
}

function isFunctionOutput(value: unknown): value is FunctionCallOutput {
  return typeof value === "object" && value !== null && "type" in value &&
    value.type === "function_call_output" && "output" in value && typeof value.output === "string";
}

function call(name: string, argumentsValue: object): AgentModelResponse {
  return {
    outputText: "",
    output: [{
      type: "function_call",
      call_id: "demo-call-1",
      name,
      arguments: JSON.stringify(argumentsValue),
    }],
  };
}

function userMessage(request: AgentModelRequest): string {
  const user = request.input.find(
    (value): value is { role: "user"; content: string } =>
      typeof value === "object" && value !== null && "role" in value && value.role === "user" &&
      "content" in value && typeof value.content === "string",
  );
  return user?.content ?? "";
}

function searchArguments(message: string) {
  const courseId = message.match(/\b(cs3481|ge2324)\b/i)?.[1]?.toLowerCase() ?? null;
  const query = message
    .replace(/\b(please|complete|finish|delete|remove|update|change|find|search|for|the|task)\b/gi, " ")
    .replace(/\b(cs3481|ge2324|high|medium|low|priority)\b/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return { query: query || null, courseId, status: null, page: 1, pageSize: 20 };
}

function parseSearchItems(output: string): Array<{ id?: string; title?: string }> {
  try {
    const parsed = JSON.parse(output) as { ok?: boolean; data?: SearchData };
    return parsed.ok ? (parsed.data?.items ?? []) : [];
  } catch {
    return [];
  }
}

export class DeterministicAgentModelClient implements AgentModelClient {
  async create(request: AgentModelRequest): Promise<AgentModelResponse> {
    const message = userMessage(request);
    const lowered = message.toLowerCase();
    const lastOutput = request.input.findLast(isFunctionOutput);
    const calls = request.input.filter(
      (value): value is { type: "function_call"; name: string } =>
        typeof value === "object" && value !== null && "type" in value &&
        value.type === "function_call" && "name" in value && typeof value.name === "string",
    );
    const lastCall = calls.at(-1);

    if (lastOutput && lastCall?.name === "searchTask" &&
        /\b(complete|finish|delete|remove|update|change)\b/.test(lowered)) {
      const items = parseSearchItems(lastOutput.output);
      if (items.length === 0) return { outputText: "I could not find a matching task.", output: [] };
      if (items.length > 1) {
        const choices = items.slice(0, 5).map((item) => item.title ?? item.id).join(", ");
        return { outputText: `I found multiple matches: ${choices}. Which exact task?`, output: [] };
      }
      const taskId = items[0]?.id;
      if (!taskId) return { outputText: "The matching task had no usable ID.", output: [] };
      if (/\b(complete|finish)\b/.test(lowered)) return call("completeTask", { taskId });
      if (/\b(delete|remove)\b/.test(lowered)) return call("deleteTask", { taskId });
      const priority = lowered.match(/\b(high|medium|low)\b/)?.[1] ?? null;
      if (priority) {
        return call("updateTask", {
          taskId,
          updateFields: ["priority"],
          title: null,
          notes: null,
          courseId: null,
          status: null,
          priority,
          dueDate: null,
        });
      }
      return { outputText: "Tell me which field to update.", output: [] };
    }

    if (lastOutput) {
      return { outputText: "The requested task action completed. Check the board for the result.", output: [] };
    }

    if (/\b(add|create)\b/.test(lowered)) {
      const courseId = message.match(/\b(cs3481|ge2324)\b/i)?.[1]?.toLowerCase() ?? null;
      const priority = lowered.match(/\b(high|medium|low)\b/)?.[1] ?? null;
      const dueDate = message.match(/\b\d{4}-\d{2}-\d{2}\b/)?.[0] ?? null;
      const title = message
        .replace(/^\s*(please\s+)?(add|create)\s+(a\s+)?/i, "")
        .replace(/\s+due\s+\d{4}-\d{2}-\d{2}\b/i, "")
        .replace(/\b(high|medium|low)\s+priority\b/i, "")
        .replace(/\s+/g, " ")
        .replace(/[.!?]+$/, "")
        .trim();
      return call("createTask", {
        title: title || "Study task",
        notes: null,
        courseId,
        priority,
        dueDate,
        sourceCitation: null,
      });
    }

    if (/\b(find|search|list|show|complete|finish|delete|remove|update|change)\b/.test(lowered)) {
      return call("searchTask", searchArguments(message));
    }
    return {
      outputText: "I can create, find, update, complete, or delete study tasks.",
      output: [],
    };
  }
}
