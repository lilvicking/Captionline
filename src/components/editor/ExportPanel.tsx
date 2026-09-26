import { Download, Film } from "lucide-react";
import { downloadSrt, srtFileName } from "../../lib/srt";
import type { CaptionCue } from "../../types";

type ExportPanelProps = {
  cues: CaptionCue[];
  videoName: string;
};

export function ExportPanel({ cues, videoName }: ExportPanelProps) {
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

      <button className="button button--ghost button--block" type="button" disabled>
        <Film size={16} aria-hidden="true" />
        Export video
      </button>
      <p className="panel__hint">
        Rendered video export is not available yet. This button stays disabled until the rendering
        pipeline is connected in a later phase.
      </p>
    </section>
  );
}
