import { useEffect, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, Download, Film, Loader2, Sparkles } from "lucide-react";
import { useAuth } from "../../auth/AuthContext";
import { downloadSrt, srtFileName } from "../../lib/srt";
import { exportCaptionedVideo } from "../../lib/export";
import { getStoredToken } from "../../lib/auth";
import type { CaptionCue, CaptionStyle } from "../../types";

type ExportPanelProps = {
  cues: CaptionCue[];
  videoName: string;
  style: CaptionStyle;
  /**
   * The original upload, held for the length of the editing session.
   *
   * Rendering needs the untouched source; the server only ever saw it
   * transiently, so this is what makes export possible without building
   * permanent video storage.
   */
  sourceFile: File | null;
  /** Opens the pricing plans, which live outside the editor stage. */
  onShowPlans: () => void;
  /** Opens the existing account sheet. */
  onRequestSignIn: () => void;
};

type ExportState =
  | { kind: "idle" }
  | { kind: "working"; label: string }
  | { kind: "done"; filename: string }
  | { kind: "error"; message: string };

export function ExportPanel({
  cues,
  videoName,
  style,
  sourceFile,
  onShowPlans,
  onRequestSignIn,
}: ExportPanelProps) {
  const { account, isPaidPlan, expireSession } = useAuth();
  const [state, setState] = useState<ExportState>({ kind: "idle" });
  const abortRef = useRef<AbortController | null>(null);

  // A render in flight must not outlive the component.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // Changing the video or the captions invalidates a previous result.
  useEffect(() => {
    setState({ kind: "idle" });
  }, [videoName, cues.length]);

  const fileName = `${srtFileName(videoName)}.srt`;

  // Entitlement is a commercial answer the server already computed. Every
  // current plan carries it, so Free is never blocked.
  const isEntitled = account?.can_export !== false;
  const isBusy = state.kind === "working";

  const handleExportVideo = async () => {
    if (!isEntitled) {
      onShowPlans();
      return;
    }

    const token = getStoredToken();

    if (!token) {
      onRequestSignIn();
      return;
    }

    if (!sourceFile) {
      setState({
        kind: "error",
        message:
          "The original video is no longer available in this tab. Re-upload it to export the finished video.",
      });
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;
    setState({ kind: "working", label: "Uploading your video" });

    try {
      const filename = await exportCaptionedVideo({
        videoFile: sourceFile,
        captions: cues,
        style,
        token,
        signal: controller.signal,
        onProgress: (progress) => setState({ kind: "working", label: progress.label }),
      });
      setState({ kind: "done", filename });
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return;
      }

      // A rejected token means the session is gone, so stop claiming otherwise.
      if (
        error instanceof Error &&
        "status" in error &&
        (error as { status?: number }).status === 401
      ) {
        expireSession();
        onRequestSignIn();
        return;
      }

      setState({
        kind: "error",
        message: error instanceof Error ? error.message : "The export could not be completed.",
      });
    } finally {
      abortRef.current = null;
    }
  };

  return (
    <section className="panel">
      <h2 className="panel__title">Export</h2>

      <button
        className="button button--primary button--block"
        type="button"
        onClick={() => downloadSrt(cues, videoName)}
        disabled={cues.length === 0 || isBusy}
      >
        <Download size={16} aria-hidden="true" />
        Export .SRT
      </button>
      <p className="panel__hint">Downloads {fileName} from the captions in this editor.</p>

      {!isEntitled ? (
        <>
          <button
            className="button button--ghost button--block"
            type="button"
            onClick={onShowPlans}
            disabled={isBusy}
          >
            <Sparkles size={16} aria-hidden="true" />
            See plans with video export
          </button>
          <p className="panel__hint">
            Finished-video export is not included with this plan. Subtitle (.srt) export above works
            on every plan.
          </p>
        </>
      ) : (
        <button
          className="button button--ghost button--block"
          type="button"
          onClick={() => void handleExportVideo()}
          disabled={isBusy || cues.length === 0}
        >
          {isBusy ? (
            <Loader2 size={16} className="pricing__spinner" aria-hidden="true" />
          ) : (
            <Film size={16} aria-hidden="true" />
          )}
          {isBusy ? "Rendering…" : "Export video"}
        </button>
      )}

      {isEntitled ? (
        <p className="panel__hint">
          Renders the finished video with your captions burned in, exactly as they appear in the
          preview. Rendering does not use any of your monthly processing minutes, so you can export
          again after changing the captions or the style.
        </p>
      ) : null}

      {state.kind === "working" ? (
        <p className="panel__note" role="status" aria-live="polite">
          <Loader2 size={15} className="pricing__spinner" aria-hidden="true" />
          <span>{state.label}…</span>
        </p>
      ) : null}

      {state.kind === "done" ? (
        <p className="panel__note panel__note--ok" role="status">
          <CheckCircle2 size={15} aria-hidden="true" />
          <span>
            Downloaded {state.filename}. Change the captions or style and export again whenever you
            like.
          </span>
        </p>
      ) : null}

      {state.kind === "error" ? (
        <p className="panel__note panel__note--error" role="alert">
          <AlertCircle size={15} aria-hidden="true" />
          <span>{state.message}</span>
        </p>
      ) : null}

      {!isPaidPlan && isEntitled ? (
        <p className="panel__hint">
          This is part of every plan, including Free. Paid plans simply include more processing
          minutes each month.
        </p>
      ) : null}
    </section>
  );
}
