import { useState } from "react";
import { ArrowLeft, Mail, MailCheck } from "lucide-react";
import { requestPasswordReset } from "../lib/auth";

type ForgotPasswordFormProps = {
  onBack: () => void;
};

/** Generic confirmation. Must match the backend wording so it never implies
 * whether the address is registered. */
const CONFIRMATION =
  "If an account exists for that email, we've sent a password reset link.";

export function ForgotPasswordForm({ onBack }: ForgotPasswordFormProps) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    setBusy(true);

    try {
      await requestPasswordReset(email.trim());
      // Shown for every outcome, including an unknown address.
      setSent(true);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "We could not send the reset email. Please try again shortly.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div className="account">
        <div className="account__confirm">
          <MailCheck size={20} aria-hidden="true" />
          <p>{CONFIRMATION}</p>
        </div>
        <p className="account__hint">
          The link expires in about an hour. Check your spam folder if it does not arrive.
        </p>
        <button className="button button--ghost button--block" type="button" onClick={onBack}>
          Back to log in
        </button>
      </div>
    );
  }

  return (
    <form className="account" onSubmit={(event) => void handleSubmit(event)}>
      <button className="account__back" type="button" onClick={onBack}>
        <ArrowLeft size={14} aria-hidden="true" />
        Back to log in
      </button>

      <div>
        <h3 className="account__heading">Forgot your password?</h3>
        <p className="account__subheading">
          Enter the email associated with your Captionline account and we'll send you a reset link.
        </p>
      </div>

      <label className="account__field" htmlFor="forgot-email">
        <span className="ctl__label">Email</span>
        <span className="account__input-wrap">
          <Mail size={15} aria-hidden="true" />
          <input
            id="forgot-email"
            className="account__input"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </span>
      </label>

      {error ? (
        <p className="account__error" role="alert">
          {error}
        </p>
      ) : null}

      <button className="button button--primary button--block" type="submit" disabled={busy}>
        {busy ? "Sending…" : "Send reset link"}
      </button>
    </form>
  );
}
