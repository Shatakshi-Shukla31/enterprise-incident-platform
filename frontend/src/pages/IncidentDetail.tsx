import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { isManager, isStaff, useAuth } from "../auth/AuthContext";
import { AnswerText, Citations, FeedbackButtons } from "../components/Answer";
import { Button, Card, ErrorNote, Field, Loading, PriorityBadge, RiskLabel, StatusBadge, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { dueIn, formatDate, humanize, percent } from "../lib/format";
import { describeFactor, formatEffect } from "../lib/risk";
import type { Answer, AuditEntry, Comment, Incident, Page, Prediction, Remediation, Runbook, Status, Team, User } from "../lib/types";

const NEXT_STATUS: Record<Status, Status[]> = {
  new: ["assigned", "in_progress", "resolved"],
  assigned: ["in_progress", "on_hold", "resolved"],
  in_progress: ["on_hold", "resolved"],
  on_hold: ["in_progress", "resolved"],
  resolved: ["in_progress", "closed"],
  closed: [],
};
const CATEGORIES = ["network", "access_identity", "hardware", "software_application", "database", "cloud_infrastructure", "security", "email_collaboration"];

function useRefresh(id: string) {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["incident", "predictions", "audit", "comments", "remediations"]) {
      void queryClient.invalidateQueries({ queryKey: [key, id] });
    }
    void queryClient.invalidateQueries({ queryKey: ["incidents"] });
  };
}

export function IncidentDetailPage() {
  const { id = "" } = useParams();
  const { user } = useAuth();
  const staff = isStaff(user?.role);
  const incident = useQuery({ queryKey: ["incident", id], queryFn: () => api.get<Incident>(`/incidents/${id}`) });

  if (incident.isPending) return <Loading />;
  if (incident.error) return <ErrorNote error={incident.error} />;
  const row = incident.data;
  const due = dueIn(row.resolution_due_at);

  return (
    <div className="space-y-4">
      <header>
        <Link to="/incidents" className="text-sm text-ink-3 hover:underline">
          Back to incidents
        </Link>
        <h1 className="mt-1 text-xl font-semibold text-ink">{row.title}</h1>
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-ink-3">
          <span className="tabular">{row.number}</span>
          <PriorityBadge priority={row.priority} />
          <StatusBadge status={row.status} />
          {row.escalation_level > 0 && <span className="font-medium text-[var(--critical)]">Escalated · level {row.escalation_level}</span>}
          {row.sla_breached ? (
            <span className="font-medium text-[var(--critical)]">SLA breached</span>
          ) : (
            !row.resolved_at && <span className={due.overdue ? "text-[var(--critical)]" : ""}>Resolution due {due.label}</span>
          )}
        </div>
      </header>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 space-y-4">
          <Card title="Description">
            <p className="whitespace-pre-wrap text-sm text-ink">{row.description}</p>
            {row.resolution_notes && (
              <div className="mt-3 border-t border-line pt-3">
                <p className="text-xs font-medium text-ink-3">Resolution</p>
                <p className="whitespace-pre-wrap text-sm text-ink">{row.resolution_notes}</p>
              </div>
            )}
          </Card>
          {staff && <SuggestionPanel id={id} />}
          <CommentsPanel id={id} staff={staff} closed={row.status === "closed"} />
          {staff && <HistoryPanel id={id} />}
        </div>

        <div className="space-y-4">
          <DetailsPanel incident={row} />
          {staff && <ActionsPanel incident={row} id={id} />}
          {staff && <TriagePanel incident={row} id={id} />}
          {staff && <RemediationPanel id={id} canApprove={isManager(user?.role)} />}
        </div>
      </div>
    </div>
  );
}

function DetailsPanel({ incident }: { incident: Incident }) {
  const rows: [string, string][] = [
    ["Requester", incident.requester.full_name],
    ["Assignee", incident.assignee?.full_name ?? "Unassigned"],
    ["Team", incident.team?.name ?? "Unrouted"],
    ["Category", humanize(incident.category)],
    ["Impact / urgency", `${humanize(incident.impact)} / ${humanize(incident.urgency)}`],
    ["Channel", humanize(incident.channel)],
    ["Created", formatDate(incident.created_at)],
    ["First response", formatDate(incident.first_response_at)],
    ["Response due", formatDate(incident.response_due_at)],
    ["Resolution due", formatDate(incident.resolution_due_at)],
  ];
  return (
    <Card title="Details">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-ink-3">{label}</dt>
            <dd className="text-right text-ink">{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function ActionsPanel({ incident, id }: { incident: Incident; id: string }) {
  const refresh = useRefresh(id);
  const options = NEXT_STATUS[incident.status];
  const [status, setStatus] = useState<Status | "">("");
  const [notes, setNotes] = useState("");
  const [teamId, setTeamId] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [reason, setReason] = useState("");
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams") });
  const staffUsers = useQuery({
    queryKey: ["staff"],
    queryFn: () => api.get<Page<User>>("/users?staff_only=true&page_size=100"),
  });

  const changeStatus = useMutation({
    mutationFn: () => api.post(`/incidents/${id}/status`, { status, resolution_notes: notes || null }),
    onSuccess: () => {
      setStatus("");
      setNotes("");
      refresh();
    },
  });
  const assign = useMutation({
    mutationFn: () =>
      api.post(`/incidents/${id}/assign`, {
        team_id: teamId ? Number(teamId) : null,
        assignee_id: assigneeId ? Number(assigneeId) : null,
      }),
    onSuccess: () => {
      setTeamId("");
      setAssigneeId("");
      refresh();
    },
  });
  const escalate = useMutation({
    mutationFn: () => api.post(`/incidents/${id}/escalate`, { reason }),
    onSuccess: () => {
      setReason("");
      refresh();
    },
  });

  if (!options.length) return null;
  const finished = incident.status === "resolved";

  return (
    <Card title="Actions">
      <div className="space-y-4">
        <div className="space-y-2">
          <Field label="Change status">
            <select className={inputClass} value={status} onChange={(e) => setStatus(e.target.value as Status)}>
              <option value="">Select…</option>
              {options.map((option) => (
                <option key={option} value={option}>
                  {humanize(option)}
                </option>
              ))}
            </select>
          </Field>
          {status === "resolved" && (
            <Field label="Resolution notes">
              <textarea className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} />
            </Field>
          )}
          <ErrorNote error={changeStatus.error} />
          <Button variant="secondary" disabled={!status || changeStatus.isPending} onClick={() => changeStatus.mutate()}>
            Update status
          </Button>
        </div>
        {!finished && (
          <div className="space-y-2 border-t border-line pt-3">
            <Field label="Team">
              <select className={inputClass} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
                <option value="">Keep {incident.team?.name ?? "unrouted"}</option>
                {teams.data?.map((team) => (
                  <option key={team.id} value={team.id}>
                    {team.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Assignee">
              <select className={inputClass} value={assigneeId} onChange={(e) => setAssigneeId(e.target.value)}>
                <option value="">Keep {incident.assignee?.full_name ?? "unassigned"}</option>
                {staffUsers.data?.items.map((person) => (
                  <option key={person.id} value={person.id}>
                    {person.full_name}
                  </option>
                ))}
              </select>
            </Field>
            <ErrorNote error={assign.error} />
            <Button variant="secondary" disabled={(!teamId && !assigneeId) || assign.isPending} onClick={() => assign.mutate()}>
              Assign
            </Button>
          </div>
        )}
        {!finished && (
          <div className="space-y-2 border-t border-line pt-3">
            <Field label="Escalation reason">
              <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
            <ErrorNote error={escalate.error} />
            <Button variant="danger" disabled={!reason.trim() || escalate.isPending} onClick={() => escalate.mutate()}>
              Escalate
            </Button>
          </div>
        )}
      </div>
    </Card>
  );
}

function TriagePanel({ incident, id }: { incident: Incident; id: string }) {
  const refresh = useRefresh(id);
  const predictions = useQuery({
    queryKey: ["predictions", id],
    queryFn: () => api.get<Prediction[]>(`/incidents/${id}/predictions`),
  });
  const correct = useMutation({
    mutationFn: (category: string) => api.post(`/incidents/${id}/category`, { category }),
    onSuccess: refresh,
  });
  const latest = (kind: Prediction["kind"]) => predictions.data?.find((item) => item.kind === kind);
  const category = latest("category");
  const routing = latest("routing");
  const risk = latest("sla_risk");

  return (
    <Card title="AI triage">
      <div className="space-y-3 text-sm">
        <div>
          <Field label="Category">
            <select
              className={inputClass}
              value={incident.category ?? ""}
              disabled={correct.isPending || incident.status === "closed"}
              onChange={(e) => correct.mutate(e.target.value)}
            >
              <option value="" disabled>
                Untriaged
              </option>
              {CATEGORIES.map((item) => (
                <option key={item} value={item}>
                  {humanize(item)}
                </option>
              ))}
            </select>
          </Field>
          <p className="mt-1 text-xs text-ink-3">
            {incident.category_corrected
              ? `Set by support staff${category ? `. Model said ${humanize(category.value)}.` : "."}`
              : category
                ? `Model prediction, ${percent(category.confidence)} confidence`
                : "No model prediction"}
          </p>
          <ErrorNote error={correct.error} />
        </div>
        {routing?.details.alternatives && (
          <div>
            <p className="font-medium text-ink-2">Recommended teams</p>
            <ul className="mt-1 space-y-0.5">
              {routing.details.alternatives.map((option) => (
                <li key={option.label} className="flex justify-between gap-2 text-ink-2">
                  <span className="truncate">{option.label}</span>
                  <span className="tabular text-ink-3">{percent(option.confidence)}</span>
                </li>
              ))}
            </ul>
            <p className="mt-1 text-xs text-ink-3">Override it with Assign. Overrides are measured.</p>
          </div>
        )}
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-ink-2">SLA breach risk</span>
          <RiskLabel score={incident.sla_risk_score} />
        </div>
        {!!risk?.details.factors?.length && (
          <div>
            <p className="text-xs text-ink-3">What moved the score, compared with a typical ticket</p>
            <ul className="mt-1 space-y-0.5">
              {risk.details.factors.map((item) => (
                <li key={item.factor} className="flex justify-between gap-2 text-ink-2">
                  <span>{describeFactor(item.factor, risk.details.features)}</span>
                  <span className="tabular whitespace-nowrap text-ink">{formatEffect(item.effect)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {risk && <p className="tabular text-xs text-ink-3">Model version {risk.model_version}</p>}
      </div>
    </Card>
  );
}

function SuggestionPanel({ id }: { id: string }) {
  const suggest = useMutation({ mutationFn: () => api.post<Answer>(`/incidents/${id}/ai/suggest`) });
  const answer = suggest.data;
  return (
    <Card
      title="Suggested resolution"
      action={
        <Button variant="secondary" disabled={suggest.isPending} onClick={() => suggest.mutate()}>
          {suggest.isPending ? "Searching…" : answer ? "Run again" : "Find a fix"}
        </Button>
      }
    >
      <ErrorNote error={suggest.error} />
      {!answer && !suggest.error && <p className="text-sm text-ink-3">Searches knowledge articles and resolved incidents you have access to.</p>}
      {answer && (
        <div className="space-y-3">
          {answer.insufficient_evidence ? <p className="text-sm text-ink-2">{answer.answer}</p> : <AnswerText text={answer.answer} citations={answer.citations} />}
          <Citations citations={answer.citations} />
          {answer.suggested_actions.length > 0 && (
            <div className="border-t border-line pt-3">
              <p className="text-sm font-medium text-ink-2">Runbooks you could request</p>
              <ul className="mt-1 text-sm text-ink-2">
                {answer.suggested_actions.map((action) => (
                  <li key={action.runbook_id}>{action.name}</li>
                ))}
              </ul>
              <p className="text-xs text-ink-3">Nothing runs until a second person approves it.</p>
            </div>
          )}
          {answer.related_incidents.length > 0 && (
            <div className="border-t border-line pt-3">
              <p className="text-sm font-medium text-ink-2">Related incidents</p>
              <ul className="mt-1 space-y-0.5 text-sm">
                {answer.related_incidents.map((item) => (
                  <li key={item.source_ref} className="truncate">
                    <Link to={`/incidents/${item.incident_id}`} className="text-ink hover:underline">
                      {item.source_ref}
                    </Link>{" "}
                    <span className="text-ink-3">{item.title}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2">
            <p className="tabular text-xs text-ink-3">
              {answer.provider} · {answer.latency_ms} ms
            </p>
            <FeedbackButtons recommendationId={answer.recommendation_id} />
          </div>
        </div>
      )}
    </Card>
  );
}

function CommentsPanel({ id, staff, closed }: { id: string; staff: boolean; closed: boolean }) {
  const refresh = useRefresh(id);
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const comments = useQuery({ queryKey: ["comments", id], queryFn: () => api.get<Comment[]>(`/incidents/${id}/comments`) });
  const add = useMutation({
    mutationFn: () => api.post(`/incidents/${id}/comments`, { body, is_internal: internal }),
    onSuccess: () => {
      setBody("");
      refresh();
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    add.mutate();
  }

  return (
    <Card title="Conversation">
      <ul className="space-y-3">
        {comments.data?.map((comment) => (
          <li key={comment.id} className="text-sm">
            <p className="text-xs text-ink-3">
              <span className="font-medium text-ink-2">{comment.author.full_name}</span> · {formatDate(comment.created_at)}
              {comment.is_internal && " · Internal note"}
            </p>
            <p className="whitespace-pre-wrap text-ink">{comment.body}</p>
          </li>
        ))}
        {comments.data?.length === 0 && <li className="text-sm text-ink-3">No comments yet.</li>}
      </ul>
      {!closed && (
        <form onSubmit={submit} className="mt-3 space-y-2 border-t border-line pt-3">
          <textarea aria-label="Add a comment" className={inputClass} placeholder="Add a comment" value={body} onChange={(e) => setBody(e.target.value)} />
          <ErrorNote error={add.error} />
          <div className="flex items-center justify-between gap-2">
            {staff ? (
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} />
                Internal note
              </label>
            ) : (
              <span />
            )}
            <Button type="submit" variant="secondary" disabled={!body.trim() || add.isPending}>
              Post
            </Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function HistoryPanel({ id }: { id: string }) {
  const history = useQuery({ queryKey: ["audit", id], queryFn: () => api.get<AuditEntry[]>(`/incidents/${id}/audit`) });
  return (
    <Card title="Audit history">
      <ol className="space-y-1.5 text-sm">
        {history.data?.map((entry) => (
          <li key={entry.id} className="flex flex-wrap justify-between gap-x-3">
            <span className="text-ink-2">
              {humanize(entry.action.replace("incident.", ""))}
              <span className="text-ink-3"> · {entry.actor?.full_name ?? "System"}</span>
            </span>
            <span className="tabular text-xs text-ink-3">{formatDate(entry.created_at)}</span>
          </li>
        ))}
      </ol>
    </Card>
  );
}

function RemediationPanel({ id, canApprove }: { id: string; canApprove: boolean }) {
  const refresh = useRefresh(id);
  const [runbookId, setRunbookId] = useState("");
  const [target, setTarget] = useState("");
  const [justification, setJustification] = useState("");
  const runbooks = useQuery({ queryKey: ["runbooks"], queryFn: () => api.get<Runbook[]>("/remediation/runbooks") });
  const requests = useQuery({
    queryKey: ["remediations", id],
    queryFn: () => api.get<Remediation[]>(`/incidents/${id}/remediations`),
  });
  const create = useMutation({
    mutationFn: () => api.post(`/incidents/${id}/remediations`, { runbook_id: Number(runbookId), target, justification }),
    onSuccess: () => {
      setRunbookId("");
      setTarget("");
      setJustification("");
      refresh();
    },
  });

  return (
    <Card title="Remediation">
      {requests.data?.length ? (
        <ul className="mb-3 space-y-2 text-sm">
          {requests.data.map((item) => (
            <li key={item.id}>
              <p className="text-ink">{item.runbook.name}</p>
              <p className="text-xs text-ink-3">
                {item.target} · {humanize(item.status)}
                {item.result.simulated === true && " · simulated"}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="space-y-2">
        <Field label="Runbook">
          <select className={inputClass} value={runbookId} onChange={(e) => setRunbookId(e.target.value)}>
            <option value="">Select…</option>
            {runbooks.data?.map((runbook) => (
              <option key={runbook.id} value={runbook.id}>
                {runbook.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Target">
          <input className={inputClass} placeholder="orders-api" value={target} onChange={(e) => setTarget(e.target.value)} />
        </Field>
        <Field label="Justification">
          <textarea className={inputClass} value={justification} onChange={(e) => setJustification(e.target.value)} />
        </Field>
        <ErrorNote error={create.error} />
        <Button variant="secondary" disabled={!runbookId || !target || justification.length < 10 || create.isPending} onClick={() => create.mutate()}>
          Request approval
        </Button>
        <p className="text-xs text-ink-3">
          {canApprove ? "You cannot approve your own request." : "A manager has to approve this."} Handlers are simulated in this demo.
        </p>
      </div>
    </Card>
  );
}
