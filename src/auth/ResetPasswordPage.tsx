import { useState } from "react";
import { AlertTriangle, CheckCircle2, Lock } from "lucide-react";
import { resetPassword } from "../lib/auth";
import { navigateTo, readQueryParam, replaceUrlSilently, RESET_PASSWORD_PATH } from "./route";

const MIN_PASSWORD_LENGTH = 8;

/** Shared id so both fields can point `aria-describedby` at the one message. */
const ERROR_ID = "reset-password-error";

type State = "form" | "done";

export function ResetPasswordPage() {
  // Read from the URL on mount. The token is never stored in localStorage or
  // sessionStorage, and is not written anywhere else.
  const [token] = useState(() => readQueryParam("token"));
  const [state, setState] = useState<State>("form");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const missingToken = token.trim() === "";

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);

    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters long.`);
      return;
    }

    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }

    setBusy(true);

    try {
      await resetPassword(token, password);
      setPassword("");
      setConfirm("");
      // The confirmation renders first. Navigating here would unmount the page
      // before the user ever saw it.
      setState("done");
      // The token is spent, so drop it from the address bar with replaceState:
      // the page stays mounted, no history entry is added, and the raw token
      // stops sitting in the URL (or in a referrer the user might share).
      replaceUrlSilently(RESET_PASSWORD_PATH);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "This password reset link is invalid or has expired.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (state === "done") {
    return (
      <main className="authpage">
        <div className="authpage__card" role="status" aria-live="polite">
          <span className="authpage__icon authpage__icon--ok" aria-hidden="true">
            <CheckCircle2 size={24} />
          </span>
          <h1 className="authpage__title">Your password has been reset.</h1>
          <p className="authpage__body">
            For your security, any other sessions have been signed out. Use your new password to log
            in.
          </p>
          <button
            className="button button--primary button--block"
            type="button"
            onClick={() => navigateTo("/")}
          >
            Log in
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="authpage">
      <div className="authpage__card">
        <span className="authpage__icon" aria-hidden="true">
          <Lock size={22} />
        </span>

        <h1 className="authpage__title">Choose a new password</h1>
        <p className="authpage__body">
          Pick something you have not used before. You will be signed out everywhere else.
        </p>

        {missingToken ? (
          <p className="authpage__notice" role="alert">
            <AlertTriangle size={16} aria-hidden="true" />
            <span>
              This reset link is missing its token. Request a new link from the Forgot password
              screen.
            </span>
          </p>
        ) : (
          <form className="authpage__form" onSubmit={(event) => void handleSubmit(event)}>
            <label className="account__field" htmlFor="reset-password">
              <span className="ctl__label">New password</span>
              <span className="account__input-wrap">
                <input
                  id="reset-password"
                  className="account__input"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={MIN_PASSWORD_LENGTH}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  aria-invalid={error !== null}
                  aria-describedby={error ? ERROR_ID : undefined}
                />
              </span>
            </label>

            <label className="account__field" htmlFor="reset-password-confirm">
              <span className="ctl__label">Confirm new password</span>
              <span className="account__input-wrap">
                <input
                  id="reset-password-confirm"
                  className="account__input"
                  type="password"
                  autoComplete="new-password"
                  required
                  minLength={MIN_PASSWORD_LENGTH}
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  aria-invalid={error !== null}
                  aria-describedby={error ? ERROR_ID : undefined}
                />
              </span>
            </label>

            {error ? (
              <p className="account__error" id={ERROR_ID} role="alert">
                {error}
              </p>
            ) : null}

            <button
              className="button button--primary button--block"
              type="submit"
              disabled={busy}
            >
              {busy ? "Updating…" : "Reset password"}
            </button>
          </form>
        )}

        <button
          className="button button--ghost button--block"
          type="button"
          onClick={() => navigateTo("/")}
        >
          Back to Captionline
        </button>
      </div>
    </main>
  );
}
