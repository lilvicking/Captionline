import { useEffect, useState } from "react";
import { Info, Loader2 } from "lucide-react";

type ProcessingStateProps = {
  fileName: string;
  onComplete: () => void;
};

const STEPS = [
  "Reading video details",
  "Preparing the caption track",
  "Opening your workspace",
];

const STEP_INTERVAL_MS = 650;
const FINISH_DELAY_MS = 450;

export function ProcessingState({ fileName, onComplete }: ProcessingStateProps) {
  const [completedSteps, setCompletedSteps] = useState(0);

  useEffect(() => {
    const timers = STEPS.map((_, index) =>
      window.setTimeout(() => {
        setCompletedSteps(index + 1);
      }, STEP_INTERVAL_MS * (index + 1)),
    );

    const finishTimer = window.setTimeout(
      onComplete,
      STEP_INTERVAL_MS * STEPS.length + FINISH_DELAY_MS,
    );

    return () => {
      timers.forEach((timer) => window.clearTimeout(timer));
      window.clearTimeout(finishTimer);
    };
  }, [onComplete]);

  return (
    <section className="processing">
      <div className="processing__card">
        <Loader2 className="processing__spinner" size={26} aria-hidden="true" />

        <h2 className="processing__title">Preparing your workspace</h2>
        <p className="processing__file">{fileName}</p>

        <ol className="processing__steps">
          {STEPS.map((step, index) => (
            <li
              key={step}
              className={`processing__step${index < completedSteps ? " is-done" : ""}`}
            >
              <span className="processing__marker" aria-hidden="true" />
              {step}
            </li>
          ))}
        </ol>

        <p className="processing__note">
          <Info size={16} aria-hidden="true" />
          <span>
            <strong>Phase 1 uses sample caption data.</strong> No transcription engine is connected
            yet, so the caption track is placeholder text you can edit freely. Your video is read
            locally and is never uploaded.
          </span>
        </p>
      </div>
    </section>
  );
}
