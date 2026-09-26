import { useCallback, useEffect, useRef, useState } from "react";
import { Footer } from "./components/Footer";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { Nav } from "./components/Nav";
import { Pricing } from "./components/Pricing";
import { ProcessingState } from "./components/ProcessingState";
import { Editor } from "./components/editor/Editor";
import { createSampleCues } from "./data/sampleCaptions";
import type { CaptionCue } from "./types";

type Stage = "landing" | "processing" | "editor";

export function App() {
  const [stage, setStage] = useState<Stage>("landing");
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoName, setVideoName] = useState("");
  const [cues, setCues] = useState<CaptionCue[]>(createSampleCues);

  const objectUrlRef = useRef<string | null>(null);

  const releaseObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  useEffect(() => releaseObjectUrl, [releaseObjectUrl]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [stage]);

  const handleFile = useCallback(
    (file: File) => {
      releaseObjectUrl();

      const url = URL.createObjectURL(file);
      objectUrlRef.current = url;

      setVideoUrl(url);
      setVideoName(file.name);
      setCues(createSampleCues());
      setStage("processing");
    },
    [releaseObjectUrl],
  );

  const handleProcessingComplete = useCallback(() => {
    setStage("editor");
  }, []);

  const handleReset = useCallback(() => {
    releaseObjectUrl();
    setVideoUrl(null);
    setVideoName("");
    setCues(createSampleCues());
    setStage("landing");
  }, [releaseObjectUrl]);

  const focusUploadZone = useCallback(() => {
    document.getElementById("upload")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  if (stage === "processing") {
    return (
      <div className="app">
        <ProcessingState fileName={videoName} onComplete={handleProcessingComplete} />
      </div>
    );
  }

  if (stage === "editor" && videoUrl) {
    return (
      <div className="app">
        <Editor
          videoUrl={videoUrl}
          videoName={videoName}
          cues={cues}
          setCues={setCues}
          onReset={handleReset}
        />
      </div>
    );
  }

  return (
    <div className="app">
      <Nav onStartUpload={focusUploadZone} />

      <main>
        <div id="upload">
          <Hero onFile={handleFile} />
        </div>
        <HowItWorks />
        <Pricing />
      </main>

      <Footer />
    </div>
  );
}
