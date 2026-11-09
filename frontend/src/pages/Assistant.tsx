import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AnswerText, Citations, FeedbackButtons } from "../components/Answer";
import {
  AttachIcon,
  AttachmentView,
  FILE_TYPES,
  MAX_FILE_BYTES,
  MAX_FILES,
  canRecord,
  formatSize,
  useVoiceNote,
} from "../components/Attachments";
import { Button, ErrorNote, inputClass } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import type { Answer, AttachmentInfo, ChatAnswer, Citation, Conversation, ConversationDetail } from "../lib/types";

type Shown = AttachmentInfo & { localUrl?: string };

interface Turn {
  role: string;
  content: string;
  citations: Citation[];
  insufficient?: boolean;
  answer?: Answer;
  attachments?: Shown[];
}

interface Pending {
  key: string;
  name: string;
  size: number;
  status: "uploading" | "ready" | "failed";
  info?: AttachmentInfo;
  localUrl?: string;
  error?: string;
}

const iconButton =
  "inline-flex size-9 shrink-0 items-center justify-center rounded-md text-ink-2 hover:bg-sunken hover:text-ink disabled:cursor-not-allowed disabled:opacity-40";
// A separate set, so no grey hover colour can win over the red while recording.
const recordingButton = "inline-flex size-9 shrink-0 items-center justify-center rounded-md bg-[var(--critical)] text-white";

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<Pending[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const localUrls = useRef<string[]>([]);
  useEffect(() => () => localUrls.current.forEach((url) => URL.revokeObjectURL(url)), []);

  function addFiles(files: File[]) {
    for (const file of files.slice(0, Math.max(0, MAX_FILES - pending.length))) {
      const key = `${file.name}-${file.size}-${Math.random()}`;
      const showable = file.type.startsWith("image/") || file.type.startsWith("audio/");
      const localUrl = showable ? URL.createObjectURL(file) : undefined;
      if (localUrl) localUrls.current.push(localUrl);
      const base = { key, name: file.name, size: file.size, localUrl };
      if (file.size > MAX_FILE_BYTES) {
        setPending((items) => [...items, { ...base, status: "failed", error: "Files can be up to 5 MB" }]);
        continue;
      }
      setPending((items) => [...items, { ...base, status: "uploading" }]);
      uploadFile<AttachmentInfo>("/ai/attachments", file, file.name)
        .then((info) => setPending((items) => items.map((item) => (item.key === key ? { ...item, status: "ready", info } : item))))
        .catch((error: unknown) =>
          setPending((items) =>
            items.map((item) =>
              item.key === key ? { ...item, status: "failed", error: error instanceof Error ? error.message : "Upload failed" } : item,
            ),
          ),
        );
    }
  }

  const voice = useVoiceNote(
    (words) => setMessage((current) => (current ? `${current} ${words}` : words)),
    (file) => addFiles([file]),
  );
  const uploading = pending.some((item) => item.status === "uploading");
  const full = pending.length >= MAX_FILES;
  const conversations = useQuery({ queryKey: ["conversations"], queryFn: () => api.get<Conversation[]>("/ai/conversations") });

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns]);

  async function open(id: number) {
    const detail = await api.get<ConversationDetail>(`/ai/conversations/${id}`);
    setConversationId(id);
    setTurns(
      detail.messages.map((item) => ({
        role: item.role,
        content: item.content,
        citations: item.citations,
        insufficient: item.insufficient_evidence,
        attachments: item.attachments,
      })),
    );
  }

  const send = useMutation({
    mutationFn: ({ text, files }: { text: string; files: Shown[] }) =>
      api.post<ChatAnswer>("/ai/chat", { message: text, conversation_id: conversationId, attachment_ids: files.map((item) => item.id) }),
    onMutate: ({ text, files }) => {
      setTurns((current) => [...current, { role: "user", content: text, citations: [], attachments: files }]);
      setMessage("");
      setPending([]);
    },
    onSuccess: (answer) => {
      setConversationId(answer.conversation_id);
      setTurns((current) => [
        ...current,
        { role: "assistant", content: answer.answer, citations: answer.citations, insufficient: answer.insufficient_evidence, answer },
      ]);
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!message.trim() || uploading) return;
    const files = pending.flatMap((item) => (item.status === "ready" && item.info ? [{ ...item.info, localUrl: item.localUrl }] : []));
    send.mutate({ text: message.trim(), files });
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
      <aside className="space-y-1">
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => {
            setConversationId(null);
            setTurns([]);
          }}
        >
          New conversation
        </Button>
        <ul className="mt-2 hidden max-h-[70vh] space-y-0.5 overflow-auto lg:block">
          {conversations.data?.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => void open(item.id)}
                className={`block w-full truncate rounded-md px-2 py-1.5 text-left text-sm ${item.id === conversationId ? "bg-accent-soft text-ink" : "text-ink-2 hover:bg-sunken"}`}
              >
                {item.title}
              </button>
            </li>
          ))}
        </ul>
      </aside>

      <div className="flex min-h-[70vh] min-w-0 flex-col rounded-lg border border-line bg-surface">
        <div className="flex-1 space-y-4 overflow-auto p-4" aria-live="polite">
          {turns.length === 0 && (
            <div className="py-12 text-center">
              <h1 className="text-lg font-semibold text-ink">Support assistant</h1>
              <p className="mx-auto mt-1 max-w-md text-sm text-ink-3">
                Answers come only from documents you are allowed to read, and each one cites its sources. If the evidence is not there, it says so.
              </p>
            </div>
          )}
          {turns.map((turn, index) =>
            turn.role === "user" ? (
              <div key={index} className="ml-auto max-w-[85%] w-fit space-y-2 rounded-lg bg-accent-soft px-3 py-2 text-sm text-ink">
                <p>{turn.content}</p>
                {!!turn.attachments?.length && (
                  <div className="flex flex-wrap gap-2">
                    {turn.attachments.map((item) => (
                      <AttachmentView key={item.id} item={item} localUrl={item.localUrl} />
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <div key={index} className="max-w-[92%] space-y-2">
                {turn.insufficient ? (
                  <p className="rounded-md border border-line px-3 py-2 text-sm text-ink-2">{turn.content}</p>
                ) : (
                  <AnswerText text={turn.content} citations={turn.citations} />
                )}
                <Citations citations={turn.citations} />
                {turn.answer && turn.answer.related_incidents.length > 0 && (
                  <p className="text-sm text-ink-2">
                    Related:{" "}
                    {turn.answer.related_incidents.map((item, position) => (
                      <span key={item.source_ref}>
                        {position > 0 && ", "}
                        <Link to={`/incidents/${item.incident_id}`} className="hover:underline">
                          {item.source_ref}
                        </Link>
                      </span>
                    ))}
                  </p>
                )}
                {turn.answer && turn.answer.suggested_actions.length > 0 && (
                  <p className="text-sm text-ink-2">
                    Possible next action: {turn.answer.suggested_actions.map((action) => action.name).join(", ")}. Requires approval.
                  </p>
                )}
                {turn.answer && <FeedbackButtons recommendationId={turn.answer.recommendation_id} />}
              </div>
            ),
          )}
          {send.isPending && <p className="text-sm text-ink-3">Searching the knowledge base…</p>}
          <ErrorNote error={send.error} />
          <div ref={endRef} />
        </div>
        <form onSubmit={submit} className="space-y-2 border-t border-line p-3">
          {pending.length > 0 && (
            <ul aria-label="Files to send" className="flex flex-wrap gap-2">
              {pending.map((item) => (
                <li key={item.key} className="flex max-w-full items-center gap-1.5 rounded-md border border-line bg-sunken px-2 py-1 text-xs text-ink-2">
                  <AttachIcon name="file" />
                  <span className="max-w-40 truncate">{item.name}</span>
                  <span className="tabular text-ink-3">
                    {item.status === "uploading" ? "Uploading…" : item.status === "failed" ? item.error : formatSize(item.size)}
                  </span>
                  <button
                    type="button"
                    aria-label={`Remove ${item.name}`}
                    className="rounded px-1 text-ink-3 hover:text-ink"
                    onClick={() => setPending((items) => items.filter((entry) => entry.key !== item.key))}
                  >
                    ×
                  </button>
                </li>
              ))}
            </ul>
          )}
          {voice.recording && (
            <p role="status" className="flex items-center gap-2 text-sm text-ink">
              <span aria-hidden className="size-2.5 animate-pulse rounded-full bg-[var(--critical)]" />
              Recording {Math.floor(voice.seconds / 60)}:{String(voice.seconds % 60).padStart(2, "0")}
              {voice.transcribes ? ". Your words appear in the message box." : "."}
            </p>
          )}
          {voice.error && (
            <p role="alert" className="text-sm text-[var(--critical)]">
              {voice.error}
            </p>
          )}
          <div className="flex items-center gap-1">
            <input
              ref={fileInput}
              type="file"
              name="attachment"
              accept={FILE_TYPES}
              multiple
              hidden
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            <input
              ref={photoInput}
              type="file"
              name="photo"
              accept="image/*"
              capture="environment"
              hidden
              onChange={(e) => {
                addFiles(Array.from(e.target.files ?? []));
                e.target.value = "";
              }}
            />
            <button type="button" className={iconButton} aria-label="Attach a file" title="Attach a file" disabled={full} onClick={() => fileInput.current?.click()}>
              <AttachIcon name="clip" />
            </button>
            <button type="button" className={iconButton} aria-label="Add a photo" title="Add a photo" disabled={full} onClick={() => photoInput.current?.click()}>
              <AttachIcon name="camera" />
            </button>
            <button
              type="button"
              className={voice.recording ? recordingButton : iconButton}
              aria-label={voice.recording ? "Stop recording" : "Record a voice note"}
              aria-pressed={voice.recording}
              title={canRecord() ? (voice.recording ? "Stop recording" : "Record a voice note") : "This browser cannot record audio"}
              disabled={!canRecord() || (full && !voice.recording)}
              onClick={() => (voice.recording ? voice.stop() : voice.start())}
            >
              <AttachIcon name={voice.recording ? "stop" : "mic"} />
            </button>
            <input aria-label="Message" className={inputClass} placeholder="Describe the problem" maxLength={2000} value={message} onChange={(e) => setMessage(e.target.value)} />
            <Button type="submit" disabled={!message.trim() || send.isPending || uploading}>
              Send
            </Button>
          </div>
          <p className="text-xs text-ink-3">
            The assistant reads text and log files. Photos and voice notes are saved with the conversation, but it cannot understand them yet. Up to {MAX_FILES} files of 5 MB each.
          </p>
        </form>
      </div>
    </div>
  );
}
