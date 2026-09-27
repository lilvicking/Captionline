/**
 * Finished-video export client.
 *
 * Sends the original video plus the caption data and style exactly as they are in
 * the editor right now, and receives the rendered MP4. The editor's corrections
 * are what get burned in: this never re-transcribes.
 *
 * Export does not consume processing allowance. Transcription is charged once by
 * the transcription endpoint; re-rendering after a change is free, so this can be
 * called as often as the customer likes.
 */

import { API_BASE_URL, TranscriptionError } from "./api";
import type { CaptionCue, CaptionStyle } from "../types";

export type ExportStage = "uploading" | "rendering" | "saving";

export type ExportProgress = {
  stage: ExportStage;
  label: string;
};

const STAGE_LABELS: Record<ExportStage, string> = {
  uploading: "Uploading your video",
  rendering: "Rendering captions into your video",
  saving: "Preparing your download",
};

/**
 * Renders the video and triggers a browser download.
 *
 * `onProgress` reports which phase is in flight. There is deliberately no
 * percentage: the backend does not stream FFmpeg progress, and inventing a number
 * would misinform the customer.
 */
export async function exportCaptionedVideo({
  videoFile,
  captions,
  style,
  token,
  onProgress,
  signal,
}: {
  videoFile: File;
  captions: CaptionCue[];
  style: CaptionStyle;
  token: string;
  onProgress?: (progress: ExportProgress) => void;
  signal?: AbortSignal;
}): Promise<string> {
  if (!token) {
    throw new TranscriptionError("Log in to export your video.", 401);
  }

  // Only captions with something to show are worth sending.
  const payload = captions
    .filter((cue) => cue.text.trim() !== "")
    .map((cue) => ({
      id: cue.id,
      start: Number(cue.start.toFixed(3)),
      end: Number(cue.end.toFixed(3)),
      text: cue.text,
      ...(cue.words && cue.words.length > 0
        ? {
            words: cue.words.map((word) => ({
              word: word.word,
              start: Number(word.start.toFixed(3)),
              end: Number(word.end.toFixed(3)),
              ...(typeof word.score === "number" ? { score: word.score } : {}),
            })),
          }
        : {}),
    }));

  if (payload.length === 0) {
    throw new TranscriptionError("There are no captions to export yet.", 400);
  }

  const form = new FormData();
  form.append("video", videoFile, videoFile.name);
  form.append("captions", JSON.stringify({ captions: payload }));
  form.append("style", JSON.stringify(style));

  onProgress?.({ stage: "uploading", label: STAGE_LABELS.uploading });

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/export/video`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new TranscriptionError(
      "We could not reach the export service. Check your connection and try again.",
      0,
    );
  }

  if (!response.ok) {
    // The backend returns a customer-safe message; surface it rather than a
    // generic failure, but never a server path or a stack trace.
    let message = "The export could not be completed. Please try again.";

    try {
      const error = (await response.json()) as { detail?: unknown };
      if (typeof error.detail === "string" && error.detail.length < 300) {
        message = error.detail;
      }
    } catch {
      // Keep the generic message.
    }

    throw new TranscriptionError(message, response.status);
  }

  onProgress?.({ stage: "rendering", label: STAGE_LABELS.rendering });

  const blob = await response.blob();
  onProgress?.({ stage: "saving", label: STAGE_LABELS.saving });

  // The server sends a sanitised name ending in -captioned.mp4.
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] ?? buildFallbackName(videoFile.name);

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);

  // Release the object URL so a large video does not pin memory.
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);

  return filename;
}

function buildFallbackName(original: string): string {
  const stem = original.replace(/\.[^/.]+$/, "").replace(/[^A-Za-z0-9._-]+/g, "-");
  return `${stem || "video"}-captioned.mp4`;
}
