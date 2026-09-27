import { useState } from "react";
import { Download, Film, Sparkles } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { downloadSrt, srtFileName } from "../../lib/srt";
import type { CaptionCue } from "../../types";

type ExportPanelProps = {
  cues: CaptionCue[];
  videoName: string;
  /** Opens the pricing plans, which live outside the editor stage. */
  onShowPlans: () => void;
};

export function ExportPanel({ cues, videoName, onShowPlans }: ExportPanelProps) {
  const { account } = useAuth();
  const [showUpgradeNote, setShowUpgradeNote] = useState(false);

  // Entitlement comes from the server. When it is unknown the account is null,
  // which is treated as not entitled.
  const canExport = account?.can_export === true;
  const fileName = `${srtFileName(videoName)}.srt`;

  /**
   * Sends the reader to the pricing section on the landing page.
   *
   * The plans are not rendered inside the editor, and this panel has no way to
   * start checkout itself, so the honest thing is to say where the plans are
   * rather than to imply something happened here.
   */
  const findPlans = () => {
    setShowUpgradeNote(true);
    onShowPlans();
  };

  return (
    <section className="panel">
      <h2 className="panel__title">Export</h2>

      <button
        className="button button--primary button--block"
        type="button"
        onClick={() => downloadSrt(cues, videoName)}
        disabled={cues.length === 0}
      >
        <Download size={16} aria-hidden="true" />
        Export .SRT
      </button>
      <p className="panel__hint">Downloads {fileName} from the captions in this editor.</p>

      {canExport ? (
        <>
          <button className="button button--ghost button--block" type="button" disabled>
            <Film size={16} aria-hidden="true" />
            Export video
          </button>
          <p className="panel__hint">
            Your plan includes the finished-video export entitlement. Rendering is not switched on
            yet, so this button stays disabled until the rendering pipeline is connected. Until
            then, the .srt export above is the finished deliverable.
          </p>
        </>
      ) : (
        <>
          <button
            className="button button--ghost button--block"
            type="button"
            onClick={findPlans}
          >
            <Sparkles size={16} aria-hidden="true" />
            Upgrade for video export
          </button>
          <p className="panel__hint">
            Paid plans include the finished-video export entitlement. Subtitle (.srt) export above
            works on every plan.
          </p>
        </>
      )}

      {showUpgradeNote ? (
        <p className="panel__note" role="status">
          <Film size={15} aria-hidden="true" />
          <span>
            Plans are on the Captionline home page, where subscribing opens Stripe checkout. Nothing
            has been charged and no payment was started from this editor. Rendered video output is
            not available yet, so paid plans currently include the export entitlement rather than a
            working renderer.
          </span>
        </p>
      ) : null}
    </section>
  );
}
