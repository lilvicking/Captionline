/** Text layout helpers for the caption overlay. */

import type { CaptionWord } from "../types";

/**
 * Greedy word wrap against a character budget.
 *
 * Words longer than the budget are hard-split rather than allowed to overflow,
 * which is the same rule a rendering backend would apply. A `null` budget means
 * the renderer wraps on the video width alone.
 */
export function wrapCaption(text: string, maxCharsPerLine: number | null): string[] {
  return wrapWords(toWords(text), maxCharsPerLine).map((line) =>
    line.map((word) => word.word).join(" "),
  );
}

/** Splits caption text into whitespace-delimited pseudo-words for wrapping. */
function toWords(text: string): CaptionWord[] {
  return text
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter((word) => word !== "")
    .map((word) => ({ word, start: 0, end: 0 }));
}

/**
 * Wraps real words, keeping each word intact so callers can render word-level
 * highlighting. Words longer than the budget are hard-split into pieces that
 * still carry the original timing, matching the renderer's wrapping rule.
 */
export function wrapWords(
  words: CaptionWord[],
  maxCharsPerLine: number | null,
): CaptionWord[][] {
  if (words.length === 0) {
    return [];
  }

  const unlimited = maxCharsPerLine === null || !Number.isFinite(maxCharsPerLine) || maxCharsPerLine < 1;

  if (unlimited) {
    return [words];
  }

  const limit = Math.floor(maxCharsPerLine);
  const lines: CaptionWord[][] = [];
  let current: CaptionWord[] = [];
  let currentLength = 0;

  const flush = () => {
    if (current.length > 0) {
      lines.push(current);
      current = [];
      currentLength = 0;
    }
  };

  for (const word of words) {
    const pieces =
      word.word.length > limit
        ? splitWord(word, limit)
        : [word];

    for (const piece of pieces) {
      const addition = currentLength === 0 ? piece.word.length : currentLength + 1 + piece.word.length;

      if (currentLength > 0 && addition > limit) {
        flush();
      }

      current.push(piece);
      currentLength =
        currentLength === 0 ? piece.word.length : currentLength + 1 + piece.word.length;
    }
  }

  flush();
  return lines;
}

/** Hard-splits an over-long word into budget-sized pieces sharing its timing. */
function splitWord(word: CaptionWord, limit: number): CaptionWord[] {
  const pieces: CaptionWord[] = [];
  const total = word.word.length;
  const span = Math.max(word.end - word.start, 0);

  for (let offset = 0; offset < total; offset += limit) {
    const chunk = word.word.slice(offset, offset + limit);
    const ratioStart = offset / total;
    const ratioEnd = Math.min((offset + chunk.length) / total, 1);

    pieces.push({
      ...word,
      word: chunk,
      start: word.start + span * ratioStart,
      end: word.start + span * ratioEnd,
    });
  }

  return pieces;
}

export function applyUppercase(text: string, uppercase: boolean): string {
  return uppercase ? text.toUpperCase() : text;
}
