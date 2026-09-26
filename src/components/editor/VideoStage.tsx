import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties, KeyboardEvent, PointerEvent, RefObject } from "react";
import { clamp } from "../../lib/time";
import { withAlpha } from "../../lib/color";
import { applyUppercase, wrapCaption } from "../../lib/text";
import { CAPTION_FONT_MAP } from "../../data/captionFonts";
import { CAPTION_STYLE_REFERENCE_HEIGHT } from "../../types";
import type { CaptionStyle } from "../../types";

/** Used before the stage has been measured, so the first paint is already sane. */
const FALLBACK_SCALE = 1 / 3;

const KEYBOARD_STEP = 1;
const KEYBOARD_STEP_LARGE = 5;

type VideoStageProps = {
  videoRef: RefObject<HTMLVideoElement>;
  src: string;
  activeText: string | null;
  style: CaptionStyle;
  onVerticalPositionChange: (value: number) => void;
  onTimeUpdate: () => void;
  onLoadedMetadata: () => void;
};

export function VideoStage({
  videoRef,
  src,
  activeText,
  style,
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

  const lines = applyUppercase(activeText ?? "", style.uppercase);
  const wrappedLines = wrapCaption(lines, style.maxCharsPerLine);

  const captionStyle: CSSProperties = {
    top: `${style.verticalPosition}%`,
    maxWidth: `${style.maxWidthPercent}%`,
    fontFamily: CAPTION_FONT_MAP[style.fontFamily],
    fontSize: `${style.fontSize * scale}px`,
    fontWeight: style.fontWeight,
    color: style.textColor,
    textAlign: style.textAlign,
    letterSpacing: `${style.letterSpacing}em`,
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

      {activeText ? (
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
            {wrappedLines.map((line, index) => (
              <span className="overlay__line" key={`${index}-${line}`}>
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
