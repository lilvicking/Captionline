import { Plus, Trash2 } from "lucide-react";
import { formatClock } from "../../lib/time";
import type { CaptionCue } from "../../types";

type CaptionTrackProps = {
  cues: CaptionCue[];
  selectedId: string | null;
  playingId: string | null;
  onSelect: (id: string) => void;
  onTextChange: (id: string, text: string) => void;
  onRemove: (id: string) => void;
  onAdd: () => void;
};

export function CaptionTrack({
  cues,
  selectedId,
  playingId,
  onSelect,
  onTextChange,
  onRemove,
  onAdd,
}: CaptionTrackProps) {
  return (
    <section className="panel">
      <div className="panel__header">
        <h2 className="panel__title">Captions</h2>
        <button className="button button--ghost button--sm" type="button" onClick={onAdd}>
          <Plus size={15} aria-hidden="true" />
          Add caption
        </button>
      </div>

      {cues.length === 0 ? (
        <p className="track__empty">
          No captions yet. Add one to start building your subtitle track.
        </p>
      ) : (
        <ul className="track">
          {cues.map((cue) => {
            const isSelected = cue.id === selectedId;
            const isPlaying = cue.id === playingId;

            return (
              <li
                key={cue.id}
                className={`track__item${isSelected ? " is-selected" : ""}${
                  isPlaying ? " is-playing" : ""
                }`}
              >
                <button
                  type="button"
                  className="track__time"
                  onClick={() => onSelect(cue.id)}
                  aria-label={`Select caption at ${formatClock(cue.start)}`}
                >
                  {formatClock(cue.start)}
                  <span className="track__arrow" aria-hidden="true">
                    &rarr;
                  </span>
                  {formatClock(cue.end)}
                </button>

                <textarea
                  className="track__text"
                  value={cue.text}
                  rows={2}
                  spellCheck={false}
                  onFocus={() => onSelect(cue.id)}
                  onChange={(event) => onTextChange(cue.id, event.target.value)}
                />

                <button
                  type="button"
                  className="track__delete"
                  onClick={() => onRemove(cue.id)}
                  aria-label={`Delete caption at ${formatClock(cue.start)}`}
                >
                  <Trash2 size={15} aria-hidden="true" />
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
