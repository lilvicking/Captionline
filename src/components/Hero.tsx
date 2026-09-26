import { Gauge, Lock, Wand2 } from "lucide-react";
import { UploadZone } from "./UploadZone";

type HeroProps = {
  onFile: (file: File) => void;
};

const POINTS = [
  { icon: Wand2, text: "Timed captions generated in seconds" },
  { icon: Gauge, text: "Style, reposition, and export without re-rendering" },
  { icon: Lock, text: "Your footage stays on your machine in Phase 1" },
];

export function Hero({ onFile }: HeroProps) {
  return (
    <section className="hero" id="top">
      <div className="hero__inner">
        <p className="eyebrow">Video captioning</p>

        <h1 className="hero__title">
          Captions that look like <span className="hero__accent">you made them.</span>
        </h1>

        <p className="hero__subtitle">
          Upload a clip, get a timed caption track, rewrite the wording, and export a subtitle file
          your platform accepts. No manual keyframes, no heavyweight editor.
        </p>

        <ul className="hero__points">
          {POINTS.map((point) => (
            <li key={point.text}>
              <point.icon size={18} aria-hidden="true" />
              {point.text}
            </li>
          ))}
        </ul>

        <UploadZone onFile={onFile} />
      </div>
    </section>
  );
}
