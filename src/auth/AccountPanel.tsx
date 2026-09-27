import { useState } from "react";
import {
  CalendarClock,
  KeyRound,
  LogOut,
  Mail,
  RefreshCw,
  User as UserIcon,
  X,
} from "lucide-react";
import { useAuth } from "./AuthContext";
import { ForgotPasswordForm } from "./ForgotPasswordForm";
import { changePassword } from "../lib/auth";
import { getStoredToken } from "../lib/auth";

type AccountPanelProps = {
  onClose: () => void;
};

type PanelView = "in" | "up" | "forgot" | "password";

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

  const [view, setView] = useState<PanelView>("in");
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  // Change-password state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordNotice, setPasswordNotice] = useState<string | null>(null);

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

  const handleChangePassword = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setPasswordNotice(null);

    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters long.");
      return;
    }

    if (newPassword !== confirmPassword) {
      setError("The two passwords do not match.");
      return;
    }

    const token = getStoredToken();
    if (!token) {
      setError("Your session expired. Please log in again.");
      return;
    }

    setBusy(true);

    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setPasswordNotice("Password changed. Other sessions were signed out.");
      setView("in");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "We could not change your password.");
    } finally {
      setBusy(false);
    }
  };

  if (view === "forgot") {
    return (
      <div className="sheet" role="dialog" aria-label="Forgot password">
        <div className="sheet__head">
          <h2 className="sheet__title">Account</h2>
          <button className="sheet__close" type="button" onClick={onClose} aria-label="Close">
            <X size={16} aria-hidden="true" />
          </button>
        </div>

        <ForgotPasswordForm onBack={() => setView("in")} />
      </div>
    );
  }

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

          {passwordNotice ? (
            <p className="account__confirm" role="status">
              {passwordNotice}
            </p>
          ) : null}

          <button
            className="button button--ghost button--block"
            type="button"
            onClick={() => {
              setView(view === "password" ? "in" : "password");
              setError(null);
            }}
          >
            <KeyRound size={15} aria-hidden="true" />
            {view === "password" ? "Hide security" : "Security"}
          </button>

          {view === "password" ? (
            <form className="account" onSubmit={(event) => void handleChangePassword(event)}>
              <label className="account__field" htmlFor="current-password">
                <span className="ctl__label">Current password</span>
                <span className="account__input-wrap">
                  <input
                    id="current-password"
                    className="account__input"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={currentPassword}
                    onChange={(event) => setCurrentPassword(event.target.value)}
                  />
                </span>
              </label>

              <label className="account__field" htmlFor="new-password">
                <span className="ctl__label">New password</span>
                <span className="account__input-wrap">
                  <input
                    id="new-password"
                    className="account__input"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={newPassword}
                    onChange={(event) => setNewPassword(event.target.value)}
                  />
                </span>
              </label>

              <label className="account__field" htmlFor="confirm-password">
                <span className="ctl__label">Confirm new password</span>
                <span className="account__input-wrap">
                  <input
                    id="confirm-password"
                    className="account__input"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={confirmPassword}
                    onChange={(event) => setConfirmPassword(event.target.value)}
                  />
                </span>
              </label>

              {error ? (
                <p className="account__error" role="alert">
                  {error}
                </p>
              ) : null}

              <button
                className="button button--primary button--block"
                type="submit"
                disabled={busy}
              >
                {busy ? "Updating…" : "Change password"}
              </button>

              <p className="account__hint">
                Changing your password signs out every other session.
              </p>
            </form>
          ) : null}

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

          {mode === "in" ? (
            <button
              className="account__forgot"
              type="button"
              onClick={() => {
                setView("forgot");
                setError(null);
              }}
            >
              Forgot password?
            </button>
          ) : null}

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
