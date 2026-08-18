import cors from "cors";
import express, { type ErrorRequestHandler, type Request } from "express";
import rateLimit from "express-rate-limit";
import helmet from "helmet";

import type { AuthStrategy } from "./auth.js";
import { AgentError, HttpError } from "./errors.js";
import {
  validateChat,
  validateCreateTask,
  validateUpdateTask,
} from "./http/validation.js";
import type { TaskRepository } from "./repositories/tasks.js";
import type { ModelRateLimiter } from "./rate-limit.js";
import type { AgentService } from "./services/agent.js";
import type { TaskListQuery, TaskStatus } from "./types.js";


export interface AppDependencies {
  repository: TaskRepository;
  agentService: AgentService;
  webOrigin: string;
  authStrategy: AuthStrategy;
  modelRateLimiter: ModelRateLimiter;
  readinessCheck: () => boolean;
}

function requireUser(request: Request, strategy: AuthStrategy): string {
  const userId = strategy.userId(request);
  if (userId === null) {
    throw new HttpError(401, "UNAUTHENTICATED", "A valid sign-in session is required.");
  }
  return userId;
}

function positiveInteger(value: unknown, fallback: number, maximum: number): number {
  if (value === undefined) return fallback;
  if (typeof value !== "string" || !/^[0-9]+$/.test(value)) {
    throw new HttpError(400, "VALIDATION_ERROR", "Pagination values must be integers.");
  }
  const parsed = Number.parseInt(value, 10);
  if (parsed < 1 || parsed > maximum) {
    throw new HttpError(
      400,
      "VALIDATION_ERROR",
      `Pagination value must be between 1 and ${maximum}.`,
    );
  }
  return parsed;
}

function optionalString(request: Request, name: string, maximum: number): string | undefined {
  const value = request.query[name];
  if (value === undefined) return undefined;
  if (typeof value !== "string" || value.length > maximum) {
    throw new HttpError(400, "VALIDATION_ERROR", `${name} must be a short string.`);
  }
  return value;
}

export function createApp(dependencies: AppDependencies): express.Express {
  const application = express();
  application.disable("x-powered-by");
  application.use(helmet());
  application.use((_request, response, next) => {
    response.setHeader("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
    next();
  });
  application.use(
    cors({
      origin: dependencies.webOrigin,
      methods: ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
      allowedHeaders: ["Authorization", "Content-Type"],
      credentials: false,
    }),
  );
  application.use(express.json({ limit: "64kb" }));
  application.use(dependencies.authStrategy.middleware);
  application.use(
    rateLimit({
      windowMs: 60_000,
      limit: 120,
      standardHeaders: true,
      legacyHeaders: false,
      handler: (_request, response) => {
        response.status(429).json({
          error: {
            code: "RATE_LIMITED",
            message: "Too many requests. Please try again shortly.",
            details: {},
          },
        });
      },
    }),
  );

  application.get("/health", (_request, response) => {
    if (!dependencies.readinessCheck()) {
      response.status(503).json({ status: "unavailable", service: "agent-api" });
      return;
    }
    response.json({ status: "ok", service: "agent-api" });
  });

  application.get("/api/tasks", (request, response) => {
    const userId = requireUser(request, dependencies.authStrategy);
    const page = positiveInteger(request.query.page, 1, 10_000);
    const pageSize = positiveInteger(request.query.pageSize, 50, 100);
    const courseId = optionalString(request, "courseId", 50);
    const status = optionalString(request, "status", 20);
    const queryText = optionalString(request, "q", 200);
    if (status !== undefined && !["todo", "in_progress", "completed"].includes(status)) {
      throw new HttpError(400, "VALIDATION_ERROR", "status is not valid.");
    }
    const query: TaskListQuery = { page, pageSize };
    if (courseId !== undefined) query.courseId = courseId;
    if (status !== undefined) query.status = status as TaskStatus;
    if (queryText !== undefined) query.query = queryText;
    response.json(dependencies.repository.list(userId, query));
  });

  application.post("/api/tasks", (request, response) => {
    const userId = requireUser(request, dependencies.authStrategy);
    const input = validateCreateTask(request.body);
    response.status(201).json(dependencies.repository.create(userId, input));
  });

  application.patch("/api/tasks/:taskId", (request, response) => {
    const userId = requireUser(request, dependencies.authStrategy);
    const input = validateUpdateTask(request.body);
    const task = dependencies.repository.update(userId, request.params.taskId ?? "", input);
    if (task === null) {
      throw new HttpError(404, "TASK_NOT_FOUND", "The task was not found.");
    }
    response.json(task);
  });

  application.delete("/api/tasks/:taskId", (request, response) => {
    const userId = requireUser(request, dependencies.authStrategy);
    if (!dependencies.repository.delete(userId, request.params.taskId ?? "")) {
      throw new HttpError(404, "TASK_NOT_FOUND", "The task was not found.");
    }
    response.status(204).send();
  });

  application.post("/api/agent/chat", async (request, response) => {
    const userId = requireUser(request, dependencies.authStrategy);
    const { message } = validateChat(request.body);
    if (!dependencies.modelRateLimiter.consume(userId)) {
      throw new HttpError(
        429,
        "RATE_LIMITED",
        "Too many AI requests. Please try again shortly.",
      );
    }
    response.json(await dependencies.agentService.chat(userId, message));
  });

  application.use((_request, _response) => {
    throw new HttpError(404, "ROUTE_NOT_FOUND", "The route was not found.");
  });

  const errorHandler: ErrorRequestHandler = (error: unknown, _request, response, _next) => {
    if (error instanceof HttpError) {
      response.status(error.statusCode).json({
        error: { code: error.code, message: error.message, details: error.details },
      });
      return;
    }
    if (error instanceof AgentError) {
      response.status(502).json({
        error: { code: error.code, message: error.message, details: {} },
      });
      return;
    }
    if (
      typeof error === "object" &&
      error !== null &&
      "type" in error &&
      error.type === "entity.parse.failed"
    ) {
      response.status(400).json({
        error: { code: "MALFORMED_JSON", message: "The JSON body is invalid.", details: {} },
      });
      return;
    }
    console.error("Unhandled Agent API error", error);
    response.status(500).json({
      error: { code: "INTERNAL_ERROR", message: "An internal error occurred.", details: {} },
    });
  };
  application.use(errorHandler);
  return application;
}
