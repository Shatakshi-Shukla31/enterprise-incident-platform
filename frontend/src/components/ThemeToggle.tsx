import type { ReactNode } from "react";
import { useTheme, type Theme } from "../lib/theme";

const ICON_PROPS = {
  "aria-hidden": true,
  width: 14,
  height: 14,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round",
  strokeLinejoin: "round",
} as const;

const OPTIONS: { value: Theme; label: string; icon: ReactNode }[] = [
  {
    value: "light",
    label: "Light",
    icon: (
      <svg {...ICON_PROPS}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    ),
  },
  {
    value: "dark",
    label: "Dark",
    icon: (
      <svg {...ICON_PROPS}>
        <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
      </svg>
    ),
  },
];

export function ThemeToggle() {
  const [theme, setTheme] = useTheme();
  return (
    <div role="group" aria-label="Colour theme" className="inline-flex gap-0.5 rounded-md bg-sunken p-0.5 md:flex">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          aria-pressed={theme === option.value}
          onClick={() => setTheme(option.value)}
          className={`inline-flex items-center justify-center gap-1.5 rounded px-2 py-1 text-xs font-medium transition-colors md:flex-1 ${
            theme === option.value ? "bg-surface text-ink shadow-sm" : "text-ink-2 hover:text-ink"
          }`}
        >
          {option.icon}
          <span className="sr-only md:not-sr-only">{option.label}</span>
        </button>
      ))}
    </div>
  );
}
