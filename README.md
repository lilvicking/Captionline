# Captionline

Captionline is a focused video-captioning SaaS. The product workflow is:

**Upload video → process/transcribe → edit timed captions → style captions → export captions/video**

This repository currently contains **Phase 1: the frontend foundation**.

---

## What Phase 1 does

Phase 1 is a browser-only build that establishes the entire user-facing workflow and the component
architecture that later backend phases will plug into.

- **Landing page** — wordmark, navigation, hero, drag-and-drop upload area, a three-step
  "How it works" section, and a pricing placeholder.
- **Local video selection** — click-to-select or drag-and-drop. The file is validated to be a video
  and read locally via `URL.createObjectURL`. Nothing is uploaded to a server.
- **Processing state** — a short workspace-preparation screen that states clearly that Phase 1 uses
  **sample caption data** and that no transcription engine is connected yet.
- **Caption editor** — real local video preview with a caption overlay, a list of timed captions
  that can be selected, edited, added, and deleted, plus a clickable timeline with a playhead and a
  scrubber.
- **Caption designer** — a full caption style panel with one-click presets (Clean, Bold, Creator,
  Minimal, Boxed, Karaoke) covering font family, size, weight, text colour, alignment, uppercase,
  letter spacing, line height, background colour/opacity/padding/corner radius, text outline,
  outline colour and thickness, text shadow, vertical position, maximum width, and characters per
  line. Every control updates the preview immediately.
- **SRT export** — working client-side `.srt` generation and download from the current caption data.

## What is NOT implemented yet

Nothing below exists in this phase, by design:

- No backend or API server
- No database
- No authentication or user accounts
- No billing or Stripe integration
- No Google Drive or other cloud storage integration
- No real transcription engine — captions are **sample placeholder data**
- No server-side or client-side video rendering. The **Export video** button is intentionally
  **disabled** and labelled as unavailable; it does not fake a render or produce a file. It will be
  enabled when the rendering pipeline is connected in a later phase.
- No final pricing. Plan names are placeholders and no prices are published.

## Tech stack

- React 18 + TypeScript
- Vite 5
- lucide-react (icons)
- Hand-written CSS (no UI framework, no CSS-in-JS)

## Project structure

```
.
├── index.html
├── package.json
├── tsconfig.json
├── vite.config.ts
├── .env.example
└── src/
    ├── main.tsx                  # React entry point
    ├── App.tsx                   # Stage machine: landing -> processing -> editor
    ├── index.css                 # Design tokens and all styles
    ├── types.ts                  # CaptionCue + the CaptionStyle model
    ├── data/
    │   ├── sampleCaptions.ts     # Phase 1 placeholder caption track
    │   ├── captionFonts.ts       # Font id -> CSS stack registry
    │   └── captionPresets.ts     # One-click CaptionStyle presets
    ├── lib/
    │   ├── srt.ts                # .srt generation + client-side download
    │   ├── color.ts              # Hex validation / alpha conversion
    │   ├── text.ts               # Greedy caption line wrapping
    │   └── time.ts               # Timecode / percentage helpers
    └── components/
        ├── Nav.tsx
        ├── Hero.tsx
        ├── UploadZone.tsx        # Click-to-select + drag/drop + video validation
        ├── HowItWorks.tsx
        ├── Pricing.tsx           # Placeholder only, no prices
        ├── Footer.tsx
        ├── ProcessingState.tsx
        └── editor/
            ├── Editor.tsx       # Editor composition, cue state, style state
            ├── CaptionDesigner.tsx  # Presets + Text/Appearance/Position/Layout
            ├── VideoStage.tsx    # Local video, caption overlay, drag positioning
            ├── CaptionTrack.tsx  # Editable caption list
            ├── Timeline.tsx      # Progress visual + scrubbing
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
- `wordHighlight` is reserved for word-level (karaoke) highlighting. Phase 1 stores it but the
  preview ignores it, because there are no word timestamps until a real transcription engine is
  connected. No timing is faked.

## Install

Requires Node.js 18 or newer.

```bash
npm install
```

## Run locally

```bash
npm run dev
```

Then open the printed local URL (default <http://localhost:5173>).

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

Phase 1 needs none. `.env.example` documents the placeholders reserved for later phases. Copy it to
`.env.local` only when those phases add real services.

## Git

Phase 1 work lives on the `phase-1-foundation` branch. `main` is untouched.
