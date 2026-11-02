import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ChartCard, StackedBarList, StatTile } from "../components/charts";
import { Button, EmptyState, ErrorNote, Loading } from "../components/ui";
import { api } from "../lib/api";
import { formatDate, humanize } from "../lib/format";
import type { Notification, NotificationCount, NotificationSummary } from "../lib/types";

const REFRESH_MS = 30000;

const PARTS = [
  { key: "unread", label: "Unread", color: "var(--series-1)" },
  { key: "read", label: "Read", color: "var(--series-1-soft)" },
] as const;

/** Colour marks severity, and the label beside it always says the same thing in words. */
const TYPES: Record<string, { label: string; color: string }> = {
  sla_breach: { label: "SLA breached", color: "var(--critical)" },
  sla_risk: { label: "High SLA risk", color: "var(--warning)" },
  escalated: { label: "Escalated", color: "var(--warning)" },
  approval_required: { label: "Approval needed", color: "var(--series-1)" },
  remediation_result: { label: "Remediation result", color: "var(--series-1)" },
  assigned: { label: "Assigned to you", color: "var(--ink-3)" },
  status_changed: { label: "Status changed", color: "var(--ink-3)" },
  comment: { label: "New comment", color: "var(--ink-3)" },
};

const typeLabel = (key: string) => TYPES[key]?.label ?? humanize(key);
const statusLabel = (key: string) => (key === "no_ticket" ? "No ticket" : humanize(key));

function count(rows: NotificationCount[], ...keys: string[]): number {
  return rows.filter((row) => keys.includes(row.key)).reduce((sum, row) => sum + row.unread + row.read, 0);
}

function chartData(rows: NotificationCount[], label: (key: string) => string) {
  return rows.map((row) => ({ label: label(row.key), unread: row.unread, read: row.read }));
}

function tableRows(rows: NotificationCount[], label: (key: string) => string) {
  return rows.map((row) => [label(row.key), row.unread, row.read, row.unread + row.read]);
}

function Overview({ summary }: { summary: NotificationSummary }) {
  const byType = [...summary.by_type].sort((a, b) => b.unread + b.read - (a.unread + a.read));
  const headers = ["Unread", "Read", "Total"];
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Unread" value={summary.unread.toLocaleString()} note={`Of ${summary.total.toLocaleString()} in total`} />
        <StatTile label="SLA alerts" value={count(summary.by_type, "sla_breach", "sla_risk").toLocaleString()} note="Breached or at high risk" />
        <StatTile label="Escalations" value={count(summary.by_type, "escalated").toLocaleString()} note="Overdue, urgent or escalated tickets" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="By type" subtitle="What each notification was about" table={{ headers: ["Type", ...headers], rows: tableRows(byType, typeLabel) }}>
          <StackedBarList name="Notifications by type" data={chartData(byType, typeLabel)} parts={[...PARTS]} />
        </ChartCard>
        <ChartCard title="By ticket status" subtitle="Where the linked tickets are now" table={{ headers: ["Status", ...headers], rows: tableRows(summary.by_status, statusLabel) }}>
          <StackedBarList name="Notifications by ticket status" data={chartData(summary.by_status, statusLabel)} parts={[...PARTS]} />
        </ChartCard>
      </div>
    </>
  );
}

export function NotificationsPage() {
  const queryClient = useQueryClient();
  const notifications = useQuery({
    queryKey: ["notifications"],
    queryFn: () => api.get<Notification[]>("/notifications?limit=100"),
    refetchInterval: REFRESH_MS,
  });
  const summary = useQuery({
    queryKey: ["notifications", "summary"],
    queryFn: () => api.get<NotificationSummary>("/notifications/summary"),
    refetchInterval: REFRESH_MS,
  });
  const readAll = useMutation({
    mutationFn: () => api.post("/notifications/read-all"),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-ink">Notifications</h1>
        <Button variant="secondary" disabled={readAll.isPending || summary.data?.unread === 0} onClick={() => readAll.mutate()}>
          Mark all read
        </Button>
      </header>
      <ErrorNote error={notifications.error ?? summary.error ?? readAll.error} />
      {notifications.isPending && <Loading />}
      {notifications.data?.length === 0 && <EmptyState>Nothing here yet.</EmptyState>}
      {summary.data && summary.data.total > 0 && <Overview summary={summary.data} />}
      {!!notifications.data?.length && (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {notifications.data.map((item) => (
            <li key={item.id} className={`flex gap-3 p-3 text-sm ${item.read_at ? "opacity-70" : ""}`}>
              <span aria-hidden className="mt-1.5 size-2 shrink-0 rounded-full" style={{ background: TYPES[item.type]?.color ?? "var(--ink-3)" }} />
              <div className="min-w-0 flex-1">
                <p className={`text-ink ${item.read_at ? "" : "font-medium"}`}>
                  {item.incident_id ? (
                    <Link to={`/incidents/${item.incident_id}`} className="hover:underline">
                      {item.title}
                    </Link>
                  ) : (
                    item.title
                  )}
                </p>
                {item.body && <p className="text-ink-2">{item.body}</p>}
                <p className="tabular text-xs text-ink-3">
                  {typeLabel(item.type)} · {formatDate(item.created_at)}
                </p>
              </div>
              {!item.read_at && <span className="self-start rounded-full bg-accent-soft px-2 py-0.5 text-xs text-ink">Unread</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
