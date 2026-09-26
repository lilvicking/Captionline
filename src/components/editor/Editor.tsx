import { useCallback, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import { ArrowLeft, Info } from "lucide-react";
import { DEFAULT_CAPTION_STYLE } from "../../types";
import type { CaptionCue, CaptionStyle } from "../../types";
import { CaptionDesigner } from "./CaptionDesigner";
import { CaptionTrack } from "./CaptionTrack";
import { ExportPanel } from "./ExportPanel";
import { Timeline } from "./Timeline";
import { VideoStage } from "./VideoStage";

type EditorProps = {
  videoUrl: string;
  videoName: string;
  cues: CaptionCue[];
  setCues: Dispatch<SetStateAction<CaptionCue[]>>;
  onReset: () => void;
};

const DEFAULT_CUE_LENGTH_SECONDS = 2;

export function Editor({ videoUrl, videoName, cues, setCues, onReset }: EditorProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [captionStyle, setCaptionStyle] = useState<CaptionStyle>(DEFAULT_CAPTION_STYLE);

  const playingCue = useMemo(
    () => cues.find((cue) => currentTime >= cue.start && currentTime < cue.end) ?? null,
    [cues, currentTime],
  );

  const seek = useCallback((time: number) => {
    const video = videoRef.current;
    if (!video) {
      return;
    }

    const target = Math.max(0, time);
    video.currentTime = target;
    setCurrentTime(target);
  }, []);

  const handleTimeUpdate = useCallback(() => {
    const video = videoRef.current;
    if (video) {
      setCurrentTime(video.currentTime);
    }
  }, []);

  const handleLoadedMetadata = useCallback(() => {
    const video = videoRef.current;
    if (video && Number.isFinite(video.duration)) {
      setDuration(video.duration);
    }
  }, []);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const handleTextChange = useCallback(
    (id: string, text: string) => {
      setCues((previous) =>
        previous.map((cue) => (cue.id === id ? { ...cue, text } : cue)),
      );
    },
    [setCues],
  );

  const handleAdd = useCallback(() => {
    setCues((previous) => {
      const start = Math.max(0, Math.round(currentTime * 100) / 100);
      const cue: CaptionCue = {
        id: `cue-${start}-${previous.length}-${Date.now()}`,
        start,
        end: Math.round((start + DEFAULT_CUE_LENGTH_SECONDS) * 100) / 100,
        text: "New caption",
      };

      return [...previous, cue].sort((a, b) => a.start - b.start);
    });
  }, [currentTime, setCues]);

  const handleRemove = useCallback(
    (id: string) => {
      setCues((previous) => previous.filter((cue) => cue.id !== id));
      setSelectedId((previous) => (previous === id ? null : previous));
    },
    [setCues],
  );

  const handleStyleChange = useCallback((next: CaptionStyle) => {
    setCaptionStyle(next);
  }, []);

  const handleVerticalPositionChange = useCallback((value: number) => {
    setCaptionStyle((previous) => ({ ...previous, verticalPosition: value }));
  }, []);

  const handleStyleReset = useCallback(() => {
    setCaptionStyle(DEFAULT_CAPTION_STYLE);
  }, []);

  return (
    <main className="editor">
      <div className="editor__bar">
        <button className="button button--ghost button--sm" type="button" onClick={onReset}>
          <ArrowLeft size={15} aria-hidden="true" />
          New video
        </button>

        <span className="editor__file" title={videoName}>
          {videoName}
        </span>

        <span className="pill">
          <Info size={13} aria-hidden="true" />
          Sample captions
        </span>
      </div>

      <div className="editor__grid">
        <div className="editor__main">
          <VideoStage
            videoRef={videoRef}
            src={videoUrl}
            activeText={playingCue?.text ?? null}
            style={captionStyle}
            onVerticalPositionChange={handleVerticalPositionChange}
            onTimeUpdate={handleTimeUpdate}
            onLoadedMetadata={handleLoadedMetadata}
          />

          <Timeline
            cues={cues}
            currentTime={currentTime}
            duration={duration}
            selectedId={selectedId}
            onSeek={seek}
            onSelect={handleSelect}
          />
        </div>

        <aside className="editor__side">
          <CaptionDesigner
            fileName={videoName}
            style={captionStyle}
            onChange={handleStyleChange}
            onReset={handleStyleReset}
          />

          <ExportPanel cues={cues} videoName={videoName} />
        </aside>
      </div>

      <CaptionTrack
        cues={cues}
        selectedId={selectedId}
        playingId={playingCue?.id ?? null}
        onSelect={handleSelect}
        onTextChange={handleTextChange}
        onRemove={handleRemove}
        onAdd={handleAdd}
      />
    </main>
  );
}
