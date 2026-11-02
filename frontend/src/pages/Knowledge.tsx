import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { isManager, useAuth } from "../auth/AuthContext";
import { Button, Card, EmptyState, ErrorNote, Field, Loading, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { humanize } from "../lib/format";
import type { KnowledgeDocument } from "../lib/types";

interface Hit {
  chunk_id: number;
  title: string;
  source_ref: string;
  similarity: number;
  content: string;
}

interface IngestResult {
  chunks: number;
  flagged_chunks: number;
  unchanged: boolean;
}

const EMPTY = { source_ref: "", title: "", content: "", access_level: "internal" };

export function KnowledgePage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [form, setForm] = useState(EMPTY);
  const documents = useQuery({
    queryKey: ["documents", page],
    queryFn: () => api.get<KnowledgeDocument[]>(`/knowledge/documents?page=${page}&page_size=20`),
  });
  const search = useMutation({ mutationFn: () => api.post<Hit[]>("/knowledge/search", { query, top_k: 5 }) });
  const create = useMutation({
    mutationFn: () => api.post<IngestResult>("/knowledge/documents", form),
    onSuccess: () => {
      setForm(EMPTY);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
  });

  function runSearch(event: FormEvent) {
    event.preventDefault();
    if (query.trim().length > 1) search.mutate();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  const rows = documents.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-ink">Knowledge</h1>

      <Card title="Search">
        <form onSubmit={runSearch} className="flex gap-2">
          <input aria-label="Search knowledge" className={inputClass} placeholder="Describe a symptom" value={query} onChange={(e) => setQuery(e.target.value)} />
          <Button type="submit" variant="secondary" disabled={search.isPending}>
            Search
          </Button>
        </form>
        <ErrorNote error={search.error} />
        {search.data && (
          <ul className="mt-3 space-y-2">
            {search.data.length === 0 && <li className="text-sm text-ink-3">No documents you can read match this.</li>}
            {search.data.map((hit) => (
              <li key={hit.chunk_id} className="border-t border-line pt-2 text-sm">
                <p className="text-ink">{hit.title}</p>
                <p className="tabular text-xs text-ink-3">
                  {hit.source_ref} · similarity {hit.similarity.toFixed(2)}
                </p>
                <p className="line-clamp-2 text-xs text-ink-2">{hit.content}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {isManager(user?.role) && (
        <Card title="Add an article">
          <form onSubmit={submit} className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <Field label="Reference">
                <input className={inputClass} required pattern="[A-Za-z0-9._\-]{2,100}" placeholder="KB-2001" value={form.source_ref} onChange={(e) => setForm({ ...form, source_ref: e.target.value })} />
              </Field>
              <Field label="Title">
                <input className={inputClass} required minLength={5} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
              </Field>
              <Field label="Access">
                <select className={inputClass} value={form.access_level} onChange={(e) => setForm({ ...form, access_level: e.target.value })}>
                  <option value="public">Everyone</option>
                  <option value="internal">Support staff</option>
                </select>
              </Field>
            </div>
            <Field label="Content">
              <textarea className={`${inputClass} min-h-28`} required minLength={20} value={form.content} onChange={(e) => setForm({ ...form, content: e.target.value })} />
            </Field>
            <ErrorNote error={create.error} />
            {create.data && (
              <p role="status" className="text-sm text-ink-2">
                Indexed {create.data.chunks} chunk(s).
                {create.data.flagged_chunks > 0 && ` ${create.data.flagged_chunks} quarantined as possible prompt injection and excluded from answers.`}
              </p>
            )}
            <Button type="submit" variant="secondary" disabled={create.isPending}>
              Index article
            </Button>
          </form>
        </Card>
      )}

      <Card title="Documents you can read">
        {documents.isPending && <Loading />}
        {rows.length === 0 && !documents.isPending && <EmptyState>No documents.</EmptyState>}
        {rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] text-left text-sm">
              <thead>
                <tr className="text-xs text-ink-3">
                  <th className="py-1 pr-3 font-medium">Reference</th>
                  <th className="py-1 pr-3 font-medium">Title</th>
                  <th className="py-1 pr-3 font-medium">Category</th>
                  <th className="py-1 pr-3 font-medium">Access</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((document) => (
                  <tr key={document.id} className="border-t border-line">
                    <td className="tabular whitespace-nowrap py-1.5 pr-3 text-ink-2">{document.source_ref}</td>
                    <td className="py-1.5 pr-3 text-ink">{document.title}</td>
                    <td className="py-1.5 pr-3 text-ink-2">{humanize(document.category)}</td>
                    <td className="py-1.5 pr-3 text-ink-2">{humanize(document.access_level)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex justify-end gap-2 pt-3 text-sm">
          <Button variant="secondary" disabled={page === 1} onClick={() => setPage(page - 1)}>
            Previous
          </Button>
          <Button variant="secondary" disabled={rows.length < 20} onClick={() => setPage(page + 1)}>
            Next
          </Button>
        </div>
      </Card>
    </div>
  );
}

