import type { CaptionCue } from "../types";

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

/** Formats seconds as an SRT timestamp: HH:MM:SS,mmm */
export function toSrtTimestamp(seconds: number): string {
  const safe = Number.isFinite(seconds) && seconds > 0 ? seconds : 0;
  const totalMs = Math.round(safe * 1000);
  const millis = totalMs % 1000;
  const totalSeconds = Math.floor(totalMs / 1000);
  const secs = totalSeconds % 60;
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const hours = Math.floor(totalSeconds / 3600);

  return `${pad(hours)}:${pad(minutes)}:${pad(secs)},${pad(millis, 3)}`;
}

/** Builds a valid SubRip (.srt) document from the current caption cues. */
export function buildSrt(cues: CaptionCue[]): string {
  const blocks = [...cues]
    .sort((a, b) => a.start - b.start)
    .map((cue, index) => {
      const text = cue.text.trim();
      return [
        String(index + 1),
        `${toSrtTimestamp(cue.start)} --> ${toSrtTimestamp(cue.end)}`,
        text === "" ? " " : text,
      ].join("\n");
    });

  return `${blocks.join("\n\n")}\n`;
}

/** Strips the video extension and any characters that are unsafe in file names. */
export function srtFileName(videoName: string): string {
  const withoutExtension = videoName.replace(/\.[^/.]+$/, "");
  const trimmed = withoutExtension.trim();
  const base = trimmed === "" ? "captionline-captions" : trimmed;
  return base.replace(/[\\/:*?"<>|]+/g, "-");
}

/** Triggers a client-side download of the captions as an .srt file. */
export function downloadSrt(cues: CaptionCue[], videoName: string): void {
  const blob = new Blob([buildSrt(cues)], { type: "application/x-subrip;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");

  anchor.href = url;
  anchor.download = `${srtFileName(videoName)}.srt`;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
