import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent } from "react";
import { AlertCircle, FileVideo, Upload } from "lucide-react";

type UploadZoneProps = {
  onFile: (file: File) => void;
};

const ACCEPTED_TYPES = "video/*";

export function UploadZone({ onFile }: UploadZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = (file: File | undefined) => {
    if (!file) {
      return;
    }

    if (!file.type.startsWith("video/")) {
      setError(`"${file.name}" is not a video file. Choose a video such as MP4, MOV, or WebM.`);
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
          {isDragging ? "Drop it here" : "Drag a video here, or choose a file"}
        </p>
        <p className="dropzone__hint">
          Your file is sent to Captionline for transcription and deleted straight after. Nothing is
          stored.
        </p>

        <button
          className="button button--primary"
          type="button"
          onClick={() => inputRef.current?.click()}
        >
          <Upload size={16} aria-hidden="true" />
          Choose video
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
