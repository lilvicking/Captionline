import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent, RefObject } from "react";
import { clamp } from "../../lib/time";
import { withAlpha } from "../../lib/color";
import { applyUppercase, wrapCaption, wrapWords } from "../../lib/text";
import { CAPTION_FONT_MAP } from "../../data/captionFonts";
import { CAPTION_STYLE_REFERENCE_HEIGHT } from "../../types";
import type { CaptionCue, CaptionStyle, CaptionWord } from "../../types";
import { canPreviewAt, hasReachedPreviewLimit } from "../../entitlement";
import type { PreviewEntitlement } from "../../entitlement";
import { PreviewLock } from "./PreviewLock";

/** Used before the stage has been measured, so the first paint is already sane. */
const FALLBACK_SCALE = 1 / 3;

const KEYBOARD_STEP = 1;
const KEYBOARD_STEP_LARGE = 5;

type VideoStageProps = {
  videoRef: RefObject<HTMLVideoElement>;
  src: string;
  activeCue: CaptionCue | null;
  currentTime: number;
  style: CaptionStyle;
  entitlement: PreviewEntitlement;
  isPreviewLocked: boolean;
  onPreviewLock: () => void;
  onPreviewUnlock: () => void;
  onVerticalPositionChange: (value: number) => void;
  onTimeUpdate: () => void;
  onLoadedMetadata: () => void;
};

/** Finds the word being spoken at `time`, if the cue carries word timings. */
function activeWordAt(words: CaptionWord[] | undefined, time: number): CaptionWord | null {
  if (!words || words.length === 0) {
    return null;
  }

  for (const word of words) {
    if (time >= word.start && time < word.end) {
      return word;
    }
  }

  return null;
}

export function VideoStage({
  videoRef,
  src,
  activeCue,
  currentTime,
  style,
  entitlement,
  isPreviewLocked,
  onPreviewLock,
  onPreviewUnlock,
  onVerticalPositionChange,
  onTimeUpdate,
  onLoadedMetadata,
}: VideoStageProps) {
  const stageRef = useRef<HTMLDivElement>(null);
  const [stageHeight, setStageHeight] = useState(0);
  const [isDragging, setIsDragging] = useState(false);

  useEffect(() => {
    const element = stageRef.current;

    if (!element) {
      return;
    }

    const measure = () => setStageHeight(element.clientHeight);
    measure();

    const observer = new ResizeObserver(measure);
    observer.observe(element);

    return () => observer.disconnect();
  }, []);

  /**
   * Free-tier preview enforcement.
   *
   * Playback is stopped at the boundary, and any seek past it is pulled back to
   * the boundary so the protected frames are never displayed. This covers the
   * native browser controls as well as Captionline's own timeline, because both
   * drive the same `seeking` event on the media element.
   *
   * UX-level protection only; see `src/entitlement.ts` for why this is not a
   * security boundary.
   */
  useEffect(() => {
    const video = videoRef.current;

    if (!video) {
      return;
    }

    const stopAtBoundary = () => {
      if (!hasReachedPreviewLimit(video.currentTime, entitlement)) {
        return;
      }

      if (!video.paused) {
        video.pause();
      }
      onPreviewLock();
    };

    const guardSeek = () => {
      if (canPreviewAt(video.currentTime, entitlement)) {
        // Moved back inside the allowed window.
        onPreviewUnlock();
        return;
      }

      // Pull the playhead back to the boundary. This re-enters `seeking` once
      // with currentTime === limit, where canPreviewAt is true, so it settles.
      video.currentTime = entitlement.previewLimitSeconds ?? video.currentTime;
      video.pause();
      onPreviewLock();
    };

    video.addEventListener("timeupdate", stopAtBoundary);
    video.addEventListener("play", stopAtBoundary);
    video.addEventListener("seeking", guardSeek);

    return () => {
      video.removeEventListener("timeupdate", stopAtBoundary);
      video.removeEventListener("play", stopAtBoundary);
      video.removeEventListener("seeking", guardSeek);
    };
  }, [videoRef, entitlement, onPreviewLock, onPreviewUnlock]);

  /** Restarts the allowed preview window and lifts the lock. */
  const replayPreview = useCallback(() => {
    const video = videoRef.current;

    if (video) {
      video.pause();
      video.currentTime = 0;
    }
    onPreviewUnlock();
    onTimeUpdate();
  }, [videoRef, onPreviewUnlock, onTimeUpdate]);

  /**
   * Scale factor from the 1080px reference frame to the rendered stage, so
   * preview sizes match what a renderer would produce for the same style.
   */
  const scale = stageHeight > 0 ? stageHeight / CAPTION_STYLE_REFERENCE_HEIGHT : FALLBACK_SCALE;

  const positionFromClientY = useCallback(
    (clientY: number) => {
      const element = stageRef.current;

      if (!element || element.clientHeight === 0) {
        return null;
      }

      const bounds = element.getBoundingClientRect();
      const ratio = ((clientY - bounds.top) / bounds.height) * 100;

      return Math.round(clamp(ratio, 3, 97) * 10) / 10;
    },
    [],
  );

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    setIsDragging(true);

    const next = positionFromClientY(event.clientY);
    if (next !== null) {
      onVerticalPositionChange(next);
    }
  };

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!isDragging) {
      return;
    }

    const next = positionFromClientY(event.clientY);
    if (next !== null) {
      onVerticalPositionChange(next);
    }
  };

  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    setIsDragging(false);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? KEYBOARD_STEP_LARGE : KEYBOARD_STEP;

    if (event.key === "ArrowUp") {
      event.preventDefault();
      onVerticalPositionChange(clamp(style.verticalPosition - step, 3, 97));
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      onVerticalPositionChange(clamp(style.verticalPosition + step, 3, 97));
    }
  };

  const activeText = activeCue?.text ?? null;
  const displayText = activeText === null ? "" : applyUppercase(activeText, style.uppercase);

  // Word highlighting only applies when the cue carries real word timings and a
  // karaoke style is selected. Timings are never invented.
  const words = activeCue?.words;
  const karaoke = style.wordHighlight;
  const spokenWord = karaoke ? activeWordAt(words, currentTime) : null;
  const useWordRendering = Boolean(karaoke && words && words.length > 0);

  // Kept as two separate values so each branch stays precisely typed.
  const wordLines = useWordRendering
    ? wrapWords(
        (words ?? []).map((word) => ({
          ...word,
          word: style.uppercase ? word.word.toUpperCase() : word.word,
        })),
        style.maxCharsPerLine,
      )
    : null;

  const textLines = useWordRendering ? null : wrapCaption(displayText, style.maxCharsPerLine);

  const captionStyle: CSSProperties = {
    top: `${style.verticalPosition}%`,
    maxWidth: `${style.maxWidthPercent}%`,
    fontFamily: CAPTION_FONT_MAP[style.fontFamily],
    fontSize: `${style.fontSize * scale}px`,
    fontWeight: style.fontWeight,
    color: style.textColor,
    textAlign: style.textAlign,
    letterSpacing: `${style.letterSpacing}em`,
    wordSpacing: `${style.wordSpacing}em`,
    lineHeight: style.lineHeight,
    textTransform: style.uppercase ? "uppercase" : "none",
    background: withAlpha(style.backgroundColor, style.backgroundOpacity),
    padding: `${style.backgroundPadding * scale}px`,
    borderRadius: `${style.backgroundRadius * scale}px`,
    WebkitTextStroke: style.outlineEnabled
      ? `${Math.max(style.outlineWidth * scale, 0.5)}px ${style.outlineColor}`
      : undefined,
    paintOrder: style.outlineEnabled ? "stroke fill" : undefined,
    textShadow: style.shadowEnabled
      ? `0 ${Math.max(1 * scale, 0.5)}px ${Math.max(3 * scale, 1)}px rgba(0, 0, 0, 0.75)`
      : undefined,
  };

  return (
    <div className="stage" ref={stageRef}>
      <video
        ref={videoRef}
        className="stage__video"
        src={src}
        controls
        playsInline
        preload="metadata"
        onTimeUpdate={onTimeUpdate}
        onLoadedMetadata={onLoadedMetadata}
      />

      {isPreviewLocked ? (
        <>
          <div className="stage__shield" aria-hidden="true" />
          <PreviewLock onReplayPreview={replayPreview} />
        </>
      ) : null}

      {activeText && !isPreviewLocked ? (
        <div className="overlay" style={{ top: `${style.verticalPosition}%` }}>
          <div
            className={`overlay__text${isDragging ? " is-dragging" : ""}`}
            style={captionStyle}
            role="slider"
            tabIndex={0}
            aria-label="Caption vertical position"
            aria-valuemin={3}
            aria-valuemax={97}
            aria-valuenow={Math.round(style.verticalPosition * 10) / 10}
            aria-valuetext={`${Math.round(style.verticalPosition)} percent from the top`}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={endDrag}
            onPointerCancel={endDrag}
            onKeyDown={handleKeyDown}
          >
            {wordLines
              ? wordLines.map((line, lineIndex) => (
                  <span className="overlay__line" key={`wline-${lineIndex}`}>
                    {line.map((word, wordIndex) => {
                      const isSpoken =
                        spokenWord !== null &&
                        word.start === spokenWord.start &&
                        word.end === spokenWord.end;

                      return (
                        <Fragment key={`word-${lineIndex}-${wordIndex}`}>
                          <span
                            className={`overlay__word${isSpoken ? " is-spoken" : ""}`}
                            style={
                              isSpoken && karaoke
                                ? { color: karaoke.activeColor }
                                : { color: karaoke?.color ?? style.textColor }
                            }
                          >
                            {word.word}
                          </span>
                          {/*
                            A real space between the word elements. `word-spacing`
                            only applies to space characters, so karaoke words would
                            otherwise clump together. This is a rendering separator
                            between separate elements, not a change to the caption
                            text, which stays intact for editing and .srt export.
                          */}
                          {wordIndex < line.length - 1 ? " " : null}
                        </Fragment>
                      );
                    })}
                  </span>
                ))
              : (textLines ?? []).map((line, lineIndex) => (
                  <span className="overlay__line" key={`tline-${lineIndex}`}>
                    {line}
                  </span>
                ))}
          </div>

          {isDragging ? (
            <span className="overlay__badge" aria-hidden="true">
              {style.verticalPosition.toFixed(1)}%
            </span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
