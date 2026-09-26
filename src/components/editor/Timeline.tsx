import { formatClock, toPercent } from "../../lib/time";
import type { CaptionCue } from "../../types";

type TimelineProps = {
  cues: CaptionCue[];
  currentTime: number;
  duration: number;
  selectedId: string | null;
  /** null or hasFullPreview means the whole timeline is watchable. */
  previewLimitSeconds: number | null;
  hasFullPreview: boolean;
  onSeek: (time: number) => void;
  onSelect: (id: string) => void;
};

export function Timeline({
  cues,
  currentTime,
  duration,
  selectedId,
  previewLimitSeconds,
  hasFullPreview,
  onSeek,
  onSelect,
}: TimelineProps) {
  const lastCueEnd = cues.reduce((max, cue) => Math.max(max, cue.end), 0);
  const span = duration > 0 ? duration : Math.max(lastCueEnd, 1);

  // The timeline still represents the whole video; the shaded region only marks
  // where the finished video stops being watchable on the free tier.
  const limitPercent =
    hasFullPreview || previewLimitSeconds === null
      ? null
      : toPercent(previewLimitSeconds, span);

  return (
    <div className="timeline">
      <div className="timeline__meta">
        <span className="timeline__time">{formatClock(currentTime)}</span>
        <span className="timeline__time timeline__time--muted">{formatClock(duration)}</span>
      </div>

      <div className="timeline__track">
        {cues.map((cue) => {
          const left = toPercent(cue.start, span);
          const width = Math.max(toPercent(cue.end, span) - left, 0.6);

          return (
            <button
              key={cue.id}
              type="button"
              className={`timeline__cue${cue.id === selectedId ? " is-selected" : ""}`}
              style={{ left: `${left}%`, width: `${width}%` }}
              onClick={() => {
                onSelect(cue.id);
                onSeek(cue.start);
              }}
              title={cue.text}
            />
          );
        })}

        <span
          className="timeline__playhead"
          style={{ left: `${toPercent(currentTime, span)}%` }}
          aria-hidden="true"
        />

        {limitPercent !== null && limitPercent < 100 ? (
          <>
            <span
              className="timeline__protected"
              style={{ left: `${limitPercent}%` }}
              aria-hidden="true"
            />
            <span
              className="timeline__boundary"
              style={{ left: `${limitPercent}%` }}
              aria-hidden="true"
            />
          </>
        ) : null}
      </div>

      <input
        className="timeline__scrub"
        type="range"
        min={0}
        max={span}
        step={0.05}
        value={Math.min(currentTime, span)}
        onChange={(event) => onSeek(Number(event.target.value))}
        aria-label="Seek through the video"
      />
    </div>
  );
}
