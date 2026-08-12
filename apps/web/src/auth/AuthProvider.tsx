import {
  ClerkProvider,
  SignInButton,
  SignUpButton,
  UserButton,
  useAuth as useClerkAuth,
  useUser,
} from "@clerk/react";
import { createContext, type ReactNode, useContext, useMemo } from "react";


export type GetSessionToken = () => Promise<string | null>;

interface AuthState {
  isLoaded: boolean;
  isSignedIn: boolean;
  userLabel: string | null;
  getToken: GetSessionToken;
  testMode: boolean;
}

const signedOutState: AuthState = {
  isLoaded: true,
  isSignedIn: false,
  userLabel: null,
  getToken: async () => null,
  testMode: true,
};

const AuthContext = createContext<AuthState>(signedOutState);

function ClerkSessionBridge({ children }: { children: ReactNode }) {
  const { getToken, isLoaded, isSignedIn } = useClerkAuth();
  const { user } = useUser();
  const value = useMemo<AuthState>(
    () => ({
      isLoaded,
      isSignedIn: isSignedIn === true,
      userLabel: user?.fullName ?? user?.primaryEmailAddress?.emailAddress ?? null,
      getToken,
      testMode: false,
    }),
    [getToken, isLoaded, isSignedIn, user],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function ClerkAuthProvider({
  children,
  publishableKey,
}: {
  children: ReactNode;
  publishableKey: string;
}) {
  return (
    <ClerkProvider publishableKey={publishableKey}>
      <ClerkSessionBridge>{children}</ClerkSessionBridge>
    </ClerkProvider>
  );
}

export function TestAuthProvider({
  children,
  token = "test-session-token",
  userLabel = "Test Student",
}: {
  children: ReactNode;
  token?: string | null;
  userLabel?: string;
}) {
  const value = useMemo<AuthState>(
    () => ({
      isLoaded: true,
      isSignedIn: token !== null,
      userLabel: token === null ? null : userLabel,
      getToken: async () => token,
      testMode: true,
    }),
    [token, userLabel],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useCourseMateAuth(): AuthState {
  return useContext(AuthContext);
}

export function SignedOutActions() {
  const auth = useCourseMateAuth();
  if (auth.testMode) {
    return <span className="auth-note">Sign in to open your study workspace.</span>;
  }
  return (
    <div className="auth-actions">
      <SignInButton mode="modal">
        <button className="button button-secondary" type="button">Sign in</button>
      </SignInButton>
      <SignUpButton mode="modal">
        <button className="button button-primary" type="button">Create account</button>
      </SignUpButton>
    </div>
  );
}

export function SignedInAccount() {
  const auth = useCourseMateAuth();
  if (!auth.isSignedIn) return null;
  if (auth.testMode) return <span className="account-label">{auth.userLabel}</span>;
  return (
    <div className="account-control">
      {auth.userLabel && <span className="account-label">{auth.userLabel}</span>}
      <UserButton />
    </div>
  );
}
