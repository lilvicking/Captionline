import type { CaptionFontId } from "../types";

/**
 * Font stacks are limited to faces that ship with Windows, macOS, and common
 * Linux distributions, so the preview works offline with no font loading and no
 * new dependency. A rendering backend maps `CaptionFontId` to its own font file
 * rather than to a CSS stack.
 */
export type CaptionFont = {
  id: CaptionFontId;
  label: string;
  stack: string;
};

export const CAPTION_FONTS: CaptionFont[] = [
  {
    id: "system",
    label: "System Sans",
    stack: 'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
  },
  {
    id: "helvetica",
    label: "Helvetica",
    stack: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  },
  {
    id: "trebuchet",
    label: "Trebuchet",
    stack: '"Trebuchet MS", "Lucida Grande", "Segoe UI", sans-serif',
  },
  {
    id: "georgia",
    label: "Serif",
    stack: 'Georgia, "Times New Roman", Times, serif',
  },
  {
    id: "impact",
    label: "Impact",
    stack: 'Impact, Haettenschweiler, "Arial Narrow Bold", sans-serif',
  },
  {
    id: "mono",
    label: "Monospace",
    stack: 'ui-monospace, "Cascadia Mono", Consolas, "Courier New", monospace',
  },
];

export const CAPTION_FONT_MAP: Record<CaptionFontId, string> = CAPTION_FONTS.reduce(
  (map, font) => {
    map[font.id] = font.stack;
    return map;
  },
  {} as Record<CaptionFontId, string>,
);
