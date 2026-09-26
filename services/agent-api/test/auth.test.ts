import { beforeEach, describe, expect, it, vi } from "vitest";

const clerkMocks = vi.hoisted(() => ({
  clerkMiddleware: vi.fn(() => (_request: unknown, _response: unknown, next: () => void) => next()),
  getAuth: vi.fn(() => ({ userId: null })),
}));

vi.mock("@clerk/express", () => clerkMocks);

import { createClerkAuthStrategy } from "../src/auth.js";
import { loadConfig } from "../src/config.js";


describe("Agent Clerk authentication", () => {
  beforeEach(() => clerkMocks.clerkMiddleware.mockClear());

  it("passes every configured browser origin to Clerk authorizedParties", () => {
    const config = loadConfig({
      CLERK_PUBLISHABLE_KEY: "pk_test_example",
      CLERK_SECRET_KEY: "sk_test_example",
      WEB_ORIGIN: "https://qqttai.com",
      WEB_ALLOWED_ORIGINS: "https://qqttai.com,https://coursejesus.com",
    });

    createClerkAuthStrategy({
      publishableKey: config.clerkPublishableKey,
      secretKey: config.clerkSecretKey,
      authorizedParties: config.webAllowedOrigins,
    });

    expect(clerkMocks.clerkMiddleware).toHaveBeenCalledWith(
      expect.objectContaining({
        authorizedParties: ["https://qqttai.com", "https://coursejesus.com"],
      }),
    );
  });
});
