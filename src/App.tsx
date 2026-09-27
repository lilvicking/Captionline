import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Footer } from "./components/Footer";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { Nav } from "./components/Nav";
import { Pricing } from "./components/Pricing";
import { ProcessingState, type TranscriptionJob } from "./components/ProcessingState";
import { Editor } from "./components/editor/Editor";
import { AccountPanel } from "./auth/AccountPanel";
import { isUnauthorized, useAuth } from "./auth/AuthContext";
import { ResetPasswordPage } from "./auth/ResetPasswordPage";
import {
  CONTACT_PATH,
  HOME_PATH,
  navigateTo,
  PRIVACY_PATH,
  RESET_PASSWORD_PATH,
  TERMS_PATH,
  usePathname,
} from "./auth/route";
import { ContactPage } from "./legal/ContactPage";
import { PrivacyPage } from "./legal/PrivacyPage";
import { TermsPage } from "./legal/TermsPage";
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
  const { status: authStatus, refresh: refreshAccount, expireSession } = useAuth();
  const pathname = usePathname();

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

        // A rejected token is dead. Leave the signed-in UI behind instead of
        // leaving the user to retry a session the server has already ended.
        if (isUnauthorized(error)) {
          expireSession();
        }

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
  }, [pendingFile, openEditor, refreshAccount, expireSession]);

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
  const closeAccount = useCallback(() => setIsAccountOpen(false), []);

  const scrollToPricing = useCallback(() => {
    document.getElementById("pricing")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, []);

  /**
   * Opens the pricing plans.
   *
   * The pricing section only exists on the landing page, so from the processing
   * or editor stage this returns home first, the same reset the "New video"
   * control performs, and scrolls once the section is on screen.
   */
  const showPlans = useCallback(() => {
    if (stage !== "landing") {
      handleReset();
      window.setTimeout(scrollToPricing, 80);
      return;
    }

    scrollToPricing();
  }, [stage, handleReset, scrollToPricing]);

  // A secondary page has no sections to scroll to, so the nav links point back
  // at the landing page and the upload button comes home first.
  const startUpload = useCallback(() => {
    if (pathname !== HOME_PATH) {
      navigateTo(HOME_PATH);
      // The landing mounts on the next render; scroll once it exists.
      window.setTimeout(focusUploadZone, 80);
      return;
    }

    focusUploadZone();
  }, [pathname, focusUploadZone]);

  const accountSheet = isAccountOpen ? <AccountPanel onClose={closeAccount} /> : null;

  /**
   * Chrome shared by the legal and not-found pages: the same nav and footer the
   * landing page uses, with section links pointed back at the landing anchors.
   */
  const secondaryPage = (children: ReactNode) => (
    <div className="app">
      <a className="skip" href="#main">
        Skip to content
      </a>

      <Nav onStartUpload={startUpload} onOpenAccount={openAccount} sectionBase={HOME_PATH} />

      <main id="main" tabIndex={-1}>
        {children}
      </main>

      <Footer />

      {accountSheet}
    </div>
  );

  // The password reset link arrives by email and must survive a full page load,
  // so it gets a real URL rather than living inside the app's state machine.
  if (pathname === RESET_PASSWORD_PATH) {
    return (
      <div className="app">
        <ResetPasswordPage />
      </div>
    );
  }

  if (pathname === TERMS_PATH) {
    return secondaryPage(<TermsPage />);
  }

  if (pathname === PRIVACY_PATH) {
    return secondaryPage(<PrivacyPage />);
  }

  if (pathname === CONTACT_PATH) {
    return secondaryPage(<ContactPage />);
  }

  // An unknown path must not fall through to the landing page: the URL would
  // then be wrong while the page looked right, which is worse than saying so.
  if (pathname !== HOME_PATH) {
    return secondaryPage(<NotFoundPage pathname={pathname} />);
  }

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
          onShowPlans={showPlans}
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

      {accountSheet}
    </div>
  );
}

/**
 * Shown for a URL that is not one Captionline serves.
 *
 * Kept deliberately small: it names the path that failed, and offers the two
 * places worth going next. Going home also repairs the URL, so the user is never
 * left staring at a wrong address with a correct-looking page.
 */
function NotFoundPage({ pathname }: { pathname: string }) {
  return (
    <section className="notfound">
      <div className="notfound__inner">
        <p className="eyebrow">Page not found</p>
        <h1 className="notfound__title">There is nothing at this address</h1>
        <p className="notfound__body">
          <code>{pathname}</code> is not a page on Captionline. The link may be old or mistyped.
        </p>

        <div className="notfound__actions">
          <button
            className="button button--primary"
            type="button"
            onClick={() => navigateTo(HOME_PATH)}
          >
            Go to Captionline
          </button>
          <a
            className="button button--ghost"
            href={CONTACT_PATH}
            onClick={(event) => {
              if (event.metaKey || event.ctrlKey || event.shiftKey) {
                return;
              }

              event.preventDefault();
              navigateTo(CONTACT_PATH);
            }}
          >
            Contact support
          </a>
        </div>
      </div>
    </section>
  );
}
