export type Role = "requester" | "agent" | "manager" | "admin";
export type Status = "new" | "assigned" | "in_progress" | "on_hold" | "resolved" | "closed";
export type Priority = "P1" | "P2" | "P3" | "P4";
export type Level = "high" | "medium" | "low";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: Role;
  team_id: number | null;
  is_active: boolean;
  is_demo?: boolean;
}

export interface Team {
  id: number;
  name: string;
  description: string;
  is_active: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Incident {
  id: number;
  number: string;
  title: string;
  description: string;
  impact: Level;
  urgency: Level;
  priority: Priority;
  status: Status;
  channel: string;
  category: string | null;
  requester: { id: number; full_name: string };
  assignee: { id: number; full_name: string } | null;
  team: { id: number; name: string } | null;
  created_at: string;
  updated_at: string;
  response_due_at: string;
  resolution_due_at: string;
  first_response_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  sla_breached: boolean;
  escalation_level: number;
  resolution_notes: string | null;
  category_confidence: number | null;
  category_corrected: boolean;
  sla_risk_score: number | null;
}

export interface Comment {
  id: number;
  body: string;
  is_internal: boolean;
  created_at: string;
  author: { id: number; full_name: string };
}

export interface AuditEntry {
  id: number;
  action: string;
  changes: Record<string, unknown>;
  created_at: string;
  actor: { id: number; full_name: string } | null;
}

export interface Prediction {
  id: number;
  kind: "category" | "routing" | "sla_risk";
  model_version: string;
  value: string;
  confidence: number;
  details: {
    alternatives?: { label: string; confidence: number }[];
    features?: Record<string, string | number>;
    factors?: RiskFactor[];
  };
  accepted: boolean | null;
  corrected_value: string | null;
  created_at: string;
}

export interface RiskFactor {
  factor: string;
  effect: number;
}

export interface Citation {
  id: string;
  document_id: number;
  chunk_id: number;
  title: string;
  source_type: string;
  source_ref: string;
  similarity: number;
  excerpt: string;
}

export interface Answer {
  recommendation_id: number;
  answer: string;
  citations: Citation[];
  insufficient_evidence: boolean;
  provider: string;
  latency_ms: number;
  related_incidents: { incident_id: number | null; source_ref: string; title: string; similarity: number }[];
  suggested_actions: { runbook_id: number; name: string; description: string; requires_approval: boolean }[];
}

export interface ChatAnswer extends Answer {
  conversation_id: number;
}

export interface Conversation {
  id: number;
  title: string;
  incident_id: number | null;
  created_at: string;
}

export interface ConversationDetail extends Conversation {
  messages: {
    role: string;
    content: string;
    created_at: string;
    citations: Citation[];
    insufficient_evidence: boolean;
  }[];
}

export interface Notification {
  id: number;
  incident_id: number | null;
  type: string;
  title: string;
  body: string;
  created_at: string;
  read_at: string | null;
}

export interface NotificationCount {
  key: string;
  unread: number;
  read: number;
}

export interface NotificationSummary {
  total: number;
  unread: number;
  by_type: NotificationCount[];
  by_status: NotificationCount[];
}

export interface Runbook {
  id: number;
  key: string;
  name: string;
  description: string;
  category: string | null;
}

export interface Remediation {
  id: number;
  incident_id: number;
  status: string;
  target: string;
  justification: string;
  decision_note: string | null;
  result: Record<string, unknown>;
  created_at: string;
  decided_at: string | null;
  finished_at: string | null;
  runbook: Runbook;
  requested_by: { id: number; full_name: string };
  decided_by: { id: number; full_name: string } | null;
}

export interface KnowledgeDocument {
  id: number;
  source_type: string;
  source_ref: string;
  title: string;
  category: string | null;
  access_level: string;
  team_id: number | null;
  created_at: string;
}

export interface OfflineModel {
  version: string;
  selected_model: string;
  synthetic_data: boolean;
  test: Record<string, number>;
}

export interface Dashboard {
  days: number;
  summary: {
    created: number;
    resolved: number;
    open_now: number;
    open_breached: number;
    open_high_risk: number;
    sla_compliance: number | null;
    mean_resolution_hours: number | null;
  };
  trend: { date: string; created: number; resolved: number }[];
  by_category: { category: string; count: number }[];
  sla_by_priority: { priority: string; resolved: number; breached: number; compliance: number | null }[];
  resolution_by_team: { team: string; resolved: number; mean_hours: number }[];
  ml_live: Record<string, unknown>;
  ml_offline: Record<string, OfflineModel | null>;
  ai_usage: {
    recommendations: number;
    insufficient_evidence_rate: number | null;
    rated: number;
    helpful_rate: number | null;
    p95_latency_ms: number | null;
  };
}
