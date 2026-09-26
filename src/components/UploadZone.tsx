import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { AlertCircle, FileVideo, Upload } from "lucide-react";

type UploadZoneProps = {
  onFile: (file: File) => void;
  /** Transcription requires an account, so the gate is shown while signed out. */
  isAuthenticated: boolean;
  onRequestSignIn: () => void;
};

const ACCEPTED_TYPES = "video/*";

export function UploadZone({
  onFile,
  isAuthenticated,
  onRequestSignIn,
}: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // A signed-out visitor is asked to create an account rather than allowed to
  // pick a file that the server would reject anyway.
  const requestSignIn = () => {
    setError(null);
    onRequestSignIn();
  };

  const accept = (file: File | undefined) => {
    if (!file) {
      return;
    }

    if (!file.type.startsWith("video/")) {
      setError(`"${file.name}" is not a video file. Choose a video such as MP4, MOV, or WebM.`);
      return;
    }

    if (!isAuthenticated) {
      requestSignIn();
      return;
    }

    setError(null);
    onFile(file);
  };

  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    accept(event.target.files?.[0]);
    event.target.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
    accept(event.dataTransfer.files?.[0]);
  };

  return (
    <div className="upload">
      <div
        className={`dropzone${isDragging ? " is-dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={handleDrop}
      >
        <span className="dropzone__icon" aria-hidden="true">
          {isDragging ? <FileVideo size={26} /> : <Upload size={26} />}
        </span>

        <p className="dropzone__title">
          {isDragging
            ? "Drop it here"
            : isAuthenticated
              ? "Drag a video here, or choose a file"
              : "Create a free account to start transcribing"}
        </p>
        <p className="dropzone__hint">
          {isAuthenticated
            ? "Your file is sent to Captionline for transcription and deleted straight after. Nothing is stored."
            : "Free accounts include 10 processing minutes a month and a 30-second finished preview."}
        </p>

        <button
          className="button button--primary"
          type="button"
          onClick={() => {
            if (isAuthenticated) {
              inputRef.current?.click();
            } else {
              requestSignIn();
            }
          }}
        >
          {isAuthenticated ? (
            <>
              <Upload size={16} aria-hidden="true" />
              Choose video
            </>
          ) : (
            "Create a free account"
          )}
        </button>

        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept={ACCEPTED_TYPES}
          onChange={handleChange}
        />
      </div>

      {error ? (
        <p className="upload__error" role="alert">
          <AlertCircle size={16} aria-hidden="true" />
          {error}
        </p>
      ) : null}
    </div>
  );
}
