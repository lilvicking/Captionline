import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
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
import { entitlementFromServer, resolvePreviewEntitlement } from "../entitlement";
import type { PreviewEntitlement } from "../entitlement";

type AuthStatus = "loading" | "authenticated" | "anonymous";

type AuthContextValue = {
  status: AuthStatus;
  user: AuthUser | null;
  account: AccountEntitlement | null;
  /**
   * Entitlement the editor enforces. Always starts at (and falls back to) the
   * free 30-second tier, so an anonymous visitor or a failed fetch can never
   * gain a wider preview.
   */
  entitlement: PreviewEntitlement;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
};

const FREE_TIER = resolvePreviewEntitlement();

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [account, setAccount] = useState<AccountEntitlement | null>(null);
  const [entitlement, setEntitlement] = useState<PreviewEntitlement>(FREE_TIER);

  const clearSession = useCallback(() => {
    storeToken(null);
    setUser(null);
    setAccount(null);
    setEntitlement(FREE_TIER);
    setStatus("anonymous");
  }, []);

  /**
   * Restores a stored session on load. Any failure signs the viewer out and
   * leaves the free tier in place rather than assuming paid access.
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
        setEntitlement(entitlementFromServer(restoredEntitlement));
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

    // Fetch entitlement straight after sign-in so the preview tier reflects the
    // account. A failure here leaves the free tier active.
    let nextEntitlement = FREE_TIER;
    let nextAccount: AccountEntitlement | null = null;

    try {
      nextAccount = await fetchEntitlement(result.access_token);
      nextEntitlement = entitlementFromServer(nextAccount);
    } catch {
      // Fail closed: keep the free tier.
    }

    setUser(result.user);
    setAccount(nextAccount);
    setEntitlement(nextEntitlement);
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
    () => ({ status, user, account, entitlement, signIn, signUp, signOut }),
    [status, user, account, entitlement, signIn, signUp, signOut],
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
