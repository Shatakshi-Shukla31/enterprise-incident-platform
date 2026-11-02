# API

Base path: `/api/v1`. With the backend running in development, interactive docs are at `/docs`. A static schema is in [openapi.json](openapi.json). Production builds do not publish either.

## Conventions

- **Auth:** send `Authorization: Bearer <access_token>`.
- **Errors:** `{"detail": "message"}`. Validation errors return 422 with a list of problems.
- **Pagination:** `?page=1&page_size=20`, capped at 100. Responses contain `items`, `total`, `page` and `page_size`.
- **Tracing:** each response has an `X-Request-ID` header, which also appears in the logs.

| Status | Meaning |
| --- | --- |
| 400 | A business rule failed, such as resolving without notes |
| 401 | Missing or invalid credentials |
| 403 | Authenticated but not allowed |
| 404 | Not found, or not visible to you |
| 409 | Conflict, such as an illegal status change |
| 429 | Rate limited |

## Sign in and create an incident

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login \
  -d "username=user@example.com" -d "password=$DEMO_PASSWORD" | jq -r .access_token)

curl -s localhost:8000/api/v1/incidents \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "VPN keeps dropping", "description": "The tunnel drops every few minutes.", "impact": "high", "urgency": "medium"}'
```

The response includes the derived priority and SLA targets, plus the predicted category. Requesters do not see confidence or risk scores.

## Authentication

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/auth/login` | Sign in with form fields. Sets the refresh cookie. | Public |
| POST | `/auth/refresh` | Rotate the refresh token | Cookie |
| POST | `/auth/logout` | End the session | Cookie |
| GET | `/auth/me` | Current user | Any |
| POST | `/auth/me/password` | Change password and end other sessions | Any |

## Incidents

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/incidents` | Create, triage and start the SLA clock | Any |
| GET | `/incidents` | List within your scope | Any |
| GET | `/incidents/{id}` | Read | Scope |
| PATCH | `/incidents/{id}` | Edit details. Recalculates priority and SLA. | Staff |
| POST | `/incidents/{id}/status` | Change status | Staff |
| POST | `/incidents/{id}/assign` | Set team or assignee | Staff |
| POST | `/incidents/{id}/escalate` | Escalate with a reason | Staff |
| POST | `/incidents/{id}/category` | Correct the predicted category | Staff |
| GET, POST | `/incidents/{id}/comments` | Read or add comments. Internal notes are staff only. | Scope |
| GET | `/incidents/{id}/audit` | Audit history | Staff |
| GET | `/incidents/{id}/predictions` | Stored model outputs | Staff |

List filters: `status` and `priority` (repeatable), `category`, `team_id`, `assignee_id`, `breached`, `open_only`, `q` (text or ticket number), `sort` (`created_at`, `updated_at`, `priority`, `resolution_due_at`, `sla_risk_score`), and `order`.

Status flow: `new` → `assigned` → `in_progress` ↔ `on_hold` → `resolved` → `closed`. A resolved ticket can return to `in_progress`. Resolving needs `resolution_notes`. Time on hold extends the SLA targets.

## AI

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| POST | `/incidents/{id}/ai/suggest` | Cited resolution for an incident | Staff |
| GET | `/incidents/{id}/ai/related` | Similar resolved incidents | Staff |
| POST | `/ai/chat` | Ask the assistant | Any |
| GET | `/ai/conversations` | Your conversations | Any |
| GET | `/ai/conversations/{id}` | One of your conversations | Owner |
| POST | `/ai/recommendations/{id}/feedback` | Rate an answer | Owner |

Answer shape:

```json
{
  "recommendation_id": 12,
  "answer": "- Switch the protocol from UDP to TCP in the client settings. [S1]",
  "citations": [{"id": "S1", "title": "VPN disconnects repeatedly", "source_type": "kb_article",
                 "source_ref": "KB-1001", "similarity": 0.71, "excerpt": "...",
                 "document_id": 1, "chunk_id": 1}],
  "insufficient_evidence": false,
  "provider": "extractive",
  "latency_ms": 180,
  "related_incidents": [],
  "suggested_actions": [{"runbook_id": 2, "name": "Flush DNS cache", "requires_approval": true}]
}
```

When `insufficient_evidence` is `true`, `citations` is empty and `answer` explains that nothing reliable was found.

## Knowledge

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/knowledge/documents` | Documents you can read | Staff |
| POST | `/knowledge/documents` | Add or update, with chunking and screening | Manager |
| DELETE | `/knowledge/documents/{id}` | Remove | Admin |
| POST | `/knowledge/search` | Filtered similarity search | Any |

The ingest response reports `flagged_chunks`, the number quarantined as possible prompt injection.

## Remediation

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/remediation/runbooks` | Allow-listed runbooks | Staff |
| POST | `/incidents/{id}/remediations` | Request one | Staff |
| GET | `/incidents/{id}/remediations` | Requests for an incident | Staff |
| GET | `/remediation/requests` | All within scope | Staff |
| POST | `/remediation/requests/{id}/decision` | Approve or reject | Manager, not the requester |

## Administration

| Method | Path | Purpose | Access |
| --- | --- | --- | --- |
| GET | `/users` | List | Staff |
| POST | `/users` | Create | Admin |
| PATCH | `/users/{id}` | Change role, team or status | Admin |
| GET | `/teams` | List | Any |
| POST | `/teams` | Create | Manager |
| GET | `/notifications` | Your notifications | Any |
| GET | `/notifications/summary` | Unread and read counts by type and by ticket status | Any |
| POST | `/notifications/{id}/read`, `/notifications/read-all` | Mark as read | Any |
| GET | `/analytics/dashboard?days=30` | Dashboard data | Manager |

## Operations

These are outside `/api/v1`.

| Path | Purpose |
| --- | --- |
| `/health` | The process is alive |
| `/ready` | Database connectivity and loaded model versions |
| `/metrics` | Prometheus metrics. Needs `Authorization: Bearer $METRICS_TOKEN`, and returns 404 otherwise. |
