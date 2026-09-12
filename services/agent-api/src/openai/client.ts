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

export class OpenAIResponsesClient implements AgentModelClient {
  private readonly client: OpenAI;

  constructor(apiKey: string, client?: OpenAI, baseURL?: string) {
    this.client = client ?? new OpenAI({
      apiKey,
      ...(baseURL ? { baseURL } : {}),
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
