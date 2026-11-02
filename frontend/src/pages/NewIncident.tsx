import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, ErrorNote, Field, inputClass } from "../components/ui";
import { api } from "../lib/api";
import type { Incident } from "../lib/types";

export function NewIncidentPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ title: "", description: "", impact: "medium", urgency: "medium" });
  const create = useMutation({
    mutationFn: () => api.post<Incident>("/incidents", form),
    onSuccess: (incident) => {
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      navigate(`/incidents/${incident.id}`);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  const levels = (
    <>
      <option value="high">High</option>
      <option value="medium">Medium</option>
      <option value="low">Low</option>
    </>
  );

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-xl font-semibold text-ink">New incident</h1>
      <Card>
        <form onSubmit={submit} className="space-y-4">
          <Field label="Summary">
            <input className={inputClass} required minLength={5} maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="What is happening?" hint="Include error messages, when it started, and who is affected. This drives automatic routing.">
            <textarea className={`${inputClass} min-h-32`} required minLength={10} maxLength={10000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Impact" hint="How many people or services are affected">
              <select className={inputClass} value={form.impact} onChange={(e) => setForm({ ...form, impact: e.target.value })}>
                {levels}
              </select>
            </Field>
            <Field label="Urgency" hint="How soon it needs to be fixed">
              <select className={inputClass} value={form.urgency} onChange={(e) => setForm({ ...form, urgency: e.target.value })}>
                {levels}
              </select>
            </Field>
          </div>
          <ErrorNote error={create.error} />
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Submitting…" : "Submit incident"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
