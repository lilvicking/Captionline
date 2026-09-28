import { useMemo } from "react";
import {
  Captions,
  Download,
  Film,
  Layers,
  Mic,
  PenLine,
  Sparkles,
  Square,
  Type,
  Upload,
  Volume2,
  VolumeX,
} from "lucide-react";
import { usePageMeta } from "../seo/meta";
import {
  FAQ,
  faqPageSchema,
  softwareApplicationSchema,
  webSiteSchema,
} from "../seo/structuredData";

const WORKFLOW = [
  {
    icon: Upload,
    title: "Upload your video",
    body: "Choose a file from your device. Captionline measures it and transcribes the audio with word-level timing, so captions can be placed against the words actually spoken.",
  },
  {
    icon: PenLine,
    title: "Review and edit the captions",
    body: "Correct the words and punctuation, adjust the timing, and add anything the automatic pass missed. The export uses the captions you leave here.",
  },
  {
    icon: Layers,
    title: "Style the captions",
    body: "Set font, size, colour, alignment, spacing, outline, shadow and background, or start from a preset. Position them anywhere, including a precise vertical setting.",
  },
  {
    icon: Download,
    title: "Download the SRT or export the video",
    body: "Take a standard SRT subtitle file, or export a finished MP4 with the captions burned in. Neither export uses processing minutes.",
  },
];

const CAPABILITY_SECTIONS = [
  {
    id: "automatic-captions",
    icon: Captions,
    title: "Automatic video captions",
    body: "Upload a video and Captionline produces a timed caption track from its audio, with word-level alignment so each line lands where the speech actually is. It is a starting point rather than a fixed result: every caption is editable straight afterwards, which is what you want when a name, a number or a technical term was misheard.",
    points: [
      "Transcribes uploaded video and audio",
      "Word-level timing, not just line-level",
      "Every caption stays editable",
      "Short videos and long recordings alike",
    ],
  },
  {
    id: "automatic-subtitles",
    icon: Type,
    title: "Automatic subtitles in SRT",
    body: "Captions are generated as a standard subtitle track. Download it as an SRT file, which is the format video players, editing tools and platforms expect, or keep the captions burned in when a viewer has no way to turn them off.",
    points: [
      "Standard SRT output",
      "Works with external subtitle tracks",
      "Burned-in export for closed captions",
      "No exporting for style changes",
    ],
  },
  {
    id: "caption-styling",
    icon: Sparkles,
    title: "Caption editing and styling",
    body: "A caption designer covers the things that make captions readable or on-brand: the typeface, its size and weight, colour, alignment, letter and word spacing, line height, a background box with its own opacity and padding, an outline, a shadow, and an exact vertical position. Presets cover common looks, and everything remains adjustable afterwards.",
    points: [
      "Font, size, weight and colour",
      "Alignment, letter and word spacing",
      "Background, outline and shadow",
      "Precise vertical positioning and presets",
    ],
  },
  {
    id: "preview",
    icon: Film,
    title: "Preview the whole captioned video",
    body: "Preview the full length of the video with your captions styled as they will appear, and with karaoke-style word highlighting when word timing is available. Nothing is watermarked and nothing is cut short on the free plan.",
    points: [
      "Full-length preview on every plan",
      "Word-by-word highlighting where timing allows",
      "Captions stay inside the frame",
      "Works for vertical and square video too",
    ],
  },
];

const USE_CASES = [
  {
    icon: Square,
    title: "TikTok captions",
    body: "Position captions low so they clear the on-screen buttons, and pick a size and outline that stay readable over a busy background. Export a captioned MP4 sized to your upload.",
  },
  {
    icon: Square,
    title: "Instagram Reels captions",
    body: "Style for vertical video, set the exact vertical position, and export a captioned MP4. Take the SRT instead if your editing workflow uses external subtitle tracks.",
  },
  {
    icon: Square,
    title: "YouTube and Shorts captions",
    body: "Upload the SRT as a subtitle track where you manage your own captions, or export a captioned MP4 for Shorts and anywhere captions must always be visible.",
  },
  {
    icon: Mic,
    title: "Podcast video captions",
    body: "Caption a talking-head or audio-led video, correct any misheard words, and publish with burned-in captions for viewers watching without sound.",
  },
  {
    icon: VolumeX,
    title: "Accessibility and sound-off viewing",
    body: "Captions make your video usable when the audio is off, in a noisy room, or for a viewer who is deaf or hard of hearing. Burning them in means they are always on screen.",
  },
  {
    icon: Volume2,
    title: "Product and business video",
    body: "Keep the look consistent across a library of videos by saving a style you like, then applying the same settings to the next upload.",
  },
  {
    icon: Type,
    title: "Courses and educators",
    body: "Add captions to lessons, review the transcript for accuracy, and download an SRT that other tools and players can read.",
  },
  {
    icon: PenLine,
    title: "Creator workflows",
    body: "Transcribe once, then keep refining the wording and the styling, exporting again as often as you need without spending processing time.",
  },
];

export function CaptionGeneratorPage() {
  // Stable references so the metadata effect does not re-run on every render.
  const structuredData = useMemo(
    () => [
      softwareApplicationSchema("/caption-generator"),
      webSiteSchema(),
      faqPageSchema(FAQ.map((entry) => ({ question: entry.question, answer: entry.answer }))),
    ],
    [],
  );

  usePageMeta({
    title: "Free AI Caption Generator for Video",
    description:
      "Generate video captions automatically, edit them, style them, and export an SRT file or a finished captioned MP4. Free plan includes 10 processing minutes a month.",
    path: "/caption-generator",
    structuredData,
  });

  return (
    <div className="seopage">
      <section className="seopage__hero">
        <p className="eyebrow">Caption generator</p>
        <h1 className="seopage__title">Free AI caption generator for video</h1>
        <p className="seopage__lede">
          Upload a video and Captionline turns the audio into timed captions you can read, correct
          and restyle. Export a standard SRT subtitle file, or export a finished video with the
          captions burned in.
        </p>

        <div className="seopage__cta">
          <a className="button button--primary" href="/#upload">
            Start captioning free
          </a>
          <p className="seopage__cta-note">
            The free plan includes <strong>10 minutes of processing a month</strong>, with editing,
            styling, full preview, SRT download and finished MP4 export all included.
          </p>
        </div>
      </section>

      <section className="seopage__section" aria-labelledby="seopage-workflow">
        <h2 className="seopage__subtitle" id="seopage-workflow">
          How it works
        </h2>
        <ol className="seopage__steps">
          {WORKFLOW.map((step, index) => (
            <li className="seopage__step" key={step.title}>
              <span className="seopage__step-index" aria-hidden="true">
                {index + 1}
              </span>
              <span className="seopage__step-icon" aria-hidden="true">
                <step.icon size={20} />
              </span>
              <h3 className="seopage__step-title">{step.title}</h3>
              <p className="seopage__step-body">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="seopage__section" aria-label="What Captionline can do">
        <h2 className="seopage__subtitle">What you can do</h2>
        <div className="seopage__grid">
          {CAPABILITY_SECTIONS.map((section) => (
            <article className="seopage__card" id={section.id} key={section.id}>
              <span className="seopage__card-icon" aria-hidden="true">
                <section.icon size={20} />
              </span>
              <h3 className="seopage__card-title">{section.title}</h3>
              <p className="seopage__card-body">{section.body}</p>
              <ul className="seopage__points">
                {section.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section className="seopage__section" aria-labelledby="seopage-usecases">
        <h2 className="seopage__subtitle" id="seopage-usecases">
          Made for the places people publish video
        </h2>
        <div className="seopage__grid seopage__grid--wide">
          {USE_CASES.map((useCase) => (
            <article className="seopage__card seopage__card--compact" key={useCase.title}>
              <span className="seopage__card-icon" aria-hidden="true">
                <useCase.icon size={18} />
              </span>
              <h3 className="seopage__card-title">{useCase.title}</h3>
              <p className="seopage__card-body">{useCase.body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="seopage__section seopage__section--free" aria-labelledby="seopage-free">
        <h2 className="seopage__subtitle" id="seopage-free">
          The free plan is not a trial
        </h2>
        <p className="seopage__body">
          The free plan does not expire. It includes 10 minutes of video processing every month, and
          every part of the workflow is available on it: automatic transcription, the caption editor,
          the full caption designer, preview of the whole video, SRT download, and export of a
          finished captioned MP4. Paid plans are for people who need more video processed each month
          — 500 minutes on Creator, 1,500 on Pro.
        </p>
        <p className="seopage__body">
          <a href="/pricing">See all plans and monthly allowances</a>.
        </p>
      </section>

      <section className="seopage__section" aria-labelledby="seopage-faq">
        <h2 className="seopage__subtitle" id="seopage-faq">
          Questions people ask about automatic captions
        </h2>
        <div className="seopage__faq">
          {FAQ.map((entry) => (
            <details className="seopage__faq-item" key={entry.question}>
              <summary className="seopage__faq-question">{entry.question}</summary>
              <p className="seopage__faq-answer">{entry.answer}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="seopage__section seopage__section--cta" aria-labelledby="seopage-cta">
        <h2 className="seopage__subtitle" id="seopage-cta">
          Add captions to your next video
        </h2>
        <p className="seopage__body">
          Upload a video, review the captions, choose a look, and export. The free plan includes 10
          processing minutes a month.
        </p>
        <a className="button button--primary" href="/#upload">
          Start captioning free
        </a>
      </section>
    </div>
  );
}
