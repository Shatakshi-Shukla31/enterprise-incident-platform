import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { isStaff, useAuth } from "../auth/AuthContext";
import { EmptyState, ErrorNote, Loading, Pagination, PriorityBadge, RiskLabel, StatusBadge, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { dueIn, humanize } from "../lib/format";
import type { Incident, Page, Status, Team } from "../lib/types";

const STATUSES: Status[] = ["new", "assigned", "in_progress", "on_hold", "resolved", "closed"];
const CATEGORIES = ["network", "access_identity", "hardware", "software_application", "database", "cloud_infrastructure", "security", "email_collaboration"];

export function IncidentsPage() {
  const { user } = useAuth();
  const staff = isStaff(user?.role);
  const [params, setParams] = useSearchParams({ open_only: "true" });
  const [search, setSearch] = useState(params.get("q") ?? "");

  function update(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    setParams(next);
  }

  const query = params.toString();
  const incidents = useQuery({
    queryKey: ["incidents", query],
    queryFn: () => api.get<Page<Incident>>(`/incidents?page_size=20&${query}`),
    placeholderData: keepPreviousData,
  });
  const teams = useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/teams"), enabled: staff });

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-ink">Incidents</h1>
        <Link to="/incidents/new" className="rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-ink hover:opacity-90">
          New incident
        </Link>
      </header>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
        <form
          className="lg:col-span-2"
          onSubmit={(event) => {
            event.preventDefault();
            update("q", search.trim());
          }}
        >
          <input aria-label="Search incidents" placeholder="Search text or INC number" className={inputClass} value={search} onChange={(e) => setSearch(e.target.value)} />
        </form>
        <select
          aria-label="Status"
          className={inputClass}
          value={params.get("status") ?? (params.get("open_only") ? "open" : "")}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            next.delete("status");
            next.delete("open_only");
            next.delete("page");
            if (event.target.value === "open") next.set("open_only", "true");
            else if (event.target.value) next.set("status", event.target.value);
            setParams(next);
          }}
        >
          <option value="open">All open</option>
          <option value="">All statuses</option>
          {STATUSES.map((status) => (
            <option key={status} value={status}>
              {humanize(status)}
            </option>
          ))}
        </select>
        <select aria-label="Priority" className={inputClass} value={params.get("priority") ?? ""} onChange={(e) => update("priority", e.target.value)}>
          <option value="">All priorities</option>
          {["P1", "P2", "P3", "P4"].map((priority) => (
            <option key={priority}>{priority}</option>
          ))}
        </select>
        {staff ? (
          <select aria-label="Team" className={inputClass} value={params.get("team_id") ?? ""} onChange={(e) => update("team_id", e.target.value)}>
            <option value="">All teams</option>
            {teams.data?.map((team) => (
              <option key={team.id} value={team.id}>
                {team.name}
              </option>
            ))}
          </select>
        ) : (
          <select aria-label="Category" className={inputClass} value={params.get("category") ?? ""} onChange={(e) => update("category", e.target.value)}>
            <option value="">All categories</option>
            {CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {humanize(category)}
              </option>
            ))}
          </select>
        )}
      </div>
      {staff && (
        <div className="flex flex-wrap items-center gap-4 text-sm text-ink-2">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={params.get("breached") === "true"} onChange={(e) => update("breached", e.target.checked ? "true" : "")} />
            Breached only
          </label>
          <label className="flex items-center gap-2">
            Sort by
            <select aria-label="Sort" className="rounded-md border border-line bg-surface px-2 py-1 text-sm" value={params.get("sort") ?? "created_at"} onChange={(e) => update("sort", e.target.value)}>
              <option value="created_at">Newest</option>
              <option value="resolution_due_at">Due date</option>
              <option value="sla_risk_score">SLA risk</option>
              <option value="updated_at">Recently updated</option>
            </select>
          </label>
        </div>
      )}

      <ErrorNote error={incidents.error} />
      {incidents.isPending ? (
        <Loading />
      ) : incidents.data?.items.length ? (
        <>
          <div className="overflow-x-auto rounded-lg border border-line bg-surface" style={{ opacity: incidents.isPlaceholderData ? 0.6 : 1 }}>
            <table className="w-full min-w-[820px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs text-ink-3">
                  <th className="px-3 py-2 font-medium">Incident</th>
                  <th className="px-3 py-2 font-medium">Priority</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Team</th>
                  <th className="px-3 py-2 font-medium">SLA</th>
                  {staff && <th className="px-3 py-2 font-medium">Breach risk</th>}
                </tr>
              </thead>
              <tbody>
                {incidents.data.items.map((incident) => {
                  const due = dueIn(incident.resolution_due_at);
                  const open = !incident.resolved_at;
                  return (
                    <tr key={incident.id} className="border-b border-line last:border-0 hover:bg-sunken">
                      <td className="max-w-md px-3 py-2">
                        <Link to={`/incidents/${incident.id}`} className="block truncate font-medium text-ink hover:underline">
                          {incident.title}
                        </Link>
                        <span className="tabular text-xs text-ink-3">
                          {incident.number} · {humanize(incident.category) === "—" ? "Untriaged" : humanize(incident.category)}
                        </span>
                      </td>
                      <td className="px-3 py-2">
                        <PriorityBadge priority={incident.priority} />
                      </td>
                      <td className="px-3 py-2">
                        <StatusBadge status={incident.status} />
                      </td>
                      <td className="whitespace-nowrap px-3 py-2 text-ink-2">{incident.team?.name ?? "Unrouted"}</td>
                      <td className="tabular whitespace-nowrap px-3 py-2">
                        {incident.sla_breached ? (
                          <span className="font-medium text-[var(--critical)]">Breached</span>
                        ) : open ? (
                          <span className={due.overdue ? "text-[var(--critical)]" : "text-ink-2"}>{due.label}</span>
                        ) : (
                          <span className="text-[var(--good)]">Met</span>
                        )}
                      </td>
                      {staff && (
                        <td className="px-3 py-2">
                          {open ? <RiskLabel score={incident.sla_risk_score} /> : <span className="text-ink-3">—</span>}
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination
            page={incidents.data.page}
            pageSize={incidents.data.page_size}
            total={incidents.data.total}
            onChange={(page) => update("page", String(page))}
          />
        </>
      ) : (
        <EmptyState>No incidents match these filters.</EmptyState>
      )}
    </div>
  );
}
