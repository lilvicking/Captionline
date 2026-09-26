import { useState } from "react";
import { Download, Film, Sparkles } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { downloadSrt, srtFileName } from "../../lib/srt";
import type { CaptionCue } from "../../types";

type ExportPanelProps = {
  cues: CaptionCue[];
  videoName: string;
};

export function ExportPanel({ cues, videoName }: ExportPanelProps) {
  const { account } = useAuth();
  const [showUpgradeNote, setShowUpgradeNote] = useState(false);

  // Entitlement comes from the server. When it is unknown the account is null,
  // which is treated as not entitled.
  const canExport = account?.can_export === true;
  const fileName = `${srtFileName(videoName)}.srt`;

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
            Your plan includes finished-video export. Rendering is not switched on yet, so this
            button stays disabled until the rendering pipeline is connected. Nothing is rendered in
            the meantime.
          </p>
        </>
      ) : (
        <>
          <button
            className="button button--ghost button--block"
            type="button"
            onClick={() => setShowUpgradeNote(true)}
          >
            <Sparkles size={16} aria-hidden="true" />
            Upgrade for video export
          </button>
          <p className="panel__hint">
            Finished-video export is included with Creator and Pro. Subtitle (.srt) export above
            works on every plan.
          </p>
        </>
      )}

      {showUpgradeNote ? (
        <p className="panel__note" role="status">
          <Film size={15} aria-hidden="true" />
          <span>
            Paid plans include finished-video export. Plans and checkout are being finalised, so
            nothing has been charged and no payment was started.
          </span>
        </p>
      ) : null}
    </section>
  );
}
