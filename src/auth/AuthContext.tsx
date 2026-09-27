import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { TranscriptionError } from "../lib/api";
import {
  fetchCurrentUser,
  fetchEntitlement,
  getStoredToken,
  loginAccount,
  logoutAccount,
  registerAccount,
  storeToken,
} from "../lib/auth";
import type { AccountEntitlement, AuthUser } from "../lib/auth";

type AuthStatus = "loading" | "authenticated" | "anonymous";

/**
 * True when an error means the bearer token is no longer accepted.
 *
 * A 401 is the server saying this session is dead, so the UI must not keep
 * claiming to be signed in. Anything else (offline, timeout, 5xx) may be
 * transient and must not throw away a valid session.
 */
export function isUnauthorized(error: unknown): boolean {
  return error instanceof TranscriptionError && error.status === 401;
}

type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  account: AccountEntitlement | null;
  /** Whether the signed-in account is on a paid plan. */
  isPaidPlan: boolean;
  /** Re-reads plan and usage from the server. Called after transcription. */
  refresh: () => Promise<void>;
  /**
   * Drops the local session without calling the server.
   *
   * Used when an endpoint rejects the stored token (HTTP 401). The server has
   * already decided the session is gone, so the client stops pretending the
   * account is signed in rather than leaving a dead token in the UI.
   */
  expireSession: () => void;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [account, setAccount] = useState<AccountEntitlement | null>(null);

  const clearSession = useCallback(() => {
    storeToken(null);
    setUser(null);
    setAccount(null);
    setStatus("anonymous");
  }, []);

  /**
   * Restores a stored session on load.
   *
   * Unlike `refresh`, every failure signs the viewer out here: there is no
   * verified identity to preserve on a cold start, so a token that cannot be
   * confirmed is discarded rather than carried forward.
   */
  useEffect(() => {
    const token = getStoredToken();

    if (!token) {
      setStatus("anonymous");
      return;
    }

    let cancelled = false;

    const restore = async () => {
      try {
        const [restoredUser, restoredEntitlement] = await Promise.all([
          fetchCurrentUser(token),
          fetchEntitlement(token),
        ]);

        if (cancelled) {
          return;
        }

        setUser(restoredUser);
        setAccount(restoredEntitlement);
        setStatus("authenticated");
      } catch {
        if (!cancelled) {
          clearSession();
        }
      }
    };

    void restore();

    return () => {
      cancelled = true;
    };
  }, [clearSession]);

  const completeSignIn = useCallback(async (email: string, password: string, mode: "in" | "up") => {
    const result =
      mode === "in" ? await loginAccount(email, password) : await registerAccount(email, password);

    storeToken(result.access_token);

    // Fetch entitlement straight after sign-in so plan and usage reflect the
    // account. A failure here leaves usage unavailable rather than guessed.
    let nextAccount: AccountEntitlement | null = null;

    try {
      nextAccount = await fetchEntitlement(result.access_token);
    } catch {
      // Usage is simply unavailable until the next refresh.
    }

    setUser(result.user);
    setAccount(nextAccount);
    setStatus("authenticated");
  }, []);

  const signIn = useCallback(
    (email: string, password: string) => completeSignIn(email, password, "in"),
    [completeSignIn],
  );

  const signUp = useCallback(
    (email: string, password: string) => completeSignIn(email, password, "up"),
    [completeSignIn],
  );

  /**
   * Re-reads entitlement and usage. Used after a transcription so the usage
   * meter reflects what was just spent, and after a Stripe redirect returns.
   *
   * A 401 means the token is no longer valid, so the session is cleared and the
   * viewer is signed out. Every other failure keeps the last known state.
   */
  const refresh = useCallback(async () => {
    const token = getStoredToken();

    if (!token) {
      return;
    }

    try {
      setAccount(await fetchEntitlement(token));
    } catch (error) {
      if (isUnauthorized(error)) {
        clearSession();
        return;
      }
      // Keep the last known state; the server remains the authority.
    }
  }, [clearSession]);

  const expireSession = useCallback(() => {
    clearSession();
  }, [clearSession]);

  const signOut = useCallback(async () => {
    const token = getStoredToken();

    // Revoke server-side when possible, but always clear locally regardless.
    if (token) {
      try {
        await logoutAccount(token);
      } catch {
        // A failed revoke must not trap the user in a signed-in UI.
      }
    }

    clearSession();
  }, [clearSession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      account,
      isPaidPlan: account?.is_paid_plan === true,
      refresh,
      expireSession,
      signIn,
      signUp,
      signOut,
    }),
    [status, user, account, refresh, expireSession, signIn, signUp, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);

  if (context === null) {
    throw new Error("useAuth must be used inside an AuthProvider.");
  }

  return context;
}
