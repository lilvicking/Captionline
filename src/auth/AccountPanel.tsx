import { useCallback, useEffect, useRef, useState } from "react";
import {
  CalendarClock,
  CreditCard,
  KeyRound,
  LogOut,
  Mail,
  RefreshCw,
  Trash2,
  TriangleAlert,
  User as UserIcon,
  X,
} from "lucide-react";
import { isUnauthorized, useAuth } from "./AuthContext";
import { ForgotPasswordForm } from "./ForgotPasswordForm";
import { changePassword, deleteAccount, getStoredToken } from "../lib/auth";
import { openBillingPortal } from "../lib/billing";

type AccountPanelProps = {
  onClose: () => void;
};

type PanelView = "in" | "up" | "forgot" | "password" | "delete";

/** The literal word the backend requires to confirm an account deletion. */
const DELETE_CONFIRMATION = "DELETE";

const LOGIN_ERROR_ID = "account-login-error";
const PASSWORD_ERROR_ID = "account-password-error";
const DELETE_ERROR_ID = "account-delete-error";
const DELETE_CURRENT_ID = "account-delete-current";
const DELETE_CONFIRM_ID = "account-delete-confirm";
const CONFIRM_HINT_ID = "account-delete-confirm-hint";

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
  const { status, user, account, isPaidPlan, refresh, signIn, signUp, signOut, expireSession } =
    useAuth();

  const [view, setView] = useState<PanelView>("in");
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  // Change-password state
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  // Billing state
  const [billingBusy, setBillingBusy] = useState(false);
  const [billingError, setBillingError] = useState<string | null>(null);

  // Account deletion state
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const sheetRef = useRef<HTMLDivElement>(null);
  const deleteRef = useRef<HTMLButtonElement>(null);

  const isAuthenticated = status === "authenticated" && user !== null;
  const isForgot = view === "forgot";

  // Both the explanation and the error belong with the confirm field, so the
  // description is assembled rather than replaced when an error appears.
  const confirmDescribedBy =
    [deleteConfirmation ? CONFIRM_HINT_ID : null, deleteError ? DELETE_ERROR_ID : null]
      .filter(Boolean)
      .join(" ") || undefined;

  /**
   * Minimal dialog behavior: move focus in on open, close on Escape, and give
   * focus back to whatever opened the sheet. No focus trap and no dependency:
   * the sheet is a small, short panel and the browser's own tab order handles
   * the rest.
   */
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const sheet = sheetRef.current;

    sheet?.querySelector<HTMLElement>("input, button")?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }

      event.stopPropagation();
      onClose();
    };

    document.addEventListener("keydown", onKeyDown);

    return () => {
      document.removeEventListener("keydown", onKeyDown);
      opener?.focus?.();
    };
  }, [onClose]);

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
    setNotice(null);

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
      expireSession();
      return;
    }

    setBusy(true);

    try {
      await changePassword(currentPassword, newPassword, token);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setNotice("Password changed. Other sessions were signed out.");
      setView("in");
    } catch (caught) {
      if (isUnauthorized(caught)) {
        expireSession();
      }

      setError(caught instanceof Error ? caught.message : "We could not change your password.");
    } finally {
      setBusy(false);
    }
  };

  /** Opens Stripe's customer portal, where the subscription is actually managed. */
  const handleManageBilling = async () => {
    setBillingError(null);
    setBillingBusy(true);

    try {
      const token = getStoredToken();
      if (!token) {
        setBillingError("Your session expired. Please log in again.");
        expireSession();
        return;
      }

      const url = await openBillingPortal(token);

      if (url) {
        window.location.assign(url);
      }
    } catch (caught) {
      if (isUnauthorized(caught)) {
        expireSession();
        setBillingError("Your session expired. Please log in again.");
        return;
      }

      setBillingError(
        caught instanceof Error ? caught.message : "The billing portal is unavailable right now.",
      );
    } finally {
      setBillingBusy(false);
    }
  };

  const closeDeletePanel = useCallback(() => {
    setView("in");
    setDeleteError(null);
    setDeletePassword("");
    setDeleteConfirmation("");
    // Deferred: the trigger button is re-created by the next render, so focus is
    // returned after the commit rather than to a node about to be removed.
    window.setTimeout(() => deleteRef.current?.focus(), 0);
  }, []);

  const handleDeleteAccount = async (event: React.FormEvent) => {
    event.preventDefault();
    setDeleteError(null);

    if (deleteConfirmation !== DELETE_CONFIRMATION) {
      setDeleteError(`Type ${DELETE_CONFIRMATION} in the box to confirm.`);
      return;
    }

    const token = getStoredToken();
    if (!token) {
      setDeleteError("Your session expired. Please log in again.");
      expireSession();
      return;
    }

    setDeleting(true);

    try {
      await deleteAccount(token, deletePassword, deleteConfirmation);
      // The account is gone, so the local session goes with it. No revoke call:
      // there is no session left on the server to revoke.
      setDeletePassword("");
      setDeleteConfirmation("");
      expireSession();
    } catch (caught) {
      if (isUnauthorized(caught)) {
        expireSession();
        setDeleteError("Your session expired. Please log in again.");
        return;
      }

      // 409 means an active subscription still has to be canceled first. The
      // backend sends the wording, so show it rather than a generic failure.
      setDeleteError(
        caught instanceof Error
          ? caught.message
          : "We could not delete your account. Please try again shortly.",
      );
    } finally {
      setDeleting(false);
    }
  };

  const sheetProps = {
    ref: sheetRef,
    className: "sheet",
    role: "dialog" as const,
    "aria-modal": true,
    "aria-label": isForgot ? "Forgot password" : "Account",
  };

  const head = (
    <div className="sheet__head">
      <h2 className="sheet__title">Account</h2>
      <button className="sheet__close" type="button" onClick={onClose} aria-label="Close account">
        <X size={16} aria-hidden="true" />
      </button>
    </div>
  );

  if (view === "forgot") {
    return (
      <div {...sheetProps}>
        {head}
        <ForgotPasswordForm onBack={() => setView("in")} />
      </div>
    );
  }

  return (
    <div {...sheetProps}>
      {head}

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
                {account.can_export ? " · export entitlement included" : ""}
              </p>
            </div>
          ) : (
            <p className="sheet__body">Usage details are unavailable right now.</p>
          )}

          {notice ? (
            <p className="account__confirm" role="status">
              {notice}
            </p>
          ) : null}

          {isPaidPlan ? (
            <button
              className="button button--ghost button--block"
              type="button"
              onClick={() => void handleManageBilling()}
              disabled={billingBusy}
            >
              <CreditCard size={15} aria-hidden="true" />
              {billingBusy ? "Opening billing…" : "Manage billing"}
            </button>
          ) : null}

          {billingError ? (
            <p className="account__error" role="alert">
              {billingError}
            </p>
          ) : null}

          {isPaidPlan && account?.subscription_status ? (
            <p className="account__hint">
              Subscription status: {account.subscription_status}. Cancel or update it in the billing
              portal.
            </p>
          ) : null}

          <button
            className="button button--ghost button--block"
            type="button"
            onClick={() => {
              setView(view === "password" ? "in" : "password");
              setError(null);
            }}
            aria-expanded={view === "password"}
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
                    aria-invalid={error !== null}
                    aria-describedby={error ? PASSWORD_ERROR_ID : undefined}
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
                    aria-invalid={error !== null}
                    aria-describedby={error ? PASSWORD_ERROR_ID : undefined}
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
                    aria-invalid={error !== null}
                    aria-describedby={error ? PASSWORD_ERROR_ID : undefined}
                  />
                </span>
              </label>

              {error ? (
                <p className="account__error" id={PASSWORD_ERROR_ID} role="alert">
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

          {view === "delete" ? (
            <form className="account" onSubmit={(event) => void handleDeleteAccount(event)}>
              <p className="account__danger">
                <TriangleAlert size={16} aria-hidden="true" />
                <span>
                  This permanently deletes your account, your usage history, and your plan data. It
                  cannot be undone. Your uploaded media is already gone: it is deleted from the
                  server as soon as it has been transcribed.
                </span>
              </p>

              {isPaidPlan ? (
                <p className="account__notice">
                  You are on a paid plan. Cancel the subscription in the billing portal first:
                  deletion is refused while a subscription is still active, and canceling is what
                  stops future charges.
                </p>
              ) : null}

              <label className="account__field" htmlFor={DELETE_CURRENT_ID}>
                <span className="ctl__label">Current password</span>
                <span className="account__input-wrap">
                  <input
                    id={DELETE_CURRENT_ID}
                    className="account__input"
                    type="password"
                    autoComplete="current-password"
                    required
                    value={deletePassword}
                    onChange={(event) => setDeletePassword(event.target.value)}
                    aria-invalid={deleteError !== null}
                    aria-describedby={deleteError ? DELETE_ERROR_ID : undefined}
                  />
                </span>
              </label>

              <label className="account__field" htmlFor={DELETE_CONFIRM_ID}>
                <span className="ctl__label">
                  Type {DELETE_CONFIRMATION} to confirm
                </span>
                <span className="account__input-wrap">
                  <input
                    id={DELETE_CONFIRM_ID}
                    className="account__input"
                    type="text"
                    autoComplete="off"
                    spellCheck={false}
                    required
                    value={deleteConfirmation}
                    onChange={(event) => setDeleteConfirmation(event.target.value)}
                    aria-invalid={deleteError !== null}
                    aria-describedby={confirmDescribedBy}
                  />
                </span>
              </label>

              <p className="account__hint" id={CONFIRM_HINT_ID}>
                Both the password and the exact word are required, so an unattended browser cannot
                destroy an account by accident.
              </p>

              {deleteError ? (
                <p className="account__error" id={DELETE_ERROR_ID} role="alert">
                  {deleteError}
                </p>
              ) : null}

              <button
                className="button button--danger button--block"
                type="submit"
                disabled={deleting}
              >
                <Trash2 size={15} aria-hidden="true" />
                {deleting ? "Deleting…" : "Delete my account permanently"}
              </button>

              <button
                className="button button--ghost button--block"
                type="button"
                onClick={closeDeletePanel}
                disabled={deleting}
              >
                Keep my account
              </button>
            </form>
          ) : (
            <button
              className="account__danger-link"
              type="button"
              ref={deleteRef}
              onClick={() => {
                setView("delete");
                setError(null);
                setDeleteError(null);
              }}
            >
              <Trash2 size={14} aria-hidden="true" />
              Delete my account
            </button>
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
          <div className="segmented segmented--full" role="group" aria-label="Log in or sign up">
            <button
              type="button"
              className={`segmented__option${mode === "in" ? " is-active" : ""}`}
              aria-pressed={mode === "in"}
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
              aria-pressed={mode === "up"}
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
                aria-invalid={error !== null}
                aria-describedby={error ? LOGIN_ERROR_ID : undefined}
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
                aria-invalid={error !== null}
                aria-describedby={error ? LOGIN_ERROR_ID : undefined}
              />
            </span>
          </label>

          {error ? (
            <p className="account__error" id={LOGIN_ERROR_ID} role="alert">
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
              : "Free accounts get 10 processing minutes a month, with every feature included."}
          </p>
        </form>
      )}
    </div>
  );
}
