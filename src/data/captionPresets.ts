import { DEFAULT_CAPTION_STYLE } from "../types";
import type { CaptionStyle } from "../types";

export type CaptionPreset = {
  id: string;
  label: string;
  description: string;
  /** Merged over `DEFAULT_CAPTION_STYLE` to produce the full style. */
  style: Partial<CaptionStyle>;
};

/**
 * One-click starting points. Every preset resolves to a complete `CaptionStyle`,
 * and applying one is just a state write, so the user can keep adjusting
 * individual properties afterwards.
 */
export const CAPTION_PRESETS: CaptionPreset[] = [
  {
    id: "clean",
    label: "Clean",
    description: "White text, soft shadow, no box",
    style: {
      fontFamily: "system",
      fontSize: 42,
      fontWeight: 600,
      textColor: "#FFFFFF",
      backgroundOpacity: 0,
      backgroundPadding: 10,
      backgroundRadius: 6,
      outlineEnabled: false,
      shadowEnabled: true,
      lineHeight: 1.3,
      letterSpacing: 0,
      wordSpacing: 0.02,
      maxWidthPercent: 80,
      maxCharsPerLine: null,
      verticalPosition: 88,
    },
  },
  {
    id: "bold",
    label: "Bold",
    description: "Large uppercase with a hard outline",
    style: {
      fontFamily: "helvetica",
      fontSize: 58,
      fontWeight: 800,
      textColor: "#FFFFFF",
      uppercase: true,
      letterSpacing: -0.01,
      wordSpacing: 0.04,
      lineHeight: 1.1,
      backgroundOpacity: 0,
      backgroundPadding: 8,
      backgroundRadius: 4,
      outlineEnabled: true,
      outlineColor: "#000000",
      outlineWidth: 4,
      shadowEnabled: false,
      maxWidthPercent: 88,
      maxCharsPerLine: 30,
      verticalPosition: 84,
    },
  },
  {
    id: "creator",
    label: "Creator",
    description: "Captionline red block",
    style: {
      fontFamily: "trebuchet",
      fontSize: 44,
      fontWeight: 700,
      textColor: "#FFFFFF",
      textAlign: "center",
      letterSpacing: 0,
      wordSpacing: 0.03,
      lineHeight: 1.25,
      backgroundColor: "#FF0033",
      backgroundOpacity: 1,
      backgroundPadding: 16,
      backgroundRadius: 10,
      outlineEnabled: false,
      shadowEnabled: false,
      maxWidthPercent: 70,
      maxCharsPerLine: 26,
      verticalPosition: 86,
    },
  },
  {
    id: "minimal",
    label: "Minimal",
    description: "Light serif, centred, quiet",
    style: {
      fontFamily: "georgia",
      fontSize: 38,
      fontWeight: 400,
      textColor: "#F2F2F2",
      textAlign: "center",
      letterSpacing: 0.02,
      wordSpacing: 0.04,
      lineHeight: 1.45,
      backgroundOpacity: 0,
      backgroundPadding: 8,
      backgroundRadius: 0,
      outlineEnabled: false,
      shadowEnabled: true,
      maxWidthPercent: 66,
      maxCharsPerLine: null,
      verticalPosition: 90,
    },
  },
  {
    id: "boxed",
    label: "Boxed",
    description: "Opaque black plate behind the text",
    style: {
      fontFamily: "system",
      fontSize: 40,
      fontWeight: 600,
      textColor: "#FFFFFF",
      textAlign: "center",
      letterSpacing: 0,
      wordSpacing: 0.02,
      lineHeight: 1.3,
      backgroundColor: "#000000",
      backgroundOpacity: 0.78,
      backgroundPadding: 18,
      backgroundRadius: 8,
      outlineEnabled: false,
      shadowEnabled: false,
      maxWidthPercent: 76,
      maxCharsPerLine: 32,
      verticalPosition: 87,
    },
  },
  {
    id: "karaoke",
    label: "Karaoke",
    description: "Heavy display look, word highlight colours reserved",
    style: {
      fontFamily: "impact",
      fontSize: 54,
      fontWeight: 400,
      textColor: "#FFFFFF",
      textAlign: "center",
      uppercase: true,
      letterSpacing: 0.01,
      // Generous word gap: karaoke words render as separate elements for
      // highlighting, and the heavy uppercase face clumps badly without it.
      wordSpacing: 0.12,
      lineHeight: 1.15,
      backgroundColor: "#000000",
      backgroundOpacity: 0.35,
      backgroundPadding: 10,
      backgroundRadius: 6,
      outlineEnabled: true,
      outlineColor: "#000000",
      outlineWidth: 3,
      shadowEnabled: true,
      maxWidthPercent: 84,
      maxCharsPerLine: 24,
      verticalPosition: 74,
      // Highlight colours drive the active word, driven by the word-level
      // timestamps returned by the transcription service.
      wordHighlight: {
        color: "#FFD400",
        activeColor: "#FF0033",
      },
    },
  },
];

/** Expands a preset into a complete style. */
export function resolvePreset(preset: CaptionPreset): CaptionStyle {
  return { ...DEFAULT_CAPTION_STYLE, ...preset.style };
}

/** Field-by-field comparison, including the optional word-highlight block. */
export function stylesMatch(a: CaptionStyle, b: CaptionStyle): boolean {
  const keys = Object.keys(DEFAULT_CAPTION_STYLE) as (keyof CaptionStyle)[];

  const differs = keys.some((key) => a[key] !== b[key]);
  if (differs) {
    return false;
  }

  const aHighlight = a.wordHighlight;
  const bHighlight = b.wordHighlight;

  if (aHighlight === undefined && bHighlight === undefined) {
    return true;
  }

  if (aHighlight === undefined || bHighlight === undefined) {
    return false;
  }

  return aHighlight.color === bHighlight.color && aHighlight.activeColor === bHighlight.activeColor;
}
