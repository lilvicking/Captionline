import type { CaptionCue } from "../types";

/**
 * Local fallback caption track.
 *
 * Used when transcription is unavailable or no speech is detected, so the editor
 * stays usable. Carries no word timings, which is why the sample track cannot
 * drive karaoke highlighting.
 */
export const SAMPLE_CAPTIONS: CaptionCue[] = [
  { id: "cue-1", start: 0.4, end: 2.6, text: "Every video deserves captions that feel intentional." },
  { id: "cue-2", start: 2.8, end: 5.4, text: "Upload the clip straight from your desktop." },
  { id: "cue-3", start: 5.6, end: 8.2, text: "Captionline prepares a timed caption track for you." },
  { id: "cue-4", start: 8.4, end: 11, text: "Rewrite any line until the wording sounds like you." },
  { id: "cue-5", start: 11.2, end: 13.8, text: "Move the captions, resize the type, check the timing." },
  { id: "cue-6", start: 14, end: 16.6, text: "Then export a subtitle file your platform accepts." },
  { id: "cue-7", start: 16.8, end: 19.4, text: "No manual keyframes, no clunky timeline." },
  { id: "cue-8", start: 19.6, end: 22.2, text: "Built for creators who publish every week." },
  { id: "cue-9", start: 22.4, end: 25, text: "Captions stay readable on every screen size." },
  { id: "cue-10", start: 25.2, end: 27.8, text: "One workflow, from raw footage to finished subtitles." },
];

export function createSampleCues(): CaptionCue[] {
  return SAMPLE_CAPTIONS.map((cue) => ({ ...cue }));
}
