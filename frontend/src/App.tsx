import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { isManager, isStaff, useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/ui";
import { ApprovalsPage } from "./pages/Approvals";
import { AssistantPage } from "./pages/Assistant";
import { DashboardPage } from "./pages/Dashboard";
import { IncidentDetailPage } from "./pages/IncidentDetail";
import { IncidentsPage } from "./pages/Incidents";
import { KnowledgePage } from "./pages/Knowledge";
import { LoginPage } from "./pages/Login";
import { NewIncidentPage } from "./pages/NewIncident";
import { NotificationsPage } from "./pages/Notifications";
import { UsersPage } from "./pages/Users";

// Hides navigation only. Every rule is enforced again by the API.
function Guard({ allow, children }: { allow: boolean; children: ReactNode }) {
  return allow ? children : <Navigate to="/incidents" replace />;
}

export function App() {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Restoring session…" />;
  if (!user) return <LoginPage />;

  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/incidents" replace />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/new" element={<NewIncidentPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="notifications" element={<NotificationsPage />} />
        <Route path="dashboard" element={<Guard allow={isManager(user.role)}><DashboardPage /></Guard>} />
        <Route path="approvals" element={<Guard allow={isStaff(user.role)}><ApprovalsPage /></Guard>} />
        <Route path="knowledge" element={<Guard allow={isStaff(user.role)}><KnowledgePage /></Guard>} />
        <Route path="users" element={<Guard allow={user.role === "admin"}><UsersPage /></Guard>} />
        <Route path="*" element={<Navigate to="/incidents" replace />} />
      </Route>
    </Routes>
  );
}
