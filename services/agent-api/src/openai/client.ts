import OpenAI from "openai";
import type {
  FunctionTool,
  ResponseInput,
} from "openai/resources/responses/responses.js";

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
    this.client = client ?? new OpenAI({ apiKey, ...(baseURL ? { baseURL } : {}) });
  }

  async create(request: AgentModelRequest): Promise<AgentModelResponse> {
    const response = await this.client.responses.create({
      model: request.model,
      instructions: request.instructions,
      input: request.input as ResponseInput,
      tools: request.tools as unknown as FunctionTool[],
      parallel_tool_calls: request.parallelToolCalls,
      max_output_tokens: 1_200,
      store: false,
    });
    return {
      outputText: response.output_text,
      output: response.output,
    };
  }
}
