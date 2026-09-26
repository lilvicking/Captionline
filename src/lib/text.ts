/** Text layout helpers for the caption overlay. */

/**
 * Greedy word wrap against a character budget.
 *
 * Words longer than the budget are hard-split rather than allowed to overflow,
 * which is the same rule a rendering backend would apply. A `null` budget means
 * the renderer wraps on the video width alone.
 */
export function wrapCaption(text: string, maxCharsPerLine: number | null): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();

  if (normalized === "") {
    return [];
  }

  if (maxCharsPerLine === null || !Number.isFinite(maxCharsPerLine) || maxCharsPerLine < 1) {
    return [normalized];
  }

  const limit = Math.floor(maxCharsPerLine);
  const lines: string[] = [];
  let current = "";

  for (const word of normalized.split(" ")) {
    if (word.length > limit) {
      if (current !== "") {
        lines.push(current);
        current = "";
      }

      for (let index = 0; index < word.length; index += limit) {
        lines.push(word.slice(index, index + limit));
      }

      continue;
    }

    if (current === "") {
      current = word;
    } else if (current.length + 1 + word.length <= limit) {
      current = `${current} ${word}`;
    } else {
      lines.push(current);
      current = word;
    }
  }

  if (current !== "") {
    lines.push(current);
  }

  return lines;
}

export function applyUppercase(text: string, uppercase: boolean): string {
  return uppercase ? text.toUpperCase() : text;
}
