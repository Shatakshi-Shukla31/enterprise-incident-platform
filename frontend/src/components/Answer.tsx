import { Fragment, useState } from "react";
import { api } from "../lib/api";
import type { Citation } from "../lib/types";
import { Button } from "./ui";

/** Answer text is rendered as plain text, never as HTML, because it derives from documents. */
export function AnswerText({ text, citations }: { text: string; citations: Citation[] }) {
  const known = new Map(citations.map((citation) => [citation.id, citation]));
  return (
    <div className="space-y-1 whitespace-pre-wrap text-sm text-ink">
      {text.split(/(\[S\d+\])/).map((part, index) => {
        const citation = known.get(part.slice(1, -1));
        return citation ? (
          <a key={index} href={`#${citation.id}`} title={citation.title} className="tabular rounded bg-accent-soft px-1 text-xs font-medium text-ink no-underline hover:underline">
            {citation.id}
          </a>
        ) : (
          <Fragment key={index}>{part}</Fragment>
        );
      })}
    </div>
  );
}

export function Citations({ citations }: { citations: Citation[] }) {
  if (!citations.length) return null;
  return (
    <ol className="mt-3 space-y-2 border-t border-line pt-3">
      {citations.map((citation) => (
        <li key={citation.id} id={citation.id} className="text-sm">
          <p className="text-ink">
            <span className="tabular mr-1.5 rounded bg-accent-soft px-1 text-xs font-medium">{citation.id}</span>
            {citation.title}
          </p>
          <p className="tabular text-xs text-ink-3">
            {citation.source_ref} · {citation.source_type === "kb_article" ? "Knowledge article" : "Resolved incident"} · similarity {citation.similarity.toFixed(2)}
          </p>
          <p className="mt-0.5 line-clamp-2 text-xs text-ink-2">{citation.excerpt}</p>
        </li>
      ))}
    </ol>
  );
}

export function FeedbackButtons({ recommendationId }: { recommendationId: number }) {
  const [sent, setSent] = useState<boolean | null>(null);
  async function send(helpful: boolean) {
    await api.post(`/ai/recommendations/${recommendationId}/feedback`, { helpful });
    setSent(helpful);
  }
  if (sent !== null) return <p className="text-xs text-ink-3">Thanks for the feedback.</p>;
  return (
    <div className="flex items-center gap-1 text-xs text-ink-3">
      Was this useful?
      <Button variant="ghost" className="!px-2 !py-0.5 text-xs" onClick={() => void send(true)}>
        Yes
      </Button>
      <Button variant="ghost" className="!px-2 !py-0.5 text-xs" onClick={() => void send(false)}>
        No
      </Button>
    </div>
  );
}
