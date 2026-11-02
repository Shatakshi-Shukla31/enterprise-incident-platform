import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnswerText, Citations } from "../components/Answer";
import { BarList, ChartCard, LineChart, StackedBarList, niceMax } from "../components/charts";
import { ThemeToggle } from "../components/ThemeToggle";
import { Pagination, PriorityBadge, RiskLabel } from "../components/ui";
import { dueIn, humanize, percent } from "../lib/format";
import type { Citation } from "../lib/types";

const citation: Citation = {
  id: "S1",
  document_id: 1,
  chunk_id: 1,
  title: "VPN article",
  source_type: "kb_article",
  source_ref: "KB-1001",
  similarity: 0.71,
  excerpt: "Update the client",
};

describe("AnswerText", () => {
  it("links known citations", () => {
    render(<AnswerText text="Update the client [S1]." citations={[citation]} />);
    expect(screen.getByRole("link", { name: "S1" })).toHaveAttribute("href", "#S1");
  });

  it("leaves unknown citation markers as plain text", () => {
    render(<AnswerText text="Reinstall [S9]." citations={[citation]} />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders document text as text, never as markup", () => {
    const { container } = render(<AnswerText text={'<img src=x onerror="alert(1)"> [S1]'} citations={[citation]} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container).toHaveTextContent("<img src=x");
  });
});

describe("Citations", () => {
  it("shows where a claim came from", () => {
    render(<Citations citations={[citation]} />);
    expect(screen.getByText("VPN article")).toBeInTheDocument();
    expect(screen.getByText(/KB-1001 · Knowledge article · similarity 0.71/)).toBeInTheDocument();
  });

  it("renders nothing without citations", () => {
    const { container } = render(<Citations citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("charts", () => {
  it("offers every value in a table view", async () => {
    render(
      <ChartCard title="Volume" table={{ headers: ["Date", "Opened"], rows: [["2026-01-01", 5]] }}>
        <BarList data={[{ label: "Network", value: 5 }]} />
      </ChartCard>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByRole("cell", { name: "2026-01-01" })).toBeInTheDocument();
  });

  it("keeps the axis close to the data", () => {
    expect(niceMax(21)).toBe(25);
    expect(niceMax(40)).toBe(40);
    expect(niceMax(120)).toBe(150);
    expect(niceMax(0)).toBe(1);
  });

  it("labels each line in a legend", () => {
    render(
      <LineChart
        data={[{ date: "2026-01-01", created: 2, resolved: 1 }]}
        series={[
          { key: "created", label: "Opened", color: "#000" },
          { key: "resolved", label: "Resolved", color: "#111" },
        ]}
      />,
    );
    expect(screen.getByText("Opened")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName(/Opened and Resolved/);
  });
});

describe("StackedBarList", () => {
  const parts = [
    { key: "unread", label: "Unread", color: "#000" },
    { key: "read", label: "Read", color: "#111" },
  ] as const;
  const data = [
    { label: "SLA breached", unread: 6, read: 2 },
    { label: "Comment", unread: 0, read: 0 },
  ];

  it("names both parts in a legend and gives each row a full description", () => {
    render(<StackedBarList name="By type" data={data} parts={[...parts]} />);
    expect(screen.getByText("Unread")).toBeInTheDocument();
    expect(screen.getByText("Read")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "SLA breached: 6 unread, 2 read" })).toBeInTheDocument();
  });

  it("keeps a row at zero visible and draws no bar for it", () => {
    render(<StackedBarList name="By type" data={data} parts={[...parts]} />);
    const row = screen.getByRole("img", { name: "Comment: 0 unread, 0 read" });
    expect(row).toHaveTextContent("0");
    expect(row.querySelector(".bar-grow")).toBeNull();
  });

  it("shows the same detail on keyboard focus as on hover", async () => {
    render(<StackedBarList name="By type" data={data} parts={[...parts]} />);
    await userEvent.tab();
    expect(screen.getByRole("status")).toHaveTextContent("SLA breached: 6 unread, 2 read");
  });
});

describe("ThemeToggle", () => {
  function stubStorage(setItem?: () => void) {
    const items = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => items.get(key) ?? null,
      setItem: setItem ?? ((key: string, value: string) => void items.set(key, value)),
    });
  }

  beforeEach(() => stubStorage());

  afterEach(() => {
    delete document.documentElement.dataset.theme;
  });

  it("applies the choice and remembers it", async () => {
    const { unmount } = render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");

    unmount();
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "false");
  });

  it("switches back to light", async () => {
    localStorage.setItem("theme", "dark");
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("still switches when storage is blocked", async () => {
    stubStorage(() => {
      throw new Error("blocked");
    });
    render(<ThemeToggle />);
    await userEvent.click(screen.getByRole("button", { name: "Dark" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
});

describe("badges and pagination", () => {
  it("shows risk in words as well as colour", () => {
    render(<RiskLabel score={0.82} />);
    expect(screen.getByText("High · 82%")).toBeInTheDocument();
  });

  it("shows a dash for an unscored incident", () => {
    render(<RiskLabel score={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("renders the priority", () => {
    render(<PriorityBadge priority="P1" />);
    expect(screen.getByText("P1")).toBeInTheDocument();
  });

  it("disables navigation past the ends", async () => {
    const onChange = vi.fn();
    render(<Pagination page={1} pageSize={20} total={45} onChange={onChange} />);
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(onChange).toHaveBeenCalledWith(2);
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
  });
});

describe("format helpers", () => {
  it("describes time until a deadline", () => {
    const now = new Date("2026-01-01T12:00:00Z");
    expect(dueIn("2026-01-01T12:30:00Z", now)).toEqual({ label: "in 30m", overdue: false });
    expect(dueIn("2026-01-01T09:00:00Z", now)).toEqual({ label: "3h overdue", overdue: true });
    expect(dueIn("2026-01-05T12:00:00Z", now)).toEqual({ label: "in 4d", overdue: false });
  });

  it("humanizes identifiers", () => {
    expect(humanize("in_progress")).toBe("In progress");
    expect(humanize(null)).toBe("—");
  });

  it("formats percentages and missing values", () => {
    expect(percent(0.125, 1)).toBe("12.5%");
    expect(percent(null)).toBe("—");
  });
});
