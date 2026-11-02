import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { AnswerText, Citations, FeedbackButtons } from "../components/Answer";
import { Button, ErrorNote, inputClass } from "../components/ui";
import { api } from "../lib/api";
import type { Answer, ChatAnswer, Citation, Conversation, ConversationDetail } from "../lib/types";

interface Turn {
  role: string;
  content: string;
  citations: Citation[];
  insufficient?: boolean;
  answer?: Answer;
}

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [message, setMessage] = useState("");
  const endRef = useRef<HTMLDivElement>(null);
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
      })),
    );
  }

  const send = useMutation({
    mutationFn: (text: string) => api.post<ChatAnswer>("/ai/chat", { message: text, conversation_id: conversationId }),
    onMutate: (text) => {
      setTurns((current) => [...current, { role: "user", content: text, citations: [] }]);
      setMessage("");
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
    if (message.trim()) send.mutate(message.trim());
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
              <div key={index} className="ml-auto max-w-[85%] w-fit rounded-lg bg-accent-soft px-3 py-2 text-sm text-ink">
                {turn.content}
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
        <form onSubmit={submit} className="flex gap-2 border-t border-line p-3">
          <input aria-label="Message" className={inputClass} placeholder="Describe the problem" maxLength={2000} value={message} onChange={(e) => setMessage(e.target.value)} />
          <Button type="submit" disabled={!message.trim() || send.isPending}>
            Send
          </Button>
        </form>
      </div>
    </div>
  );
}
