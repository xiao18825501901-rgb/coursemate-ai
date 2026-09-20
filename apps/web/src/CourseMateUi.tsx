import { ClerkProvider, useAuth, useClerk } from "@clerk/react";
import katex from "katex";
import { useEffect } from "react";

import { App as CourseMateApp } from "./ui/App.jsx";

import "./ui/styles.css";
import "./ui/styles-extra.css";
import "./ui/theme.css";

/**
 * The new CourseMate shell renders KaTeX to MathML and refuses to build React
 * elements from any other model HTML, so it only needs the render entry point.
 */
window.CourseMateMath = katex;

interface CourseMateAuthBridge {
  getToken: () => Promise<string | null>;
  subscribe: (listener: () => void) => () => void;
  signIn: () => void;
  signOut: () => Promise<void>;
}

declare global {
  interface Window {
    CourseMateMath?: typeof katex;
    CourseMateAuth?: CourseMateAuthBridge;
  }
}

/**
 * Development and E2E identity, mirroring the existing `VITE_AUTH_TEST_TOKEN`
 * convention in `main.tsx`.
 *
 * The project's E2E runs authenticate with the backend's test verifier, which
 * accepts `Bearer test-session-token`. Vite inlines this value only when the build
 * was given it; a production build without the variable leaves it undefined and
 * falls through to Clerk, so this cannot silently bypass production sign-in.
 */
const testToken = import.meta.env.VITE_AUTH_TEST_TOKEN;

function TestAuthBridge({ token }: { token: string }) {
  useEffect(() => {
    window.CourseMateAuth = {
      getToken: async () => token,
      subscribe: () => () => undefined,
      signIn: () => undefined,
      signOut: async () => undefined,
    };
    return () => {
      delete window.CourseMateAuth;
    };
  }, [token]);

  return <CourseMateApp />;
}

/**
 * Publish the already-verified Clerk session to the new shell.
 *
 * The delivered `api.js` reads a token getter and an auth subscription from
 * `window.CourseMateAuth`; this bridge supplies both from the same Clerk provider
 * the rest of CourseMate uses, so no second authentication system exists and the
 * bearer token is never handed to React through an environment variable.
 */
function AuthBridge() {
  const { getToken } = useAuth();
  const clerk = useClerk();

  useEffect(() => {
    window.CourseMateAuth = {
      getToken: () => getToken(),
      subscribe: () => () => undefined,
      signIn: () => {
        // The signed-out login card only exists inside the new shell document,
        // and the shell is the default entry at `/`, so after sign-in Clerk must
        // land back on the new dashboard rather than any legacy route.
        void clerk.openSignIn({
          fallbackRedirectUrl: `${window.location.origin}/`,
        });
      },
      signOut: async () => {
        await clerk.signOut();
      },
    };
    return () => {
      delete window.CourseMateAuth;
    };
  }, [clerk, getToken]);

  return <CourseMateApp />;
}

export function CourseMateUi() {
  const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
  if (testToken) {
    return <TestAuthBridge token={testToken} />;
  }
  if (!publishableKey) {
    return (
      <div className="login-page">
        <div className="login-card">
          <h1>认证未配置</h1>
          <p>部署时需要设置 VITE_CLERK_PUBLISHABLE_KEY。</p>
        </div>
      </div>
    );
  }
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <AuthBridge />
    </ClerkProvider>
  );
}

export default CourseMateUi;
