import { useEffect, useRef, useState } from "react";
import { fetchBlob } from "../lib/api";
import type { AttachmentInfo } from "../lib/types";

export const MAX_FILE_BYTES = 5 * 1024 * 1024;
export const MAX_FILES = 3;
export const TEXT_FILE_TYPES = ".txt,.log,.csv,.json,.md,.xml,.yaml,.yml,.ini,.conf,.cfg";
export const FILE_TYPES = `image/*,audio/*,video/mp4,video/webm,video/ogg,.avi,.pdf,${TEXT_FILE_TYPES}`;

export const ATTACHMENT_OPTIONS = [
  { name: "image", label: "Image", accept: "image/png,image/jpeg,image/gif,image/webp", icon: "image" },
  { name: "audio", label: "Audio", accept: "audio/mpeg,audio/wav,audio/ogg,audio/webm,audio/mp4,.m4a", icon: "mic" },
  { name: "video", label: "Video", accept: "video/mp4,video/webm,video/ogg,.avi", icon: "video" },
  { name: "pdf", label: "PDF", accept: ".pdf,application/pdf", icon: "file" },
] as const;

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const PATHS = {
  clip: "M21 11l-8.5 8.5a5 5 0 0 1-7-7L14 4a3.5 3.5 0 0 1 5 5l-8.5 8.5a2 2 0 0 1-3-3L15 7",
  camera: "M3 8a2 2 0 0 1 2-2h2l2-2h6l2 2h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 17a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
  mic: "M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM19 11a7 7 0 0 1-14 0M12 18v3",
  stop: "M7 7h10v10H7z",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  image: "M4 3h16a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM3 16l5-5 5 5 3-3 5 5M16 8h.01",
  video: "M3 5h12v14H3zM15 10l6-4v12l-6-4",
};

export function AttachIcon({ name }: { name: keyof typeof PATHS }) {
  return (
    <svg aria-hidden width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d={PATHS[name]} />
    </svg>
  );
}

/** A private file is fetched with the session token and shown from memory, because an
 * media tags cannot send the token themselves. */
function useFileUrl(id: number | null, localUrl?: string): string | null {
  const [url, setUrl] = useState<string | null>(localUrl ?? null);
  useEffect(() => {
    if (localUrl || id === null) return;
    let cancelled = false;
    let created: string | null = null;
    fetchBlob(`/ai/attachments/${id}`)
      .then((blob) => {
        if (cancelled) return;
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch(() => setUrl(null));
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [id, localUrl]);
  return url;
}

async function download(item: AttachmentInfo) {
  const url = URL.createObjectURL(await fetchBlob(`/ai/attachments/${item.id}`));
  const link = document.createElement("a");
  link.href = url;
  link.download = item.filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function AttachmentView({ item, localUrl }: { item: AttachmentInfo; localUrl?: string }) {
  const playable = item.kind === "image" || item.kind === "audio" || item.kind === "video";
  const url = useFileUrl(playable ? item.id : null, localUrl);
  if (item.kind === "image" && url) {
    return <img src={url} alt={item.filename} className="max-h-48 max-w-full rounded-md border border-line" />;
  }
  if (item.kind === "audio" && url) {
    return <audio controls src={url} aria-label={`Voice note ${item.filename}`} className="h-10 w-64 max-w-full" />;
  }
  if (item.kind === "video" && url) {
    return <video controls preload="metadata" src={url} aria-label={`Video ${item.filename}`} className="max-h-64 max-w-full rounded-md border border-line" />;
  }
  return (
    <button
      type="button"
      onClick={() => void download(item)}
      className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-line bg-surface px-2 py-1 text-xs text-ink-2 hover:bg-sunken"
    >
      <AttachIcon name="file" />
      <span className="truncate">{item.filename}</span>
      <span className="tabular text-ink-3">{formatSize(item.size_bytes)}</span>
    </button>
  );
}

interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<{ isFinal: boolean; 0: { transcript: string } }> }) => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type RecognitionClass = new () => Recognition;

function speechRecognition(): RecognitionClass | undefined {
  const source = window as unknown as { SpeechRecognition?: RecognitionClass; webkitSpeechRecognition?: RecognitionClass };
  return source.SpeechRecognition ?? source.webkitSpeechRecognition;
}

export const canRecord = () => typeof window !== "undefined" && "MediaRecorder" in window && !!navigator.mediaDevices?.getUserMedia;

const MAX_RECORDING_SECONDS = 120;

/** Records a voice note. Where the browser can turn speech into text, the words are typed
 * into the message as well, which is the part the assistant can actually use. */
export function useVoiceNote(onTranscript: (text: string) => void, onRecorded: (file: File) => void) {
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const stopRef = useRef<() => void>(() => {});

  useEffect(() => () => stopRef.current(), []);

  async function start() {
    setError(null);
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone access was blocked. Allow it in your browser to record a voice note.");
      return;
    }
    const recorder = new MediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      const type = recorder.mimeType || "audio/webm";
      const extension = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "m4a" : "webm";
      const stamp = new Date().toTimeString().slice(0, 5).replace(":", "");
      onRecorded(new File(chunks, `voice-note-${stamp}.${extension}`, { type }));
    };

    const Speech = speechRecognition();
    const words = Speech ? new Speech() : null;
    if (words) {
      words.lang = navigator.language || "en-US";
      words.continuous = true;
      words.interimResults = false;
      words.onresult = (event) => {
        for (let index = event.resultIndex; index < event.results.length; index += 1) {
          if (event.results[index].isFinal) onTranscript(event.results[index][0].transcript.trim());
        }
      };
      words.onerror = () => {};
      words.start();
    }

    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    const limit = window.setTimeout(() => stopRef.current(), MAX_RECORDING_SECONDS * 1000);
    stopRef.current = () => {
      window.clearInterval(timer);
      window.clearTimeout(limit);
      words?.stop();
      if (recorder.state !== "inactive") recorder.stop();
      setRecording(false);
      stopRef.current = () => {};
    };
    setSeconds(0);
    recorder.start();
    setRecording(true);
  }

  return { recording, seconds, error, start: () => void start(), stop: () => stopRef.current(), transcribes: !!speechRecognition() };
}
