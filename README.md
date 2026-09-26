# Captionline

Captionline is a focused video-captioning SaaS. The product workflow is:

**Upload video → process/transcribe → edit timed captions → style captions → export captions/video**

Phase 1 is the frontend foundation. **Phase 2 adds real transcription** through a Python
WhisperX service.

---

## What Phase 1 does

Phase 1 is a browser-only build that establishes the entire user-facing workflow and the component
architecture that later backend phases plug into.

- **Landing page** — wordmark, navigation, hero, drag-and-drop upload area, a three-step
  "How it works" section, and a pricing placeholder.
- **Local video selection** — click-to-select or drag-and-drop. The file is validated to be a video
  and read locally via `URL.createObjectURL`.
- **Processing state** — shows the transcription progress and reports clearly when the service is
  unavailable.
- **Caption editor** — real local video preview with a caption overlay, a list of timed captions
  that can be selected, edited, added, and deleted, plus a clickable timeline with a playhead and a
  scrubber.
- **Caption designer** — a full caption style panel with one-click presets (Clean, Bold, Creator,
  Minimal, Boxed, Karaoke) covering font family, size, weight, text colour, alignment, uppercase,
  letter spacing, word spacing, line height, background colour/opacity/padding/corner radius, text
  outline, outline colour and thickness, text shadow, vertical position, maximum width, and
  characters per line. Every control updates the preview immediately.
- **Karaoke word highlighting** — when the Karaoke preset is active and the caption came back with
  word timings, the word spanning `video.currentTime` is highlighted in real time.
- **Free-tier preview protection** — unpaid users get the first 30 seconds of the finished video
  preview. Playback stops at the boundary, seeking past it is refused, and a locked state covers the
  preview. Editing is never restricted.
- **SRT export** — working client-side `.srt` generation and download from the current caption data.

## What Phase 2 adds

- **`backend/`** — a small FastAPI service that transcribes an uploaded video or audio file with
  **WhisperX** and returns **word-level timestamps** in Captionline's own JSON format.
- The upload flow now calls `POST /api/transcribe`. Real captions replace the sample data when the
  service responds; if it is unreachable, the editor still opens with sample captions.
- Captions keep their word timings, which is what the karaoke preset highlights.

See [`backend/README.md`](backend/README.md) for the full service documentation, model
configuration, and Railway deployment.

## What is NOT implemented yet

Nothing below exists yet, by design:

- No database
- No authentication or user accounts
- No billing or Stripe integration
- No Google Drive or other cloud storage integration
- No permanent media storage (uploads are temporary and deleted immediately)
- No server-side or client-side video rendering. The **Export video** button is intentionally
  **disabled** and labelled as unavailable; it does not fake a render or produce a file.
- No speaker diarization, no translation, no analytics
- No background job queue, so very long videos on CPU may exceed a proxy timeout
- No accounts, no authentication, and no real subscription entitlement. The preview limit is enforced
  in the browser only, so it is a UX gate and not a security boundary (see below).
- No video export. The **Export video** button remains disabled and does not fake a render.
- No final pricing. Plan names are placeholders and no prices are published.

## Preview entitlement (Phase 2)

`src/entitlement.ts` holds the whole preview policy in one typed place:

```ts
export const FREE_PREVIEW_SECONDS = 30;

export type PreviewEntitlement = {
  previewLimitSeconds: number | null; // null = unrestricted
  hasFullPreview: boolean;
  source: "free-tier" | "server";
};
```

`resolvePreviewEntitlement()` always returns the free tier today. There is deliberately **no**
`isPaid = true` development flag that could be flipped and shipped by accident.

Unpaid users may transcribe, read, edit, restyle, and export captions for their entire project. The
limit applies only to the **finished video preview**:

- playback stops when it reaches the boundary
- seeking past the boundary is pulled back, so protected frames are never shown
- the browser's own video controls are covered by the same guard, because they drive the same
  `seeking` event

The timeline still represents the whole video and shades the protected region. Selecting a caption
past the boundary still selects and edits that caption; it simply does not move the protected
playhead there.

### This is not a security boundary

The frontend must never be the component that decides whether someone has paid. When accounts and
billing are implemented, the **backend** must determine entitlement from the authenticated
account's subscription and return it; the client then reflects that instead of assuming the free
tier. Until that endpoint exists this module is UX-level only.

## Tech stack

- React 18 + TypeScript
- Vite 5
- lucide-react (icons)
- Hand-written CSS (no UI framework, no CSS-in-JS)
- Backend: Python 3.12, FastAPI, Uvicorn, WhisperX (faster-whisper + alignment)

## Project structure

```
.
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── .env.example                # VITE_API_URL for the frontend
├── .env.local                  # local overrides (git-ignored)
├── README.md
├── backend/                    # Phase 2 transcription service
│   ├── app/
│   │   ├── main.py             # FastAPI app, CORS, health, /api/transcribe
│   │   ├── config.py           # Env-driven settings + device resolution
│   │   ├── schemas.py          # Captionline response models
│   │   └── transcribe.py       # WhisperX lifecycle + output normalization
│   ├── requirements.txt
│   ├── requirements.lock.txt
│   ├── Dockerfile
│   └── README.md
└── src/
    ├── main.tsx                  # React entry point
    ├── App.tsx                   # Stage machine: landing -> processing -> editor
    ├── index.css                 # Design tokens and all styles
    ├── types.ts                  # CaptionCue, CaptionWord, the CaptionStyle model
    ├── entitlement.ts            # Preview entitlement policy (free tier = 30s preview)
    ├── vite-env.d.ts             # VITE_API_URL typing
    ├── data/
    │   ├── sampleCaptions.ts     # Phase 1 fallback caption track
    │   ├── captionFonts.ts       # Font id -> CSS stack registry
    │   └── captionPresets.ts     # One-click CaptionStyle presets
    ├── lib/
    │   ├── api.ts                # Transcription client + response -> cue mapping
    │   ├── srt.ts                # .srt generation + client-side download
    │   ├── color.ts              # Hex validation / alpha conversion
    │   ├── text.ts               # Greedy caption line/word wrapping
    │   └── time.ts               # Timecode / percentage helpers
    └── components/
        ├── Nav.tsx
        ├── Hero.tsx
        ├── UploadZone.tsx        # Click-to-select + drag/drop + video validation
        ├── HowItWorks.tsx
        ├── Pricing.tsx           # Placeholder only, no prices
        ├── Footer.tsx
        ├── ProcessingState.tsx   # Real transcription progress + fallback notice
        └── editor/
            ├── Editor.tsx       # Editor composition, cue state, style state
            ├── CaptionDesigner.tsx  # Presets + Text/Appearance/Position/Layout
            ├── VideoStage.tsx    # Local video, caption overlay, drag positioning, karaoke, preview gate
            ├── PreviewLock.tsx   # Free-tier locked preview state
            ├── CaptionTrack.tsx  # Editable caption list
            ├── Timeline.tsx      # Progress visual + scrubbing + protected region
            ├── ExportPanel.tsx   # SRT export + disabled video export
            └── controls/
                └── CaptionControls.tsx  # Range, colour, toggle, select, segmented
```

The `CaptionCue` model (`{ id, start, end, text }`) is the contract a future transcription service
will return, so the editor wiring does not need to change when real transcription is connected.

### CaptionStyle and the future renderer

All caption styling lives in one typed `CaptionStyle` object (`src/types.ts`) rather than being
scattered across components. The video preview consumes that object directly, and its values are
designed to be handed to a rendering backend unchanged:

- Every pixel value (`fontSize`, `backgroundPadding`, `backgroundRadius`, `outlineWidth`) is
  expressed against a **1080px-tall reference frame** (`CAPTION_STYLE_REFERENCE_HEIGHT`). The preview
  scales them to the rendered stage height, which is the same arithmetic a renderer performs.
- Colours are plain hex strings plus a separate `backgroundOpacity` value, so a backend can compose
  them as it needs.
- `verticalPosition` is a single percentage from the top edge. The Top / Middle / Bottom buttons are
  derived from it, so the slider and the quick presets can never disagree.
- `maxCharsPerLine` uses the same greedy word-wrap rule as the preview
  (`src/lib/text.ts`), including hard-splitting of over-long words.
- `wordHighlight` drives karaoke. The active word is whichever word timestamp contains
  `video.currentTime`, so highlighting follows the real alignment rather than a guessed timeline.
- `letterSpacing` (between characters) and `wordSpacing` (between words) are independent `em` values.
  Both are purely visual: caption text, transcription data, and `.srt` output are never modified.

## Install

Frontend requires Node.js 18 or newer.

```bash
npm install
```

## Run the frontend locally

```bash
npm run dev
```

Then open the printed local URL (default <http://localhost:5173>).

The frontend reads the backend location from `VITE_API_URL`:

```bash
cp .env.example .env.local
```

`VITE_API_URL=http://localhost:8000` is the default, so no local configuration is required.

## Run the backend locally

Requires **Python 3.12** and `ffmpeg` on `PATH`.

```bash
cd backend
python3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows
source .venv/bin/activate           # macOS / Linux

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Check it:

```bash
curl http://localhost:8000/api/health
```

Full backend documentation, model configuration, and GPU notes:
[`backend/README.md`](backend/README.md).

## Production build

```bash
npm run build
```

This runs the TypeScript check (`tsc --noEmit`) and then builds to `dist/`.

Preview the production build locally:

```bash
npm run preview
```

## Environment variables

### Frontend (Vite)

| Variable | Purpose |
| -------- | ------- |
| `VITE_API_URL` | Base URL of the transcription service. Production example: `https://<backend>.up.railway.app` |

Only `VITE_`-prefixed variables reach the browser bundle, so no secret ever belongs in this file.

### Backend

Server-side configuration lives in `backend/.env.example`: `WHISPERX_MODEL`, `WHISPERX_DEVICE`,
`WHISPERX_COMPUTE_TYPE`, `WHISPERX_BATCH_SIZE`, `CORS_ORIGINS`, `MAX_UPLOAD_MB`, `PORT`, and
`PRELOAD_MODEL`. These must **not** be prefixed with `VITE_`.

## Railway deployment

The backend is Railway-ready: it binds `0.0.0.0`, reads `PORT`, uses temporary storage only, and
contains no Windows-specific behavior. `backend/Dockerfile` is a CPU image with `ffmpeg` installed
and a container-aware start command.

Set on the Railway service:

```
WHISPERX_MODEL=small
WHISPERX_DEVICE=cpu
WHISPERX_COMPUTE_TYPE=int8
CORS_ORIGINS=https://<your-frontend-domain>
MAX_UPLOAD_MB=500
```

Then set `VITE_API_URL` on the frontend to the Railway backend URL and rebuild the frontend. No
source change is needed to switch environments.

**Not yet done:** nothing has been deployed, no Railway resources were created, and no GPU
infrastructure was provisioned. See the size and timeout caveats in `backend/README.md`.

## Git

- Phase 1 lives on `phase-1-foundation` (committed as `542f718`).
- Phase 2 work is on `phase-2-transcription`.
- `main` is untouched.
