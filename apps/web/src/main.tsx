import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { ClerkAuthProvider, TestAuthProvider } from "./auth/AuthProvider";
import "./styles.css";


const root = document.getElementById("root");
if (root === null) {
  throw new Error("CourseMate root element was not found.");
}

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;
const testToken = import.meta.env.DEV ? import.meta.env.VITE_AUTH_TEST_TOKEN : undefined;

let application;
if (testToken) {
  application = <TestAuthProvider token={testToken}><App /></TestAuthProvider>;
} else if (publishableKey) {
  application = <ClerkAuthProvider publishableKey={publishableKey}><App /></ClerkAuthProvider>;
} else {
  application = (
    <main className="page centered-state" role="alert">
      <h1>Authentication is not configured</h1>
      <p>Set VITE_CLERK_PUBLISHABLE_KEY before starting CourseMate.</p>
    </main>
  );
}

createRoot(root).render(<StrictMode>{application}</StrictMode>);
