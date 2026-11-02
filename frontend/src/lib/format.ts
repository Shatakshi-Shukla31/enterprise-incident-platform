const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function formatDate(value: string | null | undefined): string {
  return value ? dateTime.format(new Date(value)) : "—";
}

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  const text = value.replace(/[_.]/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function percent(value: number | null | undefined, digits = 0): string {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(digits)}%`;
}

export function dueIn(value: string, now: Date = new Date()): { label: string; overdue: boolean } {
  const minutes = Math.round((new Date(value).getTime() - now.getTime()) / 60000);
  const size = Math.abs(minutes);
  const text =
    size < 60 ? `${size}m` : size < 2880 ? `${Math.round(size / 60)}h` : `${Math.round(size / 1440)}d`;
  return minutes < 0 ? { label: `${text} overdue`, overdue: true } : { label: `in ${text}`, overdue: false };
}
