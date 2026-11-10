import { useEffect, useId, useRef, useState } from "react";
import { ATTACHMENT_OPTIONS, AttachIcon, FILE_TYPES, canRecord } from "./Attachments";

const OPTIONS = [
  ...ATTACHMENT_OPTIONS.map((option) => ({
    ...option,
    description: {
      image: "Add a screenshot or photo",
      audio: "Upload an audio recording",
      video: "Share a video clip",
      pdf: "Attach a PDF document",
    }[option.name],
  })),
  { name: "attachment", label: "Files", accept: FILE_TYPES, icon: "clip", description: "Add text, logs, and other supported files" },
] as const;

interface Props {
  disabled: boolean;
  recording: boolean;
  onFiles: (files: File[]) => void;
  onRecord: () => void;
}

export function AttachmentMenu({ disabled, recording, onFiles, onRecord }: Props) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const recordingSupported = canRecord();

  function close() {
    setOpen(false);
    trigger.current?.focus();
  }

  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus();
    function onPointerDown(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
        trigger.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  function chooseFile(name: string) {
    close();
    inputs.current[name]?.click();
  }

  return (
    <div ref={root}>
      {OPTIONS.map((option) => (
        <input key={option.name} ref={(element) => { inputs.current[option.name] = element; }} type="file" name={option.name} accept={option.accept} multiple hidden onChange={(event) => {
          onFiles(Array.from(event.target.files ?? []));
          event.target.value = "";
        }} />
      ))}
      <input ref={(element) => { inputs.current.photo = element; }} type="file" name="photo" accept="image/*" capture="environment" hidden onChange={(event) => {
        onFiles(Array.from(event.target.files ?? []));
        event.target.value = "";
      }} />
      <button
        ref={trigger}
        type="button"
        aria-label="Add attachments"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        title="Add images, audio, video, PDFs, or files"
        disabled={disabled}
        className="inline-flex size-9 items-center justify-center rounded-full bg-sunken text-ink transition-colors hover:bg-accent-soft disabled:cursor-not-allowed disabled:opacity-40"
        onClick={() => setOpen((current) => !current)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <svg aria-hidden width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" className={`transition-transform ${open ? "rotate-45" : ""}`}>
          <path d="M12 5v14M5 12h14" />
        </svg>
      </button>
      {open && (
        <div
          ref={menu}
          id={menuId}
          role="menu"
          aria-label="Add to conversation"
          className="absolute inset-x-0 bottom-full z-30 mb-2 max-h-[min(28rem,60vh)] overflow-y-auto rounded-2xl border border-line bg-surface p-2 shadow-[0_8px_32px_rgba(0,0,0,0.12)]"
          onKeyDown={(event) => {
            if (!["ArrowDown", "ArrowUp", "Home", "End", "Tab"].includes(event.key)) return;
            if (event.key === "Tab") {
              close();
              return;
            }
            event.preventDefault();
            const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="menuitem"]:not(:disabled)'));
            const current = items.indexOf(document.activeElement as HTMLButtonElement);
            const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (current + (event.key === "ArrowUp" ? -1 : 1) + items.length) % items.length;
            items[next]?.focus();
          }}
        >
          <p className="px-3 py-1.5 text-xs text-ink-3">Add</p>
          {OPTIONS.map((option) => (
            <button key={option.name} type="button" role="menuitem" aria-label={option.label} disabled={disabled} onClick={() => chooseFile(option.name)} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-ink-2 hover:bg-sunken focus-visible:bg-sunken disabled:opacity-40">
              <AttachIcon name={option.icon} />
              <span className="min-w-0">
                <span className="block text-sm font-medium text-ink">{option.label}</span>
                <span className="block text-xs text-ink-3">{option.description}</span>
              </span>
            </button>
          ))}
          <div role="separator" className="mx-3 my-1 border-t border-line" />
          <button type="button" role="menuitem" aria-label="Add a photo" disabled={disabled} onClick={() => chooseFile("photo")} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-ink-2 hover:bg-sunken focus-visible:bg-sunken disabled:opacity-40">
            <AttachIcon name="camera" />Take a photo
          </button>
          <button type="button" role="menuitem" aria-label={recording ? "Stop recording" : "Record a voice note"} disabled={!recordingSupported || disabled} title={recordingSupported ? undefined : "This browser cannot record audio"} onClick={() => { close(); onRecord(); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-sm text-ink-2 hover:bg-sunken focus-visible:bg-sunken disabled:opacity-40">
            <AttachIcon name={recording ? "stop" : "mic"} />{recording ? "Stop recording" : "Record a voice note"}
          </button>
        </div>
      )}
    </div>
  );
}
