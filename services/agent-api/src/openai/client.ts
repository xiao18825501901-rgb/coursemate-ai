import OpenAI from "openai";
import type {
  FunctionTool,
  ResponseInput,
} from "openai/resources/responses/responses.js";

import { AgentError } from "../errors.js";
import { TOOL_DEFINITIONS } from "../tools/schemas.js";


export interface AgentModelRequest {
  model: string;
  instructions: string;
  input: unknown[];
  tools: typeof TOOL_DEFINITIONS;
  parallelToolCalls: false;
}

export interface AgentModelResponse {
  outputText: string;
  output: unknown[];
}

export interface AgentModelClient {
  create(request: AgentModelRequest): Promise<AgentModelResponse>;
}

export const DEEPSEEK_BASE_URL = "https://api.deepseek.com";

export class OpenAIResponsesClient implements AgentModelClient {
  private readonly client: OpenAI;

  constructor(apiKey: string, client?: OpenAI, baseURL?: string) {
    this.client = client ?? new OpenAI({
      apiKey,
      baseURL: baseURL || DEEPSEEK_BASE_URL,
      maxRetries: 0,
      timeout: 90_000,
    });
  }

  async create(request: AgentModelRequest): Promise<AgentModelResponse> {
    let response;
    try {
      response = await this.client.responses.create({
        model: request.model,
        instructions: request.instructions,
        input: request.input as ResponseInput,
        tools: request.tools as unknown as FunctionTool[],
        parallel_tool_calls: request.parallelToolCalls,
        max_output_tokens: 1_200,
        store: false,
        // DeepSeek Responses: native thinking explicitly off so the agent only
        // projects output_text / function_call items (no reasoning chain). This
        // is a documented DeepSeek field; Qwen-only fields are never emitted.
        reasoning: { effort: "none" },
      });
    } catch {
      throw new AgentError(
        "MODEL_PROVIDER_FAILURE",
        "The model provider request failed; no automatic retry was attempted.",
      );
    }
    return {
      outputText: response.output_text,
      output: response.output,
    };
  }
}
