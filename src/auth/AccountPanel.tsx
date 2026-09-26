import { useState } from "react";
import { LogOut, Mail, User as UserIcon, X } from "lucide-react";
import { useAuth } from "./AuthContext";

type AccountPanelProps = {
  onClose: () => void;
};

/** Formats "3.2 / 10 minutes used" for the usage line. */
function usageSummary(used: number, allowance: number): string {
  return `${used.toFixed(1)} / ${allowance.toFixed(1)} minutes used`;
}

export function AccountPanel({ onClose }: AccountPanelProps) {
  const { status, user, account, signIn, signUp, signOut } = useAuth();

  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isAuthenticated = status === "authenticated" && user !== null;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);

    try {
      if (mode === "in") {
        await signIn(email.trim(), password);
      } else {
        await signUp(email.trim(), password);
      }
      setPassword("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sheet" role="dialog" aria-label="Account">
      <div className="sheet__head">
        <h2 className="sheet__title">Account</h2>
        <button className="sheet__close" type="button" onClick={onClose} aria-label="Close">
          <X size={16} aria-hidden="true" />
        </button>
      </div>

      {status === "loading" ? (
        <p className="sheet__body">Checking your session…</p>
      ) : isAuthenticated ? (
        <div className="account">
          <p className="account__identity">
            <UserIcon size={16} aria-hidden="true" />
            <span className="account__email">{user.email}</span>
          </p>

          {account ? (
            <div className="account__plan">
              <p className="account__plan-name">{account.plan_label} plan</p>
              <p className="account__usage">
                {usageSummary(
                  account.processing_used_minutes,
                  account.processing_allowance_minutes,
                )}
              </p>

              <div
                className="meter"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={account.processing_allowance_minutes}
                aria-valuenow={account.processing_used_minutes}
                aria-label="Monthly processing used"
              >
                <span
                  className="meter__fill"
                  style={{
                    width: `${Math.min(
                      account.processing_allowance_minutes > 0
                        ? (account.processing_used_minutes /
                            account.processing_allowance_minutes) *
                            100
                        : 0,
                      100,
                    )}%`,
                  }}
                />
              </div>

              <p className="account__hint">
                {account.processing_remaining_minutes.toFixed(1)} minutes left this period ·
                preview {account.preview_limit_seconds === null
                  ? "unlimited"
                  : `${account.preview_limit_seconds}s`}
              </p>
            </div>
          ) : (
            <p className="sheet__body">Usage details are unavailable right now.</p>
          )}

          <button className="button button--ghost button--block" type="button" onClick={() => void signOut()}>
            <LogOut size={15} aria-hidden="true" />
            Log out
          </button>
        </div>
      ) : (
        <form className="account" onSubmit={(event) => void handleSubmit(event)}>
          <div className="segmented segmented--full">
            <button
              type="button"
              className={`segmented__option${mode === "in" ? " is-active" : ""}`}
              onClick={() => {
                setMode("in");
                setError(null);
              }}
            >
              Log in
            </button>
            <button
              type="button"
              className={`segmented__option${mode === "up" ? " is-active" : ""}`}
              onClick={() => {
                setMode("up");
                setError(null);
              }}
            >
              Sign up
            </button>
          </div>

          <label className="account__field" htmlFor="account-email">
            <span className="ctl__label">Email</span>
            <span className="account__input-wrap">
              <Mail size={15} aria-hidden="true" />
              <input
                id="account-email"
                className="account__input"
                type="email"
                autoComplete="email"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
              />
            </span>
          </label>

          <label className="account__field" htmlFor="account-password">
            <span className="ctl__label">Password</span>
            <span className="account__input-wrap">
              <input
                id="account-password"
                className="account__input"
                type="password"
                autoComplete={mode === "in" ? "current-password" : "new-password"}
                required
                minLength={8}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </span>
          </label>

          {error ? (
            <p className="account__error" role="alert">
              {error}
            </p>
          ) : null}

          <button className="button button--primary button--block" type="submit" disabled={busy}>
            {busy ? "Working…" : mode === "in" ? "Log in" : "Create account"}
          </button>

          <p className="account__hint">
            {mode === "in"
              ? "New to Captionline? Switch to Sign up."
              : "Accounts start on the Free plan: 10 minutes of processing per month."}
          </p>
        </form>
      )}
    </div>
  );
}
