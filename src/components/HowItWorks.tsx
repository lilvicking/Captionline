import { Captions, Download, Upload } from "lucide-react";

const STEPS = [
  {
    icon: Upload,
    title: "Upload",
    body: "Drop in a video from your desktop. It stays local to your browser for now.",
  },
  {
    icon: Captions,
    title: "Caption",
    body: "Get a timed caption track, then edit the text, size, and position until it fits.",
  },
  {
    icon: Download,
    title: "Export",
    body: "Download a standard .srt subtitle file, ready for YouTube or your own player.",
  },
];

export function HowItWorks() {
  return (
    <section className="section" id="how-it-works">
      <div className="section__inner">
        <header className="section__head">
          <p className="eyebrow">How it works</p>
          <h2 className="section__title">Three steps, start to finish</h2>
          <p className="section__lede">
            The whole workflow is built around one idea: get to a publishable caption file as fast
            as possible.
          </p>
        </header>

        <ol className="steps">
          {STEPS.map((step, index) => (
            <li className="step" key={step.title}>
              <span className="step__index" aria-hidden="true">
                {index + 1}
              </span>
              <span className="step__icon" aria-hidden="true">
                <step.icon size={20} />
              </span>
              <h3 className="step__title">{step.title}</h3>
              <p className="step__body">{step.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
