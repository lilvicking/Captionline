import { useEffect } from "react";
import { AlertTriangle, Info, Loader2 } from "lucide-react";

export type TranscriptionJob = {
  phase: "uploading" | "transcribing" | "ready" | "error";
  message: string;
  detail?: string;
};

type ProcessingStateProps = {
  fileName: string;
  job: TranscriptionJob | null;
  onContinue: () => void;
};

const STEPS = [
  "Preparing your workspace",
  "Sending the file to the transcription service",
  "Transcribing with WhisperX and aligning words",
];

const ERROR_STEP_COUNT = 1;

/** How long the error stays on screen before the sample captions are shown. */
const ERROR_DISMISS_MS = 4000;

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

export function ProcessingState({ fileName, job, onContinue }: ProcessingStateProps) {
  const isError = job?.phase === "error";
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

  return (
    <section className="processing">
      <div className={`processing__card${isError ? " processing__card--error" : ""}`}>
        {isError ? (
          <AlertTriangle className="processing__spinner processing__spinner--error" size={26} aria-hidden="true" />
        ) : (
          <Loader2 className="processing__spinner" size={26} aria-hidden="true" />
        )}

        <h2 className="processing__title">
          {isError ? "Transcription unavailable" : "Preparing your workspace"}
        </h2>
        <p className="processing__file">{fileName}</p>
        <p className="processing__message">{job?.message ?? "Starting"}</p>

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
            <p className="processing__note processing__note--error">
              <AlertTriangle size={16} aria-hidden="true" />
              <span>
                {job?.detail ?? "The transcription service could not be reached."} Sample captions
                will be loaded so you can keep working in the editor.
              </span>
            </p>
            <button className="button button--primary button--block" type="button" onClick={onContinue}>
              Continue with sample captions
            </button>
          </>
        ) : (
          <p className="processing__note">
            <Info size={16} aria-hidden="true" />
            <span>
              Transcription runs on the Captionline service using WhisperX. The video itself is not
              stored anywhere.
            </span>
          </p>
        )}
      </div>
    </section>
  );
}
