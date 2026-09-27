import { Download, Film, Sparkles } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { downloadSrt, srtFileName } from "../../lib/srt";
import type { CaptionCue } from "../../types";

/**
 * Whether the finished-captioned-video renderer actually exists.
 *
 * This is an implementation fact about *this build*, deliberately separate from
 * commercial entitlement. Every plan is entitled to finished-video export; the
 * renderer is simply not written yet. Keeping the two apart means turning
 * rendering on later is a one-line change here, with no commercial rework and no
 * risk of a plan being blocked for the wrong reason in the meantime.
 */
const RENDERER_AVAILABLE = false;

type ExportPanelProps = {
  cues: CaptionCue[];
  videoName: string;
  /** Opens the pricing plans, which live outside the editor stage. */
  onShowPlans: () => void;
};

export function ExportPanel({ cues, videoName, onShowPlans }: ExportPanelProps) {
  const { account } = useAuth();

  const fileName = `${srtFileName(videoName)}.srt`;

  // Entitlement is a commercial answer the server gives. Every plan currently
  // includes finished-video export, so this is a guard rather than a gate: if a
  // future plan ever excludes export, this is where it will be honoured.
  const isEntitled = account?.can_export !== false;

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

      {!isEntitled ? (
        <>
          <button
            className="button button--ghost button--block"
            type="button"
            onClick={onShowPlans}
          >
            <Sparkles size={16} aria-hidden="true" />
            See plans with video export
          </button>
          <p className="panel__hint">
            Finished-video export is not included with this plan. Subtitle (.srt) export above works
            on every plan.
          </p>
        </>
      ) : RENDERER_AVAILABLE ? (
        <button
          className="button button--ghost button--block"
          type="button"
          onClick={onShowPlans}
        >
          <Film size={16} aria-hidden="true" />
          Export video
        </button>
      ) : (
        <>
          <button className="button button--ghost button--block" type="button" disabled>
            <Film size={16} aria-hidden="true" />
            Export video
          </button>
          <p className="panel__hint">
            Finished-video export is included with your plan. The renderer that produces the video
            file is still on its way, so this button stays switched off until it arrives. Your .srt
            export above is ready now.
          </p>
        </>
      )}
    </section>
  );
}
