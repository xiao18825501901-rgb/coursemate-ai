import { ClerkProvider, useAuth, useClerk } from "@clerk/react";
import katex from "katex";
import { useEffect } from "react";

import { App as CourseMateApp } from "./ui/App.jsx";

import "./ui/styles.css";
import "./ui/styles-extra.css";

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
        void clerk.openSignIn();
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
