import type { ButtonHTMLAttributes, ReactNode } from "react";
import { humanize } from "../lib/format";
import type { Priority, Status } from "../lib/types";

export const inputClass =
  "w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 disabled:opacity-60";

export function Button({
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-accent text-accent-ink hover:opacity-90",
    secondary: "border border-line bg-surface text-ink hover:bg-sunken",
    ghost: "text-ink-2 hover:bg-sunken",
    danger: "border border-line bg-surface text-[var(--critical)] hover:bg-sunken",
  }[variant];
  return (
    <button
      type="button"
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export function Card({ title, action, children, className = "" }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-lg border border-line bg-surface p-4 ${className}`}>
      {(title || action) && (
        <header className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-ink-2">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-3">{hint}</span>}
    </label>
  );
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <p role="alert" className="rounded-md border border-line bg-sunken px-3 py-2 text-sm text-[var(--critical)]">
      {error instanceof Error ? error.message : "Something went wrong"}
    </p>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="py-8 text-center text-sm text-ink-3">{label}</p>;
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="py-8 text-center text-sm text-ink-3">{children}</p>;
}

const priorityStyle: Record<Priority, string> = {
  P1: "border-[var(--critical)] text-[var(--critical)]",
  P2: "border-[var(--warning)] text-[var(--warning)]",
  P3: "border-line text-ink-2",
  P4: "border-line text-ink-3",
};

export function PriorityBadge({ priority }: { priority: Priority }) {
  return (
    <span className={`tabular inline-block rounded border px-1.5 py-0.5 text-xs font-semibold ${priorityStyle[priority]}`}>
      {priority}
    </span>
  );
}

const statusDot: Record<Status, string> = {
  new: "bg-[var(--series-1)]",
  assigned: "bg-[var(--series-1)]",
  in_progress: "bg-[var(--warning)]",
  on_hold: "bg-ink-3",
  resolved: "bg-[var(--good)]",
  closed: "bg-ink-3",
};

export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm text-ink-2">
      <span aria-hidden className={`size-2 rounded-full ${statusDot[status]}`} />
      {humanize(status)}
    </span>
  );
}

export function RiskLabel({ score }: { score: number | null }) {
  if (score === null) return <span className="text-ink-3">—</span>;
  const level = score >= 0.7 ? "High" : score >= 0.4 ? "Medium" : "Low";
  const color = score >= 0.7 ? "text-[var(--critical)]" : score >= 0.4 ? "text-[var(--warning)]" : "text-ink-2";
  return (
    <span className={`tabular whitespace-nowrap text-sm ${color}`}>
      {level} · {Math.round(score * 100)}%
    </span>
  );
}

export function Pagination({ page, pageSize, total, onChange }: { page: number; pageSize: number; total: number; onChange: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 pt-3 text-sm text-ink-2">
      <span className="tabular">
        {total.toLocaleString()} result{total === 1 ? "" : "s"}
      </span>
      <span className="flex items-center gap-2">
        <Button variant="secondary" disabled={page <= 1} onClick={() => onChange(page - 1)}>
          Previous
        </Button>
        <span className="tabular">
          Page {page} of {pages}
        </span>
        <Button variant="secondary" disabled={page >= pages} onClick={() => onChange(page + 1)}>
          Next
        </Button>
      </span>
    </nav>
  );
}
