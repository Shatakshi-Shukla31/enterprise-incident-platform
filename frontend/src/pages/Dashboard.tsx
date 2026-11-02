import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { BarList, ChartCard, LineChart, StatTile } from "../components/charts";
import { Card, ErrorNote, Loading, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { humanize, percent } from "../lib/format";
import type { Dashboard } from "../lib/types";

const TREND_SERIES = [
  { key: "created", label: "Opened", color: "var(--series-1)" },
  { key: "resolved", label: "Resolved", color: "var(--series-2)" },
];

const MODEL_NAMES: Record<string, string> = {
  tfidf_linear_svc_calibrated: "TF-IDF + linear SVM, calibrated",
  tfidf_logistic_regression: "TF-IDF + logistic regression",
  tfidf_naive_bayes: "TF-IDF + naive Bayes",
  category_rule_baseline: "Category-to-team rule",
  lightgbm: "LightGBM",
  logistic_regression: "Logistic regression",
};

interface LiveModel {
  predictions: number;
  reviewed: number;
  acceptance_rate: number | null;
  mean_confidence: number;
}

function metric(values: Record<string, number> | undefined, key: string): string {
  const value = values?.[key];
  return value === undefined ? "—" : value.toFixed(3);
}

export function DashboardPage() {
  const [days, setDays] = useState(30);
  const dashboard = useQuery({
    queryKey: ["dashboard", days],
    queryFn: () => api.get<Dashboard>(`/analytics/dashboard?days=${days}`),
    placeholderData: keepPreviousData,
  });

  if (dashboard.isPending) return <Loading />;
  if (dashboard.error) return <ErrorNote error={dashboard.error} />;
  const data = dashboard.data;
  const { summary, ai_usage: ai } = data;
  const live = data.ml_live as Record<string, LiveModel | undefined>;
  const models = [
    ["Incident category", "category", "macro_f1", "Macro F1"],
    ["Team routing", "routing", "accuracy", "Accuracy"],
    ["SLA breach risk", "sla_risk", "pr_auc", "PR AUC"],
  ] as const;

  return (
    <div className="space-y-4" style={{ opacity: dashboard.isPlaceholderData ? 0.6 : 1 }}>
      <header className="flex items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-ink">Dashboard</h1>
        <select aria-label="Time range" className={`${inputClass} !w-auto`} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </header>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="SLA compliance" value={percent(summary.sla_compliance, 1)} note={`${summary.resolved.toLocaleString()} resolved`} />
        <StatTile label="Mean resolution time" value={summary.mean_resolution_hours === null ? "—" : `${summary.mean_resolution_hours.toFixed(1)} h`} note={`${summary.created.toLocaleString()} opened`} />
        <StatTile label="Open now" value={summary.open_now.toLocaleString()} note={`${summary.open_breached.toLocaleString()} past their SLA`} />
        <StatTile label="Open at high breach risk" value={summary.open_high_risk.toLocaleString()} note="Model score 70% or above" />
      </div>

      <ChartCard
        title="Incident volume"
        subtitle="Incidents opened and resolved per day"
        table={{ headers: ["Date", "Opened", "Resolved"], rows: data.trend.map((row) => [row.date, row.created, row.resolved]) }}
      >
        <LineChart data={data.trend} series={TREND_SERIES} />
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="SLA compliance by priority"
          subtitle="Resolved within the resolution target"
          table={{ headers: ["Priority", "Resolved", "Breached", "Compliance"], rows: data.sla_by_priority.map((row) => [row.priority, row.resolved, row.breached, percent(row.compliance, 1)]) }}
        >
          <BarList
            data={data.sla_by_priority.map((row) => ({ label: row.priority, value: row.compliance ?? 0, detail: `${row.breached} of ${row.resolved} breached` }))}
            format={(value) => percent(value)}
            max={1}
          />
        </ChartCard>
        <ChartCard
          title="Incidents by category"
          table={{ headers: ["Category", "Incidents"], rows: data.by_category.map((row) => [humanize(row.category), row.count]) }}
        >
          <BarList data={data.by_category.map((row) => ({ label: humanize(row.category), value: row.count }))} />
        </ChartCard>
        <ChartCard
          title="Mean resolution time by team"
          subtitle="Hours from opening to resolution"
          table={{ headers: ["Team", "Resolved", "Mean hours"], rows: data.resolution_by_team.map((row) => [row.team, row.resolved, row.mean_hours]) }}
        >
          <BarList
            data={[...data.resolution_by_team].sort((a, b) => b.mean_hours - a.mean_hours).map((row) => ({ label: row.team, value: row.mean_hours }))}
            format={(value) => `${value.toFixed(1)} h`}
          />
        </ChartCard>
        <Card title="AI recommendation usage">
          <dl className="grid grid-cols-2 gap-3">
            {[
              ["Recommendations", ai.recommendations.toLocaleString()],
              ["Declined for lack of evidence", percent(ai.insufficient_evidence_rate)],
              ["Rated helpful", ai.rated ? `${percent(ai.helpful_rate)} of ${ai.rated}` : "No ratings yet"],
              ["95th percentile latency", ai.p95_latency_ms === null ? "—" : `${ai.p95_latency_ms.toLocaleString()} ms`],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-xs text-ink-3">{label}</dt>
                <dd className="text-lg font-semibold text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        </Card>
      </div>

      <Card title="Model performance">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead>
              <tr className="text-xs text-ink-3">
                <th className="py-1 pr-3 font-medium">Model</th>
                <th className="py-1 pr-3 font-medium">Selected algorithm</th>
                <th className="py-1 pr-3 font-medium">Offline test score</th>
                <th className="py-1 pr-3 font-medium">Live predictions</th>
                <th className="py-1 pr-3 font-medium">Accepted when reviewed</th>
              </tr>
            </thead>
            <tbody>
              {models.map(([label, key, metricKey, metricLabel]) => {
                const offline = data.ml_offline[key];
                const current = live[key];
                return (
                  <tr key={key} className="border-t border-line">
                    <td className="py-2 pr-3 text-ink">{label}</td>
                    <td className="py-2 pr-3 text-ink-2">{MODEL_NAMES[offline?.selected_model ?? ""] ?? humanize(offline?.selected_model)}</td>
                    <td className="tabular py-2 pr-3 text-ink-2">
                      {metricLabel} {metric(offline?.test, metricKey)}
                    </td>
                    <td className="tabular py-2 pr-3 text-ink-2">{current?.predictions.toLocaleString() ?? "0"}</td>
                    <td className="tabular py-2 pr-3 text-ink-2">{current?.reviewed ? `${percent(current.acceptance_rate)} of ${current.reviewed}` : "Not reviewed"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-ink-3">Offline scores come from a held-out test split of synthetic data. They do not predict performance on real tickets.</p>
      </Card>
    </div>
  );
}
