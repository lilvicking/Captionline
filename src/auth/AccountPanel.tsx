import { useState } from "react";
import { CalendarClock, LogOut, Mail, RefreshCw, User as UserIcon, X } from "lucide-react";
import { useAuth } from "./AuthContext";

type AccountPanelProps = {
  onClose: () => void;
};

/** "3.2 / 10 minutes used" on Free, "250 / 500 minutes used" on a paid plan. */
function usageSummary(used: number, allowance: number): string {
  const format = (value: number) =>
    value >= 100 ? Math.round(value).toLocaleString() : value.toFixed(1);

  return `${format(used)} / ${format(allowance)} minutes used`;
}

function formatResetDate(iso: string): string {
  const date = new Date(iso);

  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function AccountPanel({ onClose }: AccountPanelProps) {
  const { status, user, account, refresh, signIn, signUp, signOut } = useAuth();

  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

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

  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
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
            <button
              className="account__refresh"
              type="button"
              onClick={() => void handleRefresh()}
              disabled={refreshing}
              aria-label="Refresh usage"
              title="Refresh usage"
            >
              <RefreshCw size={14} className={refreshing ? "is-spinning" : ""} aria-hidden="true" />
            </button>
          </p>

          {account ? (
            <div className="account__plan">
              <p className="account__plan-name">
                {account.plan_label}
                {account.billed_annually ? " · billed annually" : ""}
              </p>

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

              <p className="account__remaining">
                {account.processing_remaining_minutes.toFixed(1)} minutes remaining
              </p>

              <p className="account__hint">
                <CalendarClock size={13} aria-hidden="true" />
                Allowance resets {formatResetDate(account.usage_period_ends_at)}
                {account.billed_annually ? " · billed annually" : ""}
              </p>

              <p className="account__hint">
                Finished preview:{" "}
                {account.has_full_preview
                  ? "full video"
                  : `first ${account.preview_limit_seconds ?? 30} seconds`}
                {account.can_export ? " · export included" : ""}
              </p>
            </div>
          ) : (
            <p className="sheet__body">Usage details are unavailable right now.</p>
          )}

          <button
            className="button button--ghost button--block"
            type="button"
            onClick={() => void signOut()}
          >
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
              : "Free accounts get 10 processing minutes a month and a 30-second finished preview."}
          </p>
        </form>
      )}
    </div>
  );
}
