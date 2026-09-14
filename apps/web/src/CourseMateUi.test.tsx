import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The refreshed shell publishes the verified Clerk session to the delivered
 * `api.js` through `window.CourseMateAuth`. Every browser journey so far ran with
 * the backend test verifier, which uses the development bridge, so this production
 * path had no coverage at all. These tests exercise it directly.
 */

const getToken = vi.fn(async () => "clerk-session-token");
const openSignIn = vi.fn();
const signOut = vi.fn(async () => undefined);

vi.mock("@clerk/react", () => ({
  ClerkProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: () => ({ getToken }),
  useClerk: () => ({ openSignIn, signOut }),
}));

// The delivered shell is plain JSX with no type declarations; keep it honest here.
vi.mock("./ui/App.jsx", () => ({
  App: () => <div data-testid="course-mate-app" />,
}));

vi.mock("katex", () => ({
  default: { renderToString: () => "<math></math>" },
}));

import { CourseMateUi } from "./CourseMateUi";

/**
 * A production deployment sets the Clerk publishable key and no test token, which
 * is exactly the configuration these tests must exercise.
 */
beforeEach(() => {
  vi.stubEnv("VITE_CLERK_PUBLISHABLE_KEY", "pk_test_coursemate");
  vi.stubEnv("VITE_AUTH_TEST_TOKEN", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
  delete window.CourseMateAuth;
  vi.clearAllMocks();
});

describe("production Clerk auth bridge", () => {
  it("publishes a token getter that resolves the real Clerk session token", async () => {
    render(<CourseMateUi />);

    await waitFor(() => expect(window.CourseMateAuth).toBeDefined());
    await expect(window.CourseMateAuth?.getToken()).resolves.toBe("clerk-session-token");
    expect(getToken).toHaveBeenCalled();
  });

  it("exposes an unsubscribe function from subscribe", async () => {
    render(<CourseMateUi />);
    await waitFor(() => expect(window.CourseMateAuth).toBeDefined());

    const unsubscribe = window.CourseMateAuth?.subscribe(() => undefined);
    expect(typeof unsubscribe).toBe("function");
    expect(() => unsubscribe?.()).not.toThrow();
  });

  it("routes sign-in through Clerk's own modal", async () => {
    render(<CourseMateUi />);
    await waitFor(() => expect(window.CourseMateAuth).toBeDefined());

    window.CourseMateAuth?.signIn();
    expect(openSignIn).toHaveBeenCalledTimes(1);
  });

  it("routes sign-out through Clerk and resolves", async () => {
    render(<CourseMateUi />);
    await waitFor(() => expect(window.CourseMateAuth).toBeDefined());

    await expect(window.CourseMateAuth?.signOut()).resolves.toBeUndefined();
    expect(signOut).toHaveBeenCalledTimes(1);
  });

  it("removes the bridge when the shell unmounts", async () => {
    const view = render(<CourseMateUi />);
    await waitFor(() => expect(window.CourseMateAuth).toBeDefined());

    view.unmount();
    expect(window.CourseMateAuth).toBeUndefined();
  });

  it("fails closed without a publishable key instead of rendering the shell", () => {
    const previous = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
    // A production build without Clerk must not silently render an unauthenticated
    // shell; it shows the configuration boundary instead.
    vi.stubEnv("VITE_CLERK_PUBLISHABLE_KEY", "");
    vi.stubEnv("VITE_AUTH_TEST_TOKEN", "");
    try {
      const { container } = render(<CourseMateUi />);
      expect(container.textContent).toContain("认证未配置");
      expect(window.CourseMateAuth).toBeUndefined();
    } finally {
      vi.unstubAllEnvs();
      void previous;
    }
  });
});
