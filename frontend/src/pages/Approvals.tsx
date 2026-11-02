import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { isManager, useAuth } from "../auth/AuthContext";
import { Button, Card, EmptyState, ErrorNote, Loading, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { formatDate, humanize } from "../lib/format";
import type { Remediation } from "../lib/types";

export function ApprovalsPage() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState<Record<number, string>>({});
  const requests = useQuery({ queryKey: ["remediation-requests"], queryFn: () => api.get<Remediation[]>("/remediation/requests") });
  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: number; approve: boolean }) =>
      api.post(`/remediation/requests/${id}/decision`, { approve, note: notes[id] || null }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["remediation-requests"] }),
  });

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-ink">Remediation approvals</h1>
      <ErrorNote error={decide.error ?? requests.error} />
      {requests.isPending && <Loading />}
      {requests.data?.length === 0 && <EmptyState>No remediation requests.</EmptyState>}
      {requests.data?.map((item) => {
        const canDecide = item.status === "pending_approval" && isManager(user?.role) && item.requested_by.id !== user?.id;
        return (
          <Card key={item.id} title={item.runbook.name} action={<span className="text-sm text-ink-2">{humanize(item.status)}</span>}>
            <div className="space-y-2 text-sm">
              <p className="text-ink-2">{item.justification}</p>
              <p className="text-xs text-ink-3">
                Target {item.target} ·{" "}
                <Link to={`/incidents/${item.incident_id}`} className="hover:underline">
                  Incident {item.incident_id}
                </Link>{" "}
                · Requested by {item.requested_by.full_name} on {formatDate(item.created_at)}
                {item.decided_by && ` · Decided by ${item.decided_by.full_name}`}
              </p>
              {item.result.simulated === true && <p className="text-xs text-ink-3">Result: {String(item.result.step)} (simulated)</p>}
              {item.status === "pending_approval" && !canDecide && (
                <p className="text-xs text-ink-3">{item.requested_by.id === user?.id ? "A different person has to decide your request." : "Waiting for a manager."}</p>
              )}
              {canDecide && (
                <div className="flex flex-wrap gap-2 pt-1">
                  <input
                    aria-label={`Decision note for request ${item.id}`}
                    className={`${inputClass} min-w-48 flex-1`}
                    placeholder="Decision note (optional)"
                    value={notes[item.id] ?? ""}
                    onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })}
                  />
                  <Button disabled={decide.isPending} onClick={() => decide.mutate({ id: item.id, approve: true })}>
                    Approve
                  </Button>
                  <Button variant="danger" disabled={decide.isPending} onClick={() => decide.mutate({ id: item.id, approve: false })}>
                    Reject
                  </Button>
                </div>
              )}
            </div>
          </Card>
        );
      })}
    </div>
  );
}
