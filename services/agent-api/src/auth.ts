import { clerkMiddleware, getAuth } from "@clerk/express";
import type { Request, RequestHandler } from "express";


export interface AuthStrategy {
  middleware: RequestHandler;
  userId(request: Request): string | null;
}

export interface ClerkAuthOptions {
  publishableKey: string;
  secretKey: string;
  jwtKey?: string;
  authorizedParties: string[];
}

export function createClerkAuthStrategy(options: ClerkAuthOptions): AuthStrategy {
  return {
    middleware: clerkMiddleware({
      publishableKey: options.publishableKey,
      secretKey: options.secretKey,
      ...(options.jwtKey === undefined ? {} : { jwtKey: options.jwtKey }),
      authorizedParties: options.authorizedParties,
      acceptsToken: "session_token",
    }),
    userId: (request) => getAuth(request).userId,
  };
}

export function createTestAuthStrategy(userId: string): AuthStrategy {
  return {
    middleware: (_request, _response, next) => next(),
    userId: (request) =>
      request.get("authorization") === "Bearer test-session-token" ? userId : null,
  };
}
