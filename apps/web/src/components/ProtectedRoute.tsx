import { Outlet } from "react-router-dom";

import { SignedOutActions, useCourseMateAuth } from "../auth/AuthProvider";


export function ProtectedRoute() {
  const auth = useCourseMateAuth();
  if (!auth.isLoaded) {
    return <div className="page centered-state" aria-busy="true">Checking your session…</div>;
  }
  if (!auth.isSignedIn) {
    return (
      <section className="page centered-state auth-gate" aria-labelledby="auth-gate-title">
        <span className="eyebrow">Private workspace</span>
        <h1 id="auth-gate-title">Sign in to continue</h1>
        <p>Your questions, conversations, and study tasks stay attached to your account.</p>
        <SignedOutActions />
      </section>
    );
  }
  return <Outlet />;
}
