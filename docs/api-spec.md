# GovernanceIQ API Specification (Planning)

Base URL: `/api/v1`  
Protocol: HTTPS only (TLS required)  
Format: JSON request/response unless noted (file download endpoints return binary)

---

## 1) Global API conventions

### 1.1 Authentication

- Session-based bearer tokens.
- Token TTL: 8 hours.
- Revocable before expiry.
- Header: `Authorization: Bearer <token>`.

### 1.2 Authorization and role inheritance

- Hierarchical roles:
  - `administrator` inherits all `operations` + `user` capabilities
  - `operations` inherits all `user` capabilities
  - `user` is least privilege
- Audit log export endpoints are **administrator-only**.

### 1.3 Idempotency

- Header: `Idempotency-Key: <opaque-string>`
- Required on create/update operations that can duplicate outcomes:
  - ticket creation
  - backfill creation
  - report run creation
  - export job creation
- Deduplication window: 24 hours.
- Same key + same request hash returns original response.
- Same key + different payload returns `409 idempotency_key_conflict`.

### 1.4 Optimistic concurrency

- Mutable resources include `version`.
- Header required on mutable writes: `If-Match: "<version>"`.
- Mismatch returns `409 version_conflict`.

### 1.5 Pagination and filtering

- Cursor pagination default for list endpoints.
- Query model supports allowlisted operators only.
- No endpoint accepts raw SQL.

### 1.6 Error envelope

```json
{
  "error": {
    "code": "version_conflict",
    "message": "If-Match version does not match current resource version.",
    "details": {},
    "request_id": "req_..."
  }
}
```

---

## 2) Domain APIs

## 2.1 Authentication and sessions

### `POST /auth/login` (public)
Request:
```json
{ "username": "ops_anna", "password": "***" }
```
Response:
```json
{
  "token": "...",
  "expires_at": "2026-04-16T08:00:00Z",
  "user": { "id": "usr_...", "username": "ops_anna", "roles": ["operations"] }
}
```

### `POST /auth/logout` (authenticated)
- Revokes current session token.

### `GET /auth/sessions` (authenticated)
- Lists active and recently expired/revoked sessions for caller (admin can scope by user).

### `POST /auth/sessions/{session_id}/revoke` (self/admin)
- Revokes target session.

---

## 2.2 Users and roles

### `GET /users` (administrator)
### `POST /users` (administrator)
### `GET /users/{user_id}` (administrator)
### `PATCH /users/{user_id}` (administrator, `If-Match`)

### `POST /users/{user_id}/roles` (administrator)
Request:
```json
{ "roles": ["operations"] }
```

### `POST /permissions/grants` (administrator)
- Adds scoped permission grants when needed beyond base role inheritance.

---

## 2.3 Data catalog and metadata

### `GET /datasets` (user+)
- Users see only approved datasets within permission scope.

### `POST /datasets` (operations+)
### `GET /datasets/{dataset_id}` (user+ scoped)
### `PATCH /datasets/{dataset_id}` (operations+, `If-Match`)

### `GET /datasets/{dataset_id}/fields` (user+ scoped)
### `POST /datasets/{dataset_id}/fields` (operations+)

### `GET /datasets/{dataset_id}/metadata` (user+ scoped)
Response includes explicit fields:
```json
{
  "dataset_id": "dts_...",
  "owner": "registrar_office",
  "retention_class": "R7Y",
  "sensitivity_level": "high",
  "version": 3
}
```

### `PATCH /datasets/{dataset_id}/metadata` (operations+, `If-Match`)

---

## 2.4 Lineage tracking

### `GET /lineage/edges` (operations+)
### `POST /lineage/edges` (operations+)

Request:
```json
{
  "upstream_dataset_id": "dts_...",
  "downstream_dataset_id": "dts_...",
  "relation_type": "transform",
  "observed_at": "2026-04-15T01:59:00Z"
}
```

### `GET /lineage/graph?dataset_id=<id>&direction=upstream|downstream&depth=3` (operations+)
- Returns timestamped edges and nodes for impact tracing.

---

## 2.5 Institutional analytics querying (governed)

### `POST /analytics/datasets/{dataset_id}/query` (user+ scoped)

Purpose: query approved datasets via governed API filters/projections.  
Not allowed: raw SQL strings.

Guardrails:
- `limit` range: `1..5000` (default `500`)
- max filter clauses: `20`
- max sort fields: `3`
- server-side execution timeout: `30s`

Request:
```json
{
  "select": ["student_id", "program", "gpa"],
  "filters": [
    { "field": "program", "op": "in", "value": ["CS", "Math"] },
    { "field": "cohort_year", "op": "gte", "value": 2022 }
  ],
  "sort": [{ "field": "gpa", "direction": "desc" }],
  "limit": 500,
  "cursor": null
}
```

Response:
```json
{
  "rows": [ ... ],
  "next_cursor": "...",
  "applied_scope": { "dataset_id": "dts_...", "approved_only": true }
}
```

---

## 2.6 Data quality rules and inspections

### `GET /quality/rules` (operations+)
### `POST /quality/rules` (operations+)

Rule payload:
```json
{
  "dataset_id": "dts_...",
  "rule_type": "completeness",
  "severity": "P1",
  "threshold_value": 98.0,
  "field_ids": ["fld_..."],
  "config": {}
}
```

### `PATCH /quality/rules/{rule_id}` (operations+, `If-Match`)

### `POST /quality/inspections/trigger` (operations+)
- On-demand run for a dataset or scope.

### `GET /quality/inspections` (operations+)
### `GET /quality/inspections/{inspection_id}` (operations+)

Inspection response includes score + gate:
```json
{
  "id": "ins_...",
  "quality_score": 91.27,
  "gate_pass": false,
  "failed_p0_count": 1,
  "weights": { "P0": 50, "P1": 30, "P2": 15, "P3": 5 },
  "rule_results": [ ... ]
}
```

### `GET /quality/schedules` (operations+)
### `POST /quality/schedules` (operations+)
Default schedule if omitted:
```json
{ "cron_expr": "0 2 * * *", "timezone": "<local-timezone>" }
```

---

## 2.7 Issue tickets and remediation backfill

### `GET /tickets` (operations+)
### `POST /tickets` (operations+, idempotent)
- Auto-ticket creation from failed inspections may call this internally.
- Default due date = 7 calendar days.

Ticket states (exact):
- `open`
- `in_progress`
- `blocked`
- `resolved`
- `closed`

Allowed transitions:
- `open -> in_progress | blocked | resolved`
- `in_progress -> blocked | resolved`
- `blocked -> in_progress | resolved`
- `resolved -> closed | in_progress`
- `closed` is terminal (no reopen transition in v1)

### `POST /tickets/{ticket_id}/transition` (operations+, `If-Match`)
Request:
```json
{ "to_state": "in_progress", "reason": "Assigned to ETL owner for remediation" }
```

### `POST /tickets/{ticket_id}/assign` (operations+, `If-Match`)
### `POST /tickets/{ticket_id}/remediation-actions` (operations+, `If-Match`)

### `POST /tickets/{ticket_id}/backfills` (operations+, idempotent)
Request:
```json
{
  "input_fingerprint": "sha256:...",
  "parameters": { "batch": "2026-04-15", "strategy": "upsert" }
}
```
Response includes:
- affected record counts
- post-fix reinspection linkage (if run)

### `GET /backfills/{backfill_id}` (operations+)

---

## 2.8 Alumni content (poetry and tribute) + version governance

### `GET /content/entries` (user+)
- Users receive published-only by default.
- Operations/Admin can query drafts and history.

### `POST /content/entries` (operations+)
Request:
```json
{ "content_type": "tribute", "slug": "in-memory-of-...", "title": "In Memory Of ..." }
```

### `GET /content/entries/{entry_id}` (user+ scope rules)
### `PATCH /content/entries/{entry_id}` (operations+, `If-Match`)

### `GET /content/entries/{entry_id}/versions` (operations+; user gets published snapshot only)
### `POST /content/entries/{entry_id}/versions` (operations+)

### `POST /content/entries/{entry_id}/publish` (operations+, `If-Match`)
Rules:
- publish reason required and min length 10
- only one published version per entry at any time

Request:
```json
{
  "version_id": "ver_...",
  "reason": "Corrected tribute date and dedication details"
}
```

### `GET /content/entries/{entry_id}/diff?from_version_id=...&to_version_id=...` (operations+)
- Returns field-level diff including changed fields.

### `POST /content/entries/{entry_id}/rollback` (operations+, `If-Match`)
Rules:
- target version must be created within last 30 days
- reason required

---

## 2.9 Reporting and scheduled runs

### `GET /reports/definitions` (user+ scoped)
### `POST /reports/definitions` (operations+)
### `PATCH /reports/definitions/{id}` (operations+, `If-Match`)

### `POST /reports/runs` (user+ scoped, idempotent)
Request:
```json
{
  "report_definition_id": "rpt_...",
  "filters": { "cohort_year": 2025 },
  "time_window": { "start": "2026-01-01", "end": "2026-03-31" }
}
```

### `GET /reports/runs/{run_id}` (user+ scoped)

### `GET /reports/schedules` (user+ scoped)
### `POST /reports/schedules` (operations+)
### `GET /reports/schedules/{schedule_id}` (user+ scoped)
### `PATCH /reports/schedules/{schedule_id}` (operations+, `If-Match`)
- First-class persisted `ReportSchedule` records — see `apps/analytics/models.py::ReportSchedule`.
- Required field on create: `report_definition_id`. Optional: `cron_expr`
  (default `0 3 * * *`), `timezone` (default `UTC`), `active` (default `true`).
- The 5-field cron expression is validated server-side; malformed values
  return `400 invalid_cron`.

---

## 2.10 Export jobs

### `POST /reports/runs/{run_id}/exports` (operations+ scoped, idempotent)
Request:
```json
{ "format": "xlsx" }
```

Behavior:
- max 250,000 rows per file part
- if exceeded, split into `part_number` files under same export job
- retention: 30 days

Response:
```json
{
  "export_job_id": "exp_...",
  "format": "xlsx",
  "total_rows": 720000,
  "file_count": 3,
  "expires_at": "2026-05-15T10:20:00Z"
}
```

### `GET /exports/{export_job_id}` (scoped)
### `GET /exports/{export_job_id}/files` (scoped)
### `GET /exports/{export_job_id}/files/{part_number}/download` (scoped)

---

## 2.11 Audit and monitoring

### `GET /monitoring/metrics` (operations+)
Metrics include:
- ingestion success rate
- inspection success rate
- export success rate
- recommendation CTR (computed from local event logs only)

### `POST /monitoring/events` (internal producer, authenticated service account)
Allowed event types include:
- `ingestion_success`
- `ingestion_failure`
- `inspection_success`
- `inspection_failure`
- `export_success`
- `export_failure`
- `recommendation_impression`
- `recommendation_click`

### `GET /audit/logs` (administrator)
### `POST /audit/exports` (administrator-only)

---

## 3) HTTP status model (selected)

- `200` success read
- `201` created
- `202` accepted async run/export
- `400` validation_error
- `401` unauthorized
- `403` forbidden
- `404` not_found
- `409` version_conflict / idempotency_key_conflict / invalid_state_transition
- `410` export_expired
- `422` domain_rule_violation (e.g., rollback > 30 days)
- `429` throttled

---

## 4) Rate limiting defaults

- Per authenticated user: 120 requests/minute
- Per IP: 30 requests/minute

---

## 5) Non-functional API constraints

- All writes are audit-logged.
- Inspection results are immutable.
- Export access is permission scoped.
- API remains offline-self-sufficient; no external analytics dependency.

---

## 6) Runtime and operational contracts (cross-doc consistency)

- Primary runtime contract: `docker compose up --build`
- Database initialization path: `./init_db.sh`
- Broad test command contract: `./run_tests.sh`
- Backup/restore expectation: nightly encrypted backups + point-in-time restore support for previous 14 days
- No checked-in `.env` files; runtime secrets provided via mounted local secrets/bootstrap path
