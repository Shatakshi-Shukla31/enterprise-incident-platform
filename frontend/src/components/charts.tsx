import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Button } from "./ui";

export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((candidate) => candidate * magnitude >= value) ?? 10;
  return step * magnitude;
}

/** Track a container's width, so a chart can draw at real pixels and keep its text one size. */
function useWidth(fallback: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(entry.contentRect.width);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** A chart and its table are two views of one dataset, so no value depends on hovering. */
export function ChartCard({
  title,
  subtitle,
  table,
  children,
}: {
  title: string;
  subtitle?: string;
  table: { headers: string[]; rows: (string | number)[][] };
  children: ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  return (
    <section className="min-w-0 rounded-lg border border-line bg-surface p-4">
      <header className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {subtitle && <p className="text-xs text-ink-3">{subtitle}</p>}
        </div>
        <Button variant="ghost" className="!px-2 !py-1 text-xs" aria-pressed={showTable} onClick={() => setShowTable(!showTable)}>
          {showTable ? "Chart" : "Table"}
        </Button>
      </header>
      {showTable ? (
        <div className="max-h-72 overflow-auto">
          <table className="tabular w-full text-left text-sm">
            <thead>
              <tr className="text-xs text-ink-3">
                {table.headers.map((header) => (
                  <th key={header} className="py-1 pr-3 font-medium">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row) => (
                <tr key={String(row[0])} className="border-t border-line">
                  {row.map((cell, index) => (
                    <td key={index} className="py-1 pr-3 text-ink-2">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}
    </section>
  );
}

interface Series {
  key: string;
  label: string;
  color: string;
}

const HEIGHT = 240;
const MARGIN = { top: 12, right: 12, bottom: 24, left: 36 };

export function LineChart<T extends { date: string }>({ data, series }: { data: T[]; series: Series[] }) {
  const [active, setActive] = useState<number | null>(null);
  const [containerRef, WIDTH] = useWidth(640);
  const plotWidth = WIDTH - MARGIN.left - MARGIN.right;
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom;
  const value = (row: T, key: string) => Number((row as Record<string, unknown>)[key] ?? 0);

  const top = useMemo(
    () => niceMax(Math.max(1, ...data.flatMap((row) => series.map((item) => value(row, item.key))))),
    [data, series],
  );
  const x = (index: number) => MARGIN.left + (data.length < 2 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth);
  const y = (amount: number) => MARGIN.top + plotHeight - (amount / top) * plotHeight;

  function nearest(clientX: number, rect: DOMRect): number {
    const position = ((clientX - rect.left) / rect.width) * WIDTH;
    const ratio = (position - MARGIN.left) / plotWidth;
    return Math.max(0, Math.min(data.length - 1, Math.round(ratio * (data.length - 1))));
  }

  const row = active === null ? null : data[active];
  const labels = [0, Math.floor((data.length - 1) / 2), data.length - 1].filter((v, i, all) => all.indexOf(v) === i);

  return (
    <div>
      <ul className="mb-2 flex flex-wrap gap-4 text-xs text-ink-2">
        {series.map((item) => (
          <li key={item.key} className="flex items-center gap-1.5">
            <span aria-hidden className="h-0.5 w-4 rounded" style={{ background: item.color }} />
            {item.label}
          </li>
        ))}
      </ul>
      <div className="relative" ref={containerRef}>
        <svg
          width={WIDTH}
          height={HEIGHT}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="block max-w-full"
          role="img"
          aria-label={`Line chart of ${series.map((item) => item.label).join(" and ")} by day. Use the Table view for exact values.`}
          tabIndex={0}
          onPointerMove={(event) => setActive(nearest(event.clientX, event.currentTarget.getBoundingClientRect()))}
          onPointerLeave={() => setActive(null)}
          onFocus={() => setActive(data.length - 1)}
          onBlur={() => setActive(null)}
          onKeyDown={(event) => {
            if (event.key === "ArrowLeft") setActive((index) => Math.max(0, (index ?? 0) - 1));
            if (event.key === "ArrowRight") setActive((index) => Math.min(data.length - 1, (index ?? 0) + 1));
          }}
        >
          {[0, 0.5, 1].map((tick) => (
            <g key={tick}>
              <line
                x1={MARGIN.left}
                x2={WIDTH - MARGIN.right}
                y1={y(top * tick)}
                y2={y(top * tick)}
                stroke={tick === 0 ? "var(--baseline)" : "var(--line)"}
              />
              <text x={MARGIN.left - 6} y={y(top * tick) + 4} textAnchor="end" fontSize="11" fill="var(--ink-3)" className="tabular">
                {(top * tick).toLocaleString()}
              </text>
            </g>
          ))}
          {labels.map((index) => (
            <text
              key={index}
              x={x(index)}
              y={HEIGHT - 6}
              textAnchor={index === 0 ? "start" : index === data.length - 1 ? "end" : "middle"}
              fontSize="11"
              fill="var(--ink-3)"
            >
              {data[index]?.date.slice(5)}
            </text>
          ))}
          {series.map((item) => (
            <polyline
              key={item.key}
              fill="none"
              stroke={item.color}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
              points={data.map((point, index) => `${x(index)},${y(value(point, item.key))}`).join(" ")}
            />
          ))}
          {active !== null && row && (
            <g>
              <line x1={x(active)} x2={x(active)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} stroke="var(--baseline)" />
              {series.map((item) => (
                <circle key={item.key} cx={x(active)} cy={y(value(row, item.key))} r="4" fill={item.color} stroke="var(--surface)" strokeWidth="2" />
              ))}
            </g>
          )}
        </svg>
        {active !== null && row && (
          <div
            role="status"
            className="pointer-events-none absolute top-1 rounded-md border border-line bg-surface px-2 py-1 text-xs shadow-sm"
            style={active > data.length / 2 ? { left: 44 } : { right: 16 }}
          >
            <p className="font-medium text-ink">{row.date}</p>
            {series.map((item) => (
              <p key={item.key} className="tabular flex items-center gap-1.5 text-ink-2">
                <span aria-hidden className="h-0.5 w-3 rounded" style={{ background: item.color }} />
                {item.label}: {value(row, item.key)}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function BarList({
  data,
  format = (value) => value.toLocaleString(),
  max,
}: {
  data: { label: string; value: number; detail?: string }[];
  format?: (value: number) => string;
  max?: number;
}) {
  const top = max ?? Math.max(1, ...data.map((item) => item.value));
  return (
    <ul className="space-y-2">
      {data.map((item) => (
        <li key={item.label} title={item.detail} className="grid grid-cols-[minmax(0,10rem)_1fr_3.5rem] items-center gap-2 text-sm">
          <span className="truncate text-ink-2">{item.label}</span>
          <span className="block h-2.5 rounded-r bg-sunken">
            <span
              className="block h-2.5 rounded-r"
              style={{ width: `${Math.max(1, (item.value / top) * 100)}%`, background: "var(--series-1)" }}
            />
          </span>
          <span className="tabular text-right text-ink">{format(item.value)}</span>
        </li>
      ))}
    </ul>
  );
}

/** Parts of each bar share one scale, and rows at zero stay visible, so a category with
 * nothing in it reads as zero and not as missing. */
export function StackedBarList<K extends string>({
  data,
  parts,
  name,
}: {
  data: ({ label: string } & Record<K, number>)[];
  parts: { key: K; label: string; color: string }[];
  name: string;
}) {
  const [active, setActive] = useState<string | null>(null);
  const total = (row: Record<K, number>) => parts.reduce((sum, part) => sum + row[part.key], 0);
  const top = niceMax(Math.max(1, ...data.map(total)));
  const describe = (row: Record<K, number>) => parts.map((part) => `${row[part.key].toLocaleString()} ${part.label.toLowerCase()}`).join(", ");

  return (
    <div>
      <ul className="mb-3 flex flex-wrap gap-4 text-xs text-ink-2">
        {parts.map((part) => (
          <li key={part.key} className="flex items-center gap-1.5">
            <span aria-hidden className="size-2.5 rounded-sm" style={{ background: part.color }} />
            {part.label}
          </li>
        ))}
      </ul>
      <ul aria-label={name} className="space-y-1">
        {data.map((row) => {
          const visible = parts.filter((part) => row[part.key] > 0);
          return (
            <li key={row.label} className="relative">
              <div
                role="img"
                tabIndex={0}
                aria-label={`${row.label}: ${describe(row)}`}
                className="grid grid-cols-[minmax(0,9.5rem)_1fr_2.5rem] items-center gap-2 rounded px-1 py-1 text-sm hover:bg-sunken"
                onPointerEnter={() => setActive(row.label)}
                onPointerLeave={() => setActive(null)}
                onFocus={() => setActive(row.label)}
                onBlur={() => setActive(null)}
              >
                <span className="truncate text-ink-2">{row.label}</span>
                <span className="flex h-3.5 items-stretch gap-0.5 overflow-hidden rounded-r bg-sunken">
                  {visible.map((part, index) => (
                    <span
                      key={part.key}
                      className={`bar-grow block ${index === visible.length - 1 ? "rounded-r" : ""}`}
                      style={{ width: `${(row[part.key] / top) * 100}%`, minWidth: 3, background: part.color }}
                    />
                  ))}
                </span>
                <span className="tabular text-right text-ink">{total(row).toLocaleString()}</span>
              </div>
              {active === row.label && (
                <p role="status" className="pointer-events-none absolute right-12 bottom-full z-10 rounded-md border border-line bg-surface px-2 py-1 text-xs whitespace-nowrap text-ink-2 shadow-sm">
                  <span className="font-medium text-ink">{row.label}:</span> {describe(row)}
                </p>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function StatTile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <p className="text-xs text-ink-3">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-ink">{value}</p>
      {note && <p className="mt-0.5 text-xs text-ink-3">{note}</p>}
    </div>
  );
}
