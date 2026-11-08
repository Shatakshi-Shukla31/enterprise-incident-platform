import { humanize } from "./format";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** Names a group of facts in words, using this ticket's own values. */
export function describeFactor(factor: string, features: Record<string, string | number> = {}): string {
  switch (factor) {
    case "timing": {
      const day = DAYS[Number(features.day_of_week)] ?? "an unusual time";
      return `Raised on ${day}${Number(features.is_after_hours) ? ", outside office hours" : ""}`;
    }
    case "priority":
      return `Priority ${features.priority ?? ""}`.trim();
    case "queue":
      return `${features.team_backlog ?? "Several"} open tickets in the team's queue`;
    case "category":
      return `Category: ${humanize(String(features.category ?? ""))}`;
    case "team":
      return `Team: ${features.team ?? "unassigned"}`;
    case "channel":
      return `Reported through the ${String(features.channel ?? "usual")} channel`;
    case "description":
      return `A ${features.description_length ?? ""}-character description`.replace("A -", "A ");
    default:
      return humanize(factor);
  }
}

/** Percentage points, signed, so a reader sees direction and size at once. */
export function formatEffect(effect: number): string {
  const points = Math.round(Math.abs(effect) * 100);
  return `${effect > 0 ? "+" : "−"}${points} pts`;
}
