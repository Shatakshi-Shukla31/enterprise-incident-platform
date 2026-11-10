import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api } from "../lib/api";
import { Button, ErrorNote, inputClass } from "./ui";

interface Hit {
  chunk_id: number;
  title: string;
  source_ref: string;
  content: string;
}

export function AssistantKnowledge({ onAsk }: { onAsk: (question: string) => void }) {
  const [query, setQuery] = useState("");
  const search = useMutation({
    mutationFn: (text: string) => api.post<Hit[]>("/knowledge/search", { query: text, top_k: 5 }),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length > 1) search.mutate(query.trim());
  }

  return (
    <section aria-label="Assistant knowledge" className="space-y-3 pt-3">
      <p className="text-xs text-ink-3">Search articles you can access, then ask the assistant for help.</p>
      <form onSubmit={submit} className="space-y-2">
        <input aria-label="Search assistant knowledge" className={inputClass} placeholder="VPN, password, printer…" value={query} maxLength={2000} onChange={(event) => setQuery(event.target.value)} />
        <Button type="submit" variant="secondary" className="w-full" disabled={query.trim().length < 2 || search.isPending}>
          {search.isPending ? "Searching…" : "Search knowledge"}
        </Button>
      </form>
      <ErrorNote error={search.error} />
      <ul className="max-h-[55vh] space-y-2 overflow-auto">
        {search.data?.length === 0 && <li className="text-sm text-ink-3">No matching articles you can access. Try another symptom.</li>}
        {search.data?.map((hit) => (
          <li key={hit.chunk_id} className="space-y-1 rounded-md border border-line bg-surface p-2">
            <p className="text-xs text-ink-3">{hit.source_ref}</p>
            <h2 className="text-sm font-medium text-ink">{hit.title}</h2>
            <p className="line-clamp-4 whitespace-pre-line text-xs text-ink-2">{hit.content}</p>
            <button type="button" className="text-xs font-medium text-accent hover:underline" onClick={() => onAsk(`Help me with ${hit.title}`)}>
              Ask about this
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
