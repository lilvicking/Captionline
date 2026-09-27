import { useEffect } from "react";
import { AlertTriangle, Info, Loader2, Lock } from "lucide-react";
import type { TranscriptionFailureReason } from "../lib/api";

export type TranscriptionJob = {
  phase: "uploading" | "transcribing" | "ready" | "error";
  message: string;
  detail?: string;
  /** Drives which remedy the error screen offers. */
  reason?: TranscriptionFailureReason;
};

type ProcessingStateProps = {
  fileName: string;
  job: TranscriptionJob | null;
  onContinue: () => void;
  onSignIn: () => void;
  onViewPlans: () => void;
};

const STEPS = [
  "Preparing your workspace",
  "Sending the file to the transcription service",
  "Transcribing with WhisperX and aligning words",
];

const ERROR_STEP_COUNT = 1;

/** How long the error stays on screen before the sample captions are shown. */
const ERROR_DISMISS_MS = 5000;

/** Reasons that need the user to act rather than just retry. */
const NEEDS_SIGN_IN = new Set<TranscriptionFailureReason>(["auth-required"]);
const NEEDS_PLAN = new Set<TranscriptionFailureReason>(["insufficient-minutes"]);

/** Safe fallback copy. Never surfaces a raw server or library message. */
function fallbackMessage(reason: TranscriptionFailureReason | undefined): string {
  switch (reason) {
    case "auth-required":
      return "Create a free account or log in to transcribe video.";
    case "insufficient-minutes":
      return "You have used all of the processing included in your current plan.";
    case "file-too-large":
      return "That file is too large to upload.";
    case "invalid-media":
      return "That file could not be read as video or audio.";
    case "unavailable":
      return "Transcription is temporarily unavailable. Please try again shortly.";
    default:
      return "Transcription could not be completed for this file.";
  }
}

function completedSteps(phase: TranscriptionJob["phase"] | undefined): number {
  switch (phase) {
    case "uploading":
      return 1;
    case "transcribing":
    case "ready":
      return STEPS.length;
    case "error":
      return ERROR_STEP_COUNT;
    default:
      return 0;
  }
}

export function ProcessingState({
  fileName,
  job,
  onContinue,
  onSignIn,
  onViewPlans,
}: ProcessingStateProps) {
  const isError = job?.phase === "error";
  const reason = job?.reason;
  const done = completedSteps(job?.phase);

  // Never strand the user on an error screen: fall through to the editor, which
  // will be showing sample captions.
  useEffect(() => {
    if (!isError) {
      return;
    }

    const timer = window.setTimeout(onContinue, ERROR_DISMISS_MS);
    return () => window.clearTimeout(timer);
  }, [isError, onContinue]);

  const needsSignIn = reason !== undefined && NEEDS_SIGN_IN.has(reason);
  const needsPlan = reason !== undefined && NEEDS_PLAN.has(reason);

  // The server's message is shown when present because it explains the specific
  // problem (for example the exact remaining seconds), and the backend only
  // returns curated text.
  const headline = isError
    ? needsSignIn
      ? "Sign in to transcribe"
      : needsPlan
        ? "No processing time left"
        : "Transcription unavailable"
    : "Preparing your workspace";

  return (
    <section className="processing">
      <div className={`processing__card${isError ? " processing__card--error" : ""}`}>
        {isError ? (
          needsSignIn ? (
            <Lock className="processing__icon processing__icon--accent" size={26} aria-hidden="true" />
          ) : (
            <AlertTriangle
              className="processing__spinner processing__spinner--error"
              size={26}
              aria-hidden="true"
            />
          )
        ) : (
          <Loader2 className="processing__spinner" size={26} aria-hidden="true" />
        )}

        <h2 className="processing__title">{headline}</h2>
        <p className="processing__file">{fileName}</p>
        {/*
          The screen advances on its own after a failure, so the message is a
          live region: a screen reader that is not watching the visual change
          still hears why the transcription stopped.
        */}
        <p
          className="processing__message"
          role={isError ? "alert" : undefined}
          aria-live={isError ? "assertive" : "polite"}
        >
          {isError ? job?.message || fallbackMessage(reason) : job?.message ?? "Starting"}
        </p>

        <ol className="processing__steps">
          {STEPS.map((step, index) => (
            <li
              key={step}
              className={`processing__step${index < done ? " is-done" : ""}`}
            >
              <span className="processing__marker" aria-hidden="true" />
              {step}
            </li>
          ))}
        </ol>

        {isError ? (
          <>
            <p className="processing__note processing__note--error" role="status" aria-live="polite">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>
                {job?.detail || fallbackMessage(reason)}
                {needsSignIn
                  ? " You can still look around and edit sample captions."
                  : needsPlan
                    ? " Upgrade your plan for more processing time."
                    : " Sample captions will be loaded so you can keep working in the editor."}
              </span>
            </p>

            <div className="processing__actions">
              {needsSignIn ? (
                <button className="button button--primary" type="button" onClick={onSignIn}>
                  Create a free account
                </button>
              ) : null}

              {needsPlan ? (
                <button className="button button--primary" type="button" onClick={onViewPlans}>
                  View plans
                </button>
              ) : null}

              <button className="button button--ghost" type="button" onClick={onContinue}>
                Continue with sample captions
              </button>
            </div>
          </>
        ) : (
          <p className="processing__note">
            <Info size={16} aria-hidden="true" />
            <span>
              Transcription runs on the Captionline service using WhisperX. The uploaded file is
              deleted as soon as it has been transcribed.
            </span>
          </p>
        )}
      </div>
    </section>
  );
}
