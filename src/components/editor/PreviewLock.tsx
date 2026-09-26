import { useState } from "react";
import { Lock, RotateCcw } from "lucide-react";

type PreviewLockProps = {
  /** Restarts the allowed preview window. */
  onReplayPreview: () => void;
};

/**
 * Covers the finished-video preview once the free-tier boundary is reached.
 *
 * This is a product/UX gate, not a security control. See `src/entitlement.ts`.
 */
export function PreviewLock({ onReplayPreview }: PreviewLockProps) {
  const [showPlansNote, setShowPlansNote] = useState(false);

  return (
    <div className="lock" role="dialog" aria-label="Full preview locked">
      <span className="lock__icon" aria-hidden="true">
        <Lock size={24} />
      </span>

      <h2 className="lock__title">Full preview locked</h2>

      <p className="lock__body">
        You can keep editing your entire project. Subscribe to preview and export the complete video.
      </p>

      <div className="lock__actions">
        <button
          className="button button--primary button--sm"
          type="button"
          onClick={() => setShowPlansNote(true)}
        >
          Upgrade
        </button>

        <button className="button button--ghost button--sm" type="button" onClick={onReplayPreview}>
          <RotateCcw size={14} aria-hidden="true" />
          Replay preview
        </button>
      </div>

      {showPlansNote ? (
        <p className="lock__note" role="status">
          Plans coming next. Subscriptions are not available yet, so nothing has been charged and no
          checkout was started.
        </p>
      ) : null}
    </div>
  );
}
