import type { CaptionCue, CaptionWord } from "../types";

/**
 * Client for the Captionline transcription service.
 *
 * The base URL comes from VITE_API_URL so the same build can target a local
 * backend or a deployed one (Railway) without source changes.
 */

const configuredUrl = import.meta.env.VITE_API_URL?.trim();

export const API_BASE_URL = (configuredUrl && configuredUrl.length > 0
  ? configuredUrl
  : "http://localhost:8000"
).replace(/\/+$/, "");

export type TranscriptionWord = {
  word: string;
  start: number;
  end: number;
  score?: number | null;
};

export type TranscriptionSegment = {
  id: number;
  start: number;
  end: number;
  text: string;
  words: TranscriptionWord[];
};

export type TranscriptionResult = {
  language: string;
  duration: number;
  segments: TranscriptionSegment[];
  model: string;
  device: string;
  compute_type: string;
  word_aligned: boolean;
};

export type HealthResult = {
  status: string;
  version: string;
  whisperx_model: string;
  device: string;
  compute_type: string;
  batch_size: number;
  model_loaded: boolean;
  alignment_enabled: boolean;
  cuda_available: boolean;
};

export class TranscriptionError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "TranscriptionError";
    this.status = status;
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Fall through to the status text below.
  }
  return response.statusText || `Request failed with status ${response.status}`;
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResult> {
  const response = await fetch(`${API_BASE_URL}/api/health`, { signal });

  if (!response.ok) {
    throw new TranscriptionError(await readError(response), response.status);
  }

  return (await response.json()) as HealthResult;
}

/**
 * Uploads a local media file for transcription.
 *
 * The file is sent as multipart/form-data under the `file` field. Progress is
 * reported through the request lifecycle only, since fetch cannot report
 * upload progress.
 */
export async function transcribeFile(
  file: File,
  signal?: AbortSignal,
): Promise<TranscriptionResult> {
  const body = new FormData();
  body.append("file", file, file.name);

  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}/api/transcribe`, {
      method: "POST",
      body,
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new TranscriptionError(
      `Could not reach the transcription service at ${API_BASE_URL}.`,
      0,
    );
  }

  if (!response.ok) {
    throw new TranscriptionError(await readError(response), response.status);
  }

  return (await response.json()) as TranscriptionResult;
}

/** Maps one returned word onto Captionline's caption word shape. */
function toCaptionWord(word: TranscriptionWord): CaptionWord | null {
  if (!word || typeof word.word !== "string" || word.word.trim() === "") {
    return null;
  }

  if (!Number.isFinite(word.start) || !Number.isFinite(word.end)) {
    return null;
  }

  return {
    word: word.word,
    start: word.start,
    end: word.end,
    ...(typeof word.score === "number" ? { score: word.score } : {}),
  };
}

/**
 * Converts the service response into the existing Captionline cue structure so
 * the editor and caption designer work unchanged.
 */
export function segmentsToCues(segments: TranscriptionSegment[]): CaptionCue[] {
  return segments
    .map((segment, index) => {
      const text = segment.text?.trim() ?? "";
      const start = Number.isFinite(segment.start) ? segment.start : 0;
      const end = Number.isFinite(segment.end) ? segment.end : start;
      const words = (segment.words ?? [])
        .map(toCaptionWord)
        .filter((word): word is CaptionWord => word !== null);

      return {
        id: `transcribed-${index}-${start}`,
        start,
        // Guard against a reversed range so the timeline never renders negative.
        end: Math.max(end, start + 0.1),
        text,
        ...(words.length > 0 ? { words } : {}),
      };
    })
    .filter((cue) => cue.text !== "" || (cue.words?.length ?? 0) > 0);
}
