import { useCallback, useEffect, useRef, useState } from "react";
import { Footer } from "./components/Footer";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { Nav } from "./components/Nav";
import { Pricing } from "./components/Pricing";
import { ProcessingState, type TranscriptionJob } from "./components/ProcessingState";
import { Editor } from "./components/editor/Editor";
import { AccountPanel } from "./auth/AccountPanel";
import { useAuth } from "./auth/AuthContext";
import { createSampleCues } from "./data/sampleCaptions";
import { TranscriptionError, failureReasonFor, segmentsToCues, transcribeFile } from "./lib/api";
import { getStoredToken } from "./lib/auth";
import type { CaptionCue } from "./types";

type Stage = "landing" | "processing" | "editor";

export type CaptionSource = "whisperx" | "sample";

export type TranscriptionMeta = {
  source: CaptionSource;
  language?: string;
  wordAligned: boolean;
  model?: string;
  device?: string;
  /** Set when transcription failed and sample captions were used instead. */
  error?: string;
};

export function App() {
  const [stage, setStage] = useState<Stage>("landing");
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [videoName, setVideoName] = useState("");
  const [cues, setCues] = useState<CaptionCue[]>(createSampleCues);
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [job, setJob] = useState<TranscriptionJob | null>(null);
  const [meta, setMeta] = useState<TranscriptionMeta>({ source: "sample", wordAligned: false });
  const [isAccountOpen, setIsAccountOpen] = useState(false);

  const objectUrlRef = useRef<string | null>(null);
  const { status: authStatus, refresh: refreshAccount } = useAuth();

  const isAuthenticated = authStatus === "authenticated";

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

  const openEditor = useCallback(() => {
    setPendingFile(null);
    setStage("editor");
  }, []);

  // Runs the transcription for the most recently selected file.
  useEffect(() => {
    if (!pendingFile) {
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    setJob({ phase: "uploading", message: "Sending the file to the transcription service" });

    // fetch cannot report upload progress, so move the label on once the request
    // is in flight rather than inventing a percentage.
    const transcribingTimer = window.setTimeout(() => {
      if (!cancelled) {
        setJob({
          phase: "transcribing",
          message: "Transcribing with WhisperX and aligning words",
        });
      }
    }, 1200);

    transcribeFile(pendingFile, getStoredToken(), controller.signal)
      .then((result) => {
        if (cancelled) {
          return;
        }

        const transcribed = segmentsToCues(result.segments);

        if (transcribed.length > 0) {
          setCues(transcribed);
          setMeta({
            source: "whisperx",
            language: result.language,
            wordAligned: transcribed.some((cue) => (cue.words?.length ?? 0) > 0),
            model: result.model,
            device: result.device,
          });
        } else {
          // No speech found: keep the editor usable with sample captions.
          setCues(createSampleCues());
          setMeta({
            source: "sample",
            wordAligned: false,
            model: result.model,
            device: result.device,
            error: "No speech was detected in this file, so sample captions are shown.",
          });
        }

        // Processing time was just spent, so pull the fresh usage numbers.
        void refreshAccount();

        openEditor();
      })
      .catch((error: unknown) => {
        if (cancelled || (error instanceof DOMException && error.name === "AbortError")) {
          return;
        }

        const reason =
          error instanceof TranscriptionError ? failureReasonFor(error.status) : "failed";

        const message =
          error instanceof Error ? error.message : "Transcription failed for an unknown reason.";

        setCues(createSampleCues());
        setMeta({ source: "sample", wordAligned: false, error: message });
        setJob({ phase: "error", message, detail: message, reason });
      })
      .finally(() => {
        window.clearTimeout(transcribingTimer);
      });

    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(transcribingTimer);
    };
  }, [pendingFile, openEditor, refreshAccount]);

  const handleFile = useCallback(
    (file: File) => {
      releaseObjectUrl();

      const url = URL.createObjectURL(file);
      objectUrlRef.current = url;

      setVideoUrl(url);
      setVideoName(file.name);
      setStage("processing");
      setJob({ phase: "uploading", message: "Preparing your workspace" });
      setMeta({ source: "sample", wordAligned: false });
      setPendingFile(file);
    },
    [releaseObjectUrl],
  );

  const handleReset = useCallback(() => {
    releaseObjectUrl();
    setVideoUrl(null);
    setVideoName("");
    setPendingFile(null);
    setJob(null);
    setCues(createSampleCues());
    setMeta({ source: "sample", wordAligned: false });
    setStage("landing");
  }, [releaseObjectUrl]);

  const focusUploadZone = useCallback(() => {
    document.getElementById("upload")?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  const openAccount = useCallback(() => setIsAccountOpen(true), []);

  const showPlans = useCallback(() => {
    document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  if (stage === "processing") {
    return (
      <div className="app">
        <ProcessingState
          fileName={videoName}
          job={job}
          onContinue={openEditor}
          onSignIn={openAccount}
          onViewPlans={showPlans}
        />
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
          transcription={meta}
          onReset={handleReset}
        />
      </div>
    );
  }

  return (
    <div className="app">
      <Nav onStartUpload={focusUploadZone} onOpenAccount={openAccount} />

      <main>
        <div id="upload">
          <Hero onFile={handleFile} isAuthenticated={isAuthenticated} onRequestSignIn={openAccount} />
        </div>
        <HowItWorks />
        <Pricing />
      </main>

      <Footer />

      {isAccountOpen ? <AccountPanel onClose={() => setIsAccountOpen(false)} /> : null}
    </div>
  );
}
