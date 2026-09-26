/** Colour helpers shared by the preview and, later, the render payload. */

const HEX_PATTERN = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i;

/** Accepts `#abc` / `#aabbcc` (with or without `#`) and returns a 6-digit hex. */
export function normalizeHex(value: string): string {
  const match = HEX_PATTERN.exec(value.trim());

  if (!match) {
    return "#000000";
  }

  const digits = match[1].toLowerCase();

  if (digits.length === 3) {
    return `#${digits
      .split("")
      .map((digit) => digit + digit)
      .join("")}`;
  }

  return `#${digits}`;
}

export function isValidHex(value: string): boolean {
  return HEX_PATTERN.test(value.trim());
}

type Rgb = { r: number; g: number; b: number };

export function hexToRgb(value: string): Rgb {
  const hex = normalizeHex(value);

  return {
    r: parseInt(hex.slice(1, 3), 16),
    g: parseInt(hex.slice(3, 5), 16),
    b: parseInt(hex.slice(5, 7), 16),
  };
}

/** Converts a hex colour plus an alpha value into a CSS rgba() string. */
export function withAlpha(value: string, alpha: number): string {
  const { r, g, b } = hexToRgb(value);
  const clamped = Number.isFinite(alpha) ? Math.min(Math.max(alpha, 0), 1) : 0;

  return `rgba(${r}, ${g}, ${b}, ${clamped})`;
}

/** True when the two colours would render the same, ignoring alpha. */
export function sameColor(a: string, b: string): boolean {
  return normalizeHex(a) === normalizeHex(b);
}
