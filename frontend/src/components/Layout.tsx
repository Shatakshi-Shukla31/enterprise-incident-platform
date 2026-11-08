import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { isManager, isStaff, useAuth } from "../auth/AuthContext";
import { api } from "../lib/api";
import { humanize } from "../lib/format";
import type { Notification } from "../lib/types";
import { ThemeToggle } from "./ThemeToggle";
import { Button } from "./ui";

export function Layout() {
  const { user, signOut } = useAuth();
  const { data: unread } = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => api.get<Notification[]>("/notifications?unread_only=true&limit=100"),
    refetchInterval: 30000,
  });

  const links = [
    { to: "/incidents", label: "Incidents", show: true },
    { to: "/assistant", label: "Assistant", show: true },
    { to: "/notifications", label: unread?.length ? `Notifications (${unread.length})` : "Notifications", show: true },
    { to: "/dashboard", label: "Dashboard", show: isManager(user?.role) },
    { to: "/approvals", label: "Approvals", show: isStaff(user?.role) },
    { to: "/knowledge", label: "Knowledge", show: isStaff(user?.role) },
    { to: "/users", label: "Users", show: user?.role === "admin" },
  ];

  return (
    <div className="min-h-screen md:grid md:grid-cols-[220px_1fr]">
      <aside className="border-b border-line bg-surface p-3 md:sticky md:top-0 md:flex md:h-screen md:flex-col md:border-r md:border-b-0">
        <p className="px-2 py-1 text-sm font-semibold text-ink">Incident Platform</p>
        <nav aria-label="Main" className="mt-1 flex gap-1 overflow-x-auto md:mt-4 md:flex-col md:overflow-visible">
          {links
            .filter((link) => link.show)
            .map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  `whitespace-nowrap rounded-md px-2 py-1.5 text-sm ${isActive ? "bg-accent-soft font-medium text-ink" : "text-ink-2 hover:bg-sunken"}`
                }
              >
                {link.label}
              </NavLink>
            ))}
        </nav>
        <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-3 md:mt-auto md:block">
          <div className="min-w-0">
            <p className="truncate px-2 text-sm text-ink">{user?.full_name}</p>
            <p className="truncate px-2 text-xs text-ink-3">{humanize(user?.role)}</p>
          </div>
          <div className="flex shrink-0 items-center gap-1 md:mt-2 md:block md:space-y-1 md:px-2">
            <ThemeToggle />
            <Button variant="ghost" className="md:w-full md:justify-start md:!px-2" onClick={() => void signOut()}>
              Sign out
            </Button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 p-4 md:p-6">
        <div className="mx-auto max-w-6xl">
          {user?.is_demo && (
            <p role="note" className="mb-4 rounded-md border border-line bg-accent-soft px-3 py-2 text-sm text-ink">
              You're exploring a read-only demo with made-up data. To raise your own tickets, sign out and create an account.
            </p>
          )}
          <Outlet />
        </div>
      </main>
    </div>
  );
}
