import { useState } from "react";
import { Lock, RotateCcw } from "lucide-react";

type PreviewLockProps = {
  /** Restarts the allowed preview window. */
  onReplayPreview: () => void;
  /**
   * Leaves the editor and opens the pricing plans.
   *
   * The editor is a full-screen stage with no pricing section, so this is
   * handled by the app, which owns the stage machine.
   */
  onShowPlans: () => void;
};

/**
 * Covers the finished-video preview once the free-tier boundary is reached.
 *
 * This is a product/UX gate, not a security control. See `src/entitlement.ts`.
 */
export function PreviewLock({ onReplayPreview, onShowPlans }: PreviewLockProps) {
  const [showPlansNote, setShowPlansNote] = useState(false);

  const showPlans = () => {
    setShowPlansNote(true);
    onShowPlans();
  };

  return (
    <div className="lock" role="dialog" aria-label="Full preview locked">
      <span className="lock__icon" aria-hidden="true">
        <Lock size={24} />
      </span>

      <h2 className="lock__title">Full preview locked</h2>

      <p className="lock__body">
        You can keep editing your entire project. Subscribe to watch the whole captioned video
        instead of the first 30 seconds. Subtitle (.srt) export works on every plan, including
        free.
      </p>

      <div className="lock__actions">
        <button className="button button--primary button--sm" type="button" onClick={showPlans}>
          See plans
        </button>

        <button className="button button--ghost button--sm" type="button" onClick={onReplayPreview}>
          <RotateCcw size={14} aria-hidden="true" />
          Replay preview
        </button>
      </div>

      {showPlansNote ? (
        <p className="lock__note" role="status">
          The plans are on the Captionline home page, where subscribing opens Stripe checkout.
          Nothing has been charged and no payment was started from this editor. Leaving the editor
          clears the project from this tab, so export your .srt first if you want to keep it. Paid
          plans include a finished-video export entitlement, but rendered video output is not
          available yet.
        </p>
      ) : null}
    </div>
  );
}
