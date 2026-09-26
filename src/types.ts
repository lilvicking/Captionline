export type CaptionCue = {
  id: string;
  /** Start time in seconds. */
  start: number;
  /** End time in seconds. */
  end: number;
  text: string;
};

/* -------------------------------------------------------------------------- */
/* Caption style model                                                        */
/* -------------------------------------------------------------------------- */

/**
 * All pixel values in `CaptionStyle` are expressed against a 1080px-tall
 * reference frame. The browser preview scales them to the rendered video
 * height, and a future rendering backend can reuse the exact same numbers when
 * burning captions into an exported video. Keeping the unit explicit is what
 * makes the preview and the renderer agree.
 */
export const CAPTION_STYLE_REFERENCE_HEIGHT = 1080;

export type CaptionFontId = "system" | "helvetica" | "georgia" | "trebuchet" | "impact" | "mono";

export type CaptionTextAlign = "left" | "center" | "right";

export type CaptionPositionPreset = "top" | "middle" | "bottom";

export type CaptionStyle = {
  /* Text */
  fontFamily: CaptionFontId;
  /** px, relative to `CAPTION_STYLE_REFERENCE_HEIGHT`. */
  fontSize: number;
  fontWeight: number;
  /** Hex colour, e.g. "#FFFFFF". */
  textColor: string;
  textAlign: CaptionTextAlign;
  uppercase: boolean;
  /** em */
  letterSpacing: number;
  /** unitless multiplier */
  lineHeight: number;

  /* Appearance */
  backgroundColor: string;
  /** 0 = fully transparent, 1 = fully opaque. */
  backgroundOpacity: number;
  /** px, relative to the reference frame. */
  backgroundPadding: number;
  backgroundRadius: number;
  outlineEnabled: boolean;
  outlineColor: string;
  /** px, relative to the reference frame. */
  outlineWidth: number;
  shadowEnabled: boolean;

  /* Position */
  /**
   * Single source of truth for vertical placement: percentage of the video
   * height, measured from the top edge. The Top / Middle / Bottom buttons are
   * derived from this value so the slider and the presets can never disagree.
   */
  verticalPosition: number;

  /* Layout */
  /** Percentage of the video width the caption block may occupy. */
  maxWidthPercent: number;
  /** null = no character limit, otherwise greedy word wrap at this budget. */
  maxCharsPerLine: number | null;

  /**
   * Reserved for word-level (karaoke) highlighting.
   *
   * Phase 1 has no word-level timestamps, so the preview ignores this and no
   * timing is faked. The field exists so a future transcription service that
   * returns per-word timings can drive highlighting without reshaping the model
   * or the editor wiring.
   */
  wordHighlight?: {
    color: string;
    activeColor: string;
  };
};

export const DEFAULT_CAPTION_STYLE: CaptionStyle = {
  fontFamily: "system",
  fontSize: 42,
  fontWeight: 700,
  textColor: "#FFFFFF",
  textAlign: "center",
  uppercase: false,
  letterSpacing: 0,
  lineHeight: 1.25,

  backgroundColor: "#000000",
  backgroundOpacity: 0,
  backgroundPadding: 12,
  backgroundRadius: 8,
  outlineEnabled: false,
  outlineColor: "#000000",
  outlineWidth: 2,
  shadowEnabled: true,

  verticalPosition: 88,

  maxWidthPercent: 80,
  maxCharsPerLine: null,
};

/** The caption block is kept inside the frame at these vertical positions. */
export const CAPTION_MIN_VERTICAL_POSITION = 3;
export const CAPTION_MAX_VERTICAL_POSITION = 97;

export const POSITION_PRESET_VALUES: Record<CaptionPositionPreset, number> = {
  top: 8,
  middle: 50,
  bottom: 88,
};

/** Derives the highlighted quick preset from the precise vertical position. */
export function positionPresetFor(verticalPosition: number): CaptionPositionPreset {
  const entries = Object.entries(POSITION_PRESET_VALUES) as [CaptionPositionPreset, number][];

  return entries.reduce((closest, entry) =>
    Math.abs(entry[1] - verticalPosition) < Math.abs(closest[1] - verticalPosition) ? entry : closest,
  )[0];
}
