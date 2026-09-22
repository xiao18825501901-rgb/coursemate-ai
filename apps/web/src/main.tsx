import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { ClerkAuthProvider, TestAuthProvider } from "./auth/AuthProvider";
import { BRAND } from "./brand";
import "./styles.css";


const root = document.getElementById("root");
if (root === null) {
  throw new Error(`${BRAND.name} root element was not found.`);
}

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
/**
 * Development and E2E identity, matching the refreshed shell (`CourseMateUi.tsx`).
 *
 * Vite inlines this value only when the build was given it. A production build
 * cannot be produced with it at all: `scripts/preflight_release_build.mjs` fails
 * when `VITE_AUTH_TEST_TOKEN` is set for a production context, and
 * `scripts/verify_release_build.mjs` fails if the token string appears in the
 * emitted bundle — so this cannot silently bypass production sign-in. Reading it
 * without a `DEV` guard is what lets the built legacy entry (`index.html`) be
 * exercised by the browser acceptance suite at all.
 */
const testToken = import.meta.env.VITE_AUTH_TEST_TOKEN;

let application;
if (testToken) {
  application = <TestAuthProvider token={testToken}><App /></TestAuthProvider>;
} else if (publishableKey) {
  application = <ClerkAuthProvider publishableKey={publishableKey}><App /></ClerkAuthProvider>;
} else {
  application = (
    <main className="page centered-state" role="alert">
      <h1>Authentication is not configured</h1>
      <p>Set VITE_CLERK_PUBLISHABLE_KEY before starting {BRAND.name}.</p>
    </main>
  );
}

createRoot(root).render(<StrictMode>{application}</StrictMode>);
