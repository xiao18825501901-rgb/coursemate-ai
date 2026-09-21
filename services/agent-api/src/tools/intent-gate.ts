export type ToolIntentMode = "off" | "advisory" | "enforce";

export type ToolIntentVerdict =
  | "ALLOW"
  | "REQUIRE_CONFIRMATION"
  | "REFUSE_UNAUTHORIZED"
  | "REFUSE_STALE";

export interface ToolIntentRecord {
  mode: ToolIntentMode;
  checked: boolean;
  verdict: ToolIntentVerdict;
  reason: string;
  usedJev: boolean;
  jevLabel: string | null;
  receiptId: string | null;
  path: string;
  jevCalls: number;
}

export interface ToolIntentRequest {
  userMessage: string;
  proposedTool: string;
  toolArguments: Record<string, unknown>;
  actorScope: string;
  actorPermissions: string[];
  requiredPermissions: string[];
  isReadOnly: boolean;
  explicit: boolean;
  objectRevision: string | null;
  currentRevision: string | null;
  ownerUserId: string;
  authorizationScope: string;
  courseId: string | null;
  workspaceId: string | null;
  materialRevision: string | null;
  nodeId: string | null;
  specVersion: string | null;
}

export interface FetchInit {
  method: string;
  headers: Record<string, string>;
  body: string;
  signal: AbortSignal;
}

export type FetchImpl = (url: string, init: FetchInit) => Promise<Response>;

export interface JevToolIntentGateOptions {
  mode: ToolIntentMode;
  url?: string;
  token?: string;
  timeoutMs?: number;
  fetchImpl?: FetchImpl;
}

const DEFAULT_TIMEOUT_MS = 1_500;
const INTERNAL_TOKEN_HEADER = "X-CourseMate-Internal-Token";

const VERDICTS = new Set<string>([
  "ALLOW",
  "REQUIRE_CONFIRMATION",
  "REFUSE_UNAUTHORIZED",
  "REFUSE_STALE",
]);

function toVerdict(value: unknown): ToolIntentVerdict | null {
  if (typeof value === "string" && VERDICTS.has(value)) {
    return value as ToolIntentVerdict;
  }
  return null;
}

export class JevToolIntentGate {
  private readonly mode: ToolIntentMode;
  private readonly url: string | undefined;
  private readonly token: string | undefined;
  private readonly timeoutMs: number;
  private readonly fetchImpl: FetchImpl;

  constructor(options: JevToolIntentGateOptions) {
    this.mode = options.mode;
    this.url = options.url;
    this.token = options.token;
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.fetchImpl = options.fetchImpl ?? (globalThis.fetch as FetchImpl);
  }

  async checkToolIntent(request: ToolIntentRequest): Promise<ToolIntentRecord> {
    if (this.mode === "off") {
      return {
        mode: "off",
        checked: false,
        verdict: "ALLOW",
        reason: "gate_off",
        usedJev: false,
        jevLabel: null,
        receiptId: null,
        path: "disabled",
        jevCalls: 0,
      };
    }
    if (!this.url || !this.token) {
      return this.unavailable();
    }
    try {
      const response = await this.fetchImpl(this.url, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          [INTERNAL_TOKEN_HEADER]: this.token,
        },
        body: JSON.stringify({
          user_message: request.userMessage,
          proposed_tool: request.proposedTool,
          tool_arguments: request.toolArguments,
          actor_scope: request.actorScope,
          actor_permissions: request.actorPermissions,
          required_permissions: request.requiredPermissions,
          is_read_only: request.isReadOnly,
          explicit: request.explicit,
          object_revision: request.objectRevision,
          current_revision: request.currentRevision,
          owner_user_id: request.ownerUserId,
          authorization_scope: request.authorizationScope,
          course_id: request.courseId,
          workspace_id: request.workspaceId,
          material_revision: request.materialRevision,
          node_id: request.nodeId,
          spec_version: request.specVersion,
        }),
        signal: AbortSignal.timeout(this.timeoutMs),
      });
      if (!response.ok) {
        return this.unavailable();
      }
      const payload: unknown = await response.json();
      return this.fromPayload(payload);
    } catch {
      return this.unavailable();
    }
  }

  private unavailable(): ToolIntentRecord {
    return {
      mode: this.mode,
      checked: true,
      verdict: "REQUIRE_CONFIRMATION",
      reason: "intent:unavailable",
      usedJev: false,
      jevLabel: null,
      receiptId: null,
      path: "fallback:unavailable",
      jevCalls: 0,
    };
  }

  private fromPayload(payload: unknown): ToolIntentRecord {
    if (typeof payload !== "object" || payload === null) {
      return this.unavailable();
    }
    const body = payload as Record<string, unknown>;
    const verdict = toVerdict(body["verdict"]);
    if (verdict === null) {
      return this.unavailable();
    }
    return {
      mode: this.mode,
      checked: true,
      verdict,
      reason: typeof body["reason"] === "string" ? body["reason"] : "intent:unavailable",
      usedJev: body["used_jev"] === true,
      jevLabel: typeof body["jev_label"] === "string" ? body["jev_label"] : null,
      receiptId: typeof body["receipt_id"] === "string" ? body["receipt_id"] : null,
      path: typeof body["path"] === "string" ? body["path"] : "unknown",
      jevCalls: typeof body["jev_calls"] === "number" ? body["jev_calls"] : 0,
    };
  }
}
