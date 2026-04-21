# GovernanceIQ — Education Data & Content Governance API

**Project type: server**

Backend-only Django REST Framework + MySQL service that centralizes
institutional analytics and data/content governance operations for an
offline-deployable environment.

The API covers the locked product scope:

- Authentication and sessions (8h TTL, revocable bearer tokens)
- Users and hierarchical roles (`administrator` ⊃ `operations` ⊃ `user`)
- Data catalog, fields, and metadata (`owner`, `retention_class`,
  `sensitivity_level`)
- Data quality rules, scoring (P0=50/P1=30/P2=15/P3=5), and inspections (with
  default nightly schedule at `02:00` local time and P0 hard-fail gate)
- Issue tickets and remediation backfill with an exact 5-state state machine
  (`open`, `in_progress`, `blocked`, `resolved`, `closed`)
- Lineage tracking with timestamped edges
- Alumni content (`poetry` and `tribute`) with versions, publish/rollback,
  ≥10-character publish reason, and a 30-day rollback window
- Reporting, scheduled runs (first-class persisted `ReportSchedule`), and
  governed analytics queries (allowlisted filter grammar; no raw SQL)
- Exports with multipart split at 250,000 rows/file in **real CSV** or
  **real Office Open XML XLSX** (openpyxl)
- Audit logs (append-only) and monitoring metrics including recommendation CTR
  computed from local impression/click event logs

This repo contains no checked-in `.env*` files. All runtime secrets and the
local TLS certificate are produced at container startup by
`docker/bootstrap.sh` (a thin shell wrapper around the
`bootstrap_runtime` Django management command) and mounted into the Docker
volume `runtime_secrets`.

---

## Run it (TLS-terminated, single command)

The single primary runtime contract is:

```bash
docker-compose up --build
```

If your Docker installation uses Compose v2 plugin syntax, the equivalent is:

```bash
docker compose up --build
```

This starts:

- `bootstrap` (one-shot) — generates ephemeral runtime secrets *and a real
  self-signed RSA-2048 X.509 cert + key* into the `runtime_secrets` volume
- `db` — MySQL 8.0 with binary logging enabled
  (`--log-bin --binlog-format=ROW --binlog-expire-logs-seconds=1209600
  --gtid-mode=ON --enforce-gtid-consistency=ON`) for the **14-day PITR**
  retention contract
- `api` — Gunicorn + Django REST Framework, listens internally on `8000`
- `proxy` — nginx terminating TLS on `443` (host port `8443`),
  redirecting HTTP→HTTPS, enforcing TLS 1.2/1.3 only, with HSTS

Reach the API at:

```
https://localhost:8443/api/v1/...
```

The cert is self-signed for `governanceiq.local`; for local development you
will need `--insecure`/`-k` (or pin the cert from the `runtime_secrets`
volume into your trust store).

## Verification (how to confirm it works)

Use this exact flow after the stack is up.

1. Create the first administrator (one time on a fresh DB):

```bash
docker-compose exec api python manage.py bootstrap_admin \
    --username admin --password 'AdminPass!1234'
```

2. Login and capture a bearer token:

```bash
TOKEN=$(curl -sk https://localhost:8443/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"AdminPass!1234"}' | python -c 'import json,sys; print(json.load(sys.stdin)["token"])')
```

3. Call a protected endpoint with that token:

```bash
curl -sk https://localhost:8443/api/v1/monitoring/metrics \
  -H "Authorization: Bearer $TOKEN"
```

Expected result: HTTP `200` with a JSON body containing metrics fields such as
`recommendation_impressions`, `recommendation_clicks`, and
`recommendation_ctr`.

To initialize/refresh the database state explicitly:

```bash
./init_db.sh
```

This is the only project-standard database initialization path.

### First-run: create the initial administrator

A fresh deployment has no users. Create the first administrator via the
bootstrap command (requires the stack to be running):

```bash
docker compose exec api python manage.py bootstrap_admin \
    --username admin --password '<strong-password-here>'
```

This command is **idempotent and one-shot**: it refuses to create a second
administrator unless `--force` is supplied (with a visible warning). The
password must be at least 12 characters. After this single step the
operator can log in via `POST /api/v1/auth/login` and use the admin API to
create further users.

### Demo credentials (all roles)

Authentication is required. Use the following demo accounts:

| Role | Username | Password |
|---|---|---|
| administrator | `admin` | `AdminPass!1234` |
| operations | `ops_demo` | `OpsPass!1234` |
| user | `user_demo` | `UserPass!1234` |

Create the non-admin demo users once, using the admin token:

```bash
# operations user
curl -sk https://localhost:8443/api/v1/users \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"ops_demo","password":"OpsPass!1234","roles":["operations"]}'

# basic user
curl -sk https://localhost:8443/api/v1/users \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"username":"user_demo","password":"UserPass!1234","roles":["user"]}'
```

## Test it

The single primary broad test command is:

```bash
./run_tests.sh
```

By default this builds the project's Dockerfile, brings up a real MySQL 8
container via docker-compose, runs migrations, and executes the full
`pytest` suite under `Unit_tests/` and `api_test/` against that real
database. It then tears the stack down.

### Test policy

- No mock tests, no fake services, no stubbed integration tests
- No `unittest.mock`, no `monkeypatch` substitution of behavior
- No `requests-mock` / `responses` / `HTTPretty` / VCR
- No SQLite substitution for MySQL behavior
- API tests exercise the real Django app against a real MySQL database
- Unit tests run real domain logic (scoring, gate, state machine, encryption,
  TLS handshake, backup encrypt/decrypt, mysqldump+restore, etc.)

The TLS proxy integration test in
`api_test/test_tls_proxy_integration.py` boots the real `docker compose`
stack and performs a real HTTPS round-trip through nginx into the api. It
auto-skips when the host running pytest doesn't have Docker available
(documented in the test file).

## Scheduler

Scheduled work in this system is driven by a real, in-process scheduler — not
by external cron. `docker compose up --build` brings up a `scheduler` service
that calls the `tick_all` function once per minute (configurable via
`--interval`).

- **Inspection schedules** (`apps.quality.models.InspectionSchedule`) —
  default cron `0 2 * * *` (nightly 02:00 in the schedule's local
  timezone, per the spec). When due, the scheduler runs the same
  `run_inspection` path the manual `POST /quality/inspections/trigger`
  endpoint uses, so a scheduled inspection produces a real
  `InspectionRun`, evaluates rules, applies the P0 hard-fail gate, and
  may auto-open tickets.
- **Report schedules** (`apps.analytics.models.ReportSchedule`) — default
  cron `0 3 * * *`. When due, the scheduler runs the governed query
  defined by the bound `ReportDefinition` and persists a real
  `ReportRun` (status `complete`, with `total_rows` and `rows_snapshot`).
- **State maintenance** — both kinds advance `next_run_at` (via
  `croniter`-evaluated cron + timezone) and stamp `last_enqueued_at`
  inside the same database transaction as the work, so the scheduler is
  idempotent and re-running a tick immediately fires nothing.
- **Manual flush** — operators can run a single tick on demand:
  `docker compose exec api python manage.py run_scheduler_tick [--json]`.

To install on host crontab instead of running the in-stack scheduler
container, the equivalent line is:

```cron
* * * * * cd /opt/governanceiq && docker compose run --rm -e SKIP_MIGRATE=1 api python manage.py run_scheduler_tick
```

## Backup, restore, and PITR

- **Encrypted backup** — `python manage.py run_backup [--label LABEL]`
  shells `mysqldump`, encrypts the dump with AES-256-GCM under
  `BACKUP_ENCRYPTION_KEY` (loaded from
  `/run/runtime-secrets/backup_encryption_key`), and writes the artifact
  plus a JSON manifest to `BACKUP_STORAGE_DIR`
  (`/var/lib/governanceiq/backups`). Operator wrapper:
  `./scripts/backup_now.sh`.
- **Nightly schedule (in-service)** — the scheduler service automatically runs
  encrypted backups on a configurable cron schedule (default `0 1 * * *` =
  01:00 local time daily). Cadence is configurable via the `BACKUP_CRON_EXPR`
  and `BACKUP_CRON_TZ` environment variables. **Precedence:** env vars are
  applied only on first creation of the `backup_schedule_state` DB row;
  after that the DB values persist across restarts, so operator overrides
  (e.g. via admin or direct SQL) are not reset by env changes. To re-seed
  from env, delete the `backup_schedule_state` row and restart. The backup
  schedule state is exposed in the monitoring metrics endpoint
  (`GET /api/v1/monitoring/metrics` → `backup_schedule` object).
  Manual host cron is still available: `./scripts/install_backup_cron.sh`.
- **Restore** — `python manage.py restore_backup <artifact_path>
  --target-database <name>` decrypts and applies the dump back into the
  named database. Operator wrapper: `./scripts/restore_backup.sh`.
- **PITR (14 days)** — MySQL is launched with `--log-bin`,
  `--binlog-format=ROW`, `--binlog-expire-logs-seconds=1209600`, and GTID
  mode on. Use `python manage.py show_pitr` to confirm the live retention
  and list current binlogs.
- **PITR operator command** — `python manage.py run_pitr
  --target-time <ISO-8601> --target-database <name> [--source-database <name>]
  [--dry-run] [--json]`. The command:
  1. enforces the 14-day window
  2. picks the latest backup at or before `--target-time`
  3. restores it into `--target-database`
  4. streams binlogs via `mysqlbinlog --read-from-remote-server` filtered
     to `[backup_time, target_time)`
  5. uses `--rewrite-db source->target` when source ≠ target so events
     land in the recovery database
  6. uses `--skip-gtids` so events apply as fresh transactions on the
     same server
  Operator wrapper: `./scripts/pitr_restore.sh`. Use `--dry-run` to see
  the exact plan (base backup label, binlog list, time window, target db)
  without touching MySQL.

  Example operator flow:

  ```bash
  # 1. one-off: create the target DB (project-managed command)
  docker compose exec api python manage.py create_pitr_database \
      --database-name gi_pitr
  # 2. preview the plan
  ./scripts/pitr_restore.sh --target-time 2026-04-15T16:30:00Z \
                            --target-database gi_pitr --dry-run
  # 3. execute
  ./scripts/pitr_restore.sh --target-time 2026-04-15T16:30:00Z \
                            --target-database gi_pitr
  ```

## Repo contents

```
governanceiq/        Django project (settings, urls, wsgi)
apps/
  platform_common/   IDs, errors, idempotency, OCC, encryption, middleware,
                     audit helper, rate limiter, TLS bootstrap, backup
                     encrypt/decrypt + restore + PITR helpers, management
                     commands (wait_for_db, seed_roles, bootstrap_runtime,
                     run_backup, restore_backup, show_pitr)
  identity/          Users, roles, sessions; login/logout/revoke endpoints
  authorization/     Role inheritance + capability resolution; grants endpoint
  catalog/           Datasets, fields, metadata, persisted dataset rows
  lineage/           Lineage edges + graph traversal endpoints
  quality/           Quality rules, inspections, scoring, schedules
  tickets/           Tickets, transitions, remediation, backfill (idempotent)
  content/           Poetry/tribute entries, versions, publish/rollback/diff
  analytics/         Report definitions/runs + ReportSchedule + governed query
  exports/           Multipart export jobs (real CSV / real XLSX) with retention
  audit_monitoring/  Append-only audit log, event log, metrics, audit export
docker/
  bootstrap.sh       Wrapper that runs the bootstrap_runtime command
  entrypoint.sh      api container entrypoint
  mysql/             MySQL Dockerfile + initdb script
  proxy/             nginx TLS-terminating reverse proxy
scripts/             Operator wrappers (backup, restore, install cron)
Unit_tests/          Real unit tests (no mocks)
api_test/            Real API tests (no mocks)
docker-compose.yml   docker compose up --build runtime contract
Dockerfile           api/worker image
init_db.sh           Standard DB initialization path
run_tests.sh         Single broad test command
```

## Offline / runtime assumptions

- Single-host deployment: `bootstrap` + MySQL + api + nginx proxy + local
  attached storage
- Local mounts:
  - `/var/lib/governanceiq/exports` — export artifacts (30-day retention)
  - `/var/lib/governanceiq/backups` — encrypted nightly backups
- TLS is terminated at the `proxy` for client ingress, and the internal
  `proxy -> api` hop is also HTTPS with certificate verification enabled;
  plaintext HTTP is used only for redirect listener behavior (`80 -> 443`),
  not for application transport
- No external analytics service: monitoring metrics including CTR are
  computed from local `event_logs` only

## Secrets, certs, and runtime

- No `.env`, `.env.local`, `.env.example`, or similar files are checked in
- `docker/bootstrap.sh` (Django command `bootstrap_runtime`) generates these
  ephemeral runtime materials on container startup if they are not already
  present in the `runtime_secrets` Docker volume:
  - `django_secret_key`
  - `data_encryption_key`
  - `mysql_root_password`
  - `mysql_user_password`
  - `backup_encryption_key`
  - `tls_cert.pem` (X.509, RSA-2048, valid 365 days, SAN includes
    `governanceiq.local`, `localhost`, `proxy`)
  - `tls_key.pem`
- These are mounted at `/run/runtime-secrets/...` and consumed via
  `*_FILE` environment variables in `docker-compose.yml`
- **File permissions**: Runtime secrets (`django_secret_key`,
  `data_encryption_key`, `mysql_root_password`, `mysql_user_password`,
  `backup_encryption_key`) and the TLS private key (`tls_key.pem`) are
  written with mode `0600` (owner read/write only). The TLS certificate
  (`tls_cert.pem`) is `0644` since it is not secret material. This follows
  the principle of least privilege for secret files.
- The bootstrap path is **for local development only** — production secret
  material AND production TLS certificates must be delivered by the
  deployment platform's secret/cert-management path (Vault, KMS, ACME, etc.)

## Security and governance notes

- Argon2id password hashing (with PBKDF2-SHA256 fallback)
- **AES-256-GCM encryption at rest** for sensitive domain fields via
  `EncryptedTextField` (`apps.platform_common.fields`). Currently applied to:
  - `ContentVersion.body` — content bodies are stored encrypted.
  - `DatasetMetadata.owner` — governance metadata owner is encrypted.
  The field is reusable: apply `EncryptedTextField` to any model field to
  enable transparent encrypt-on-write / decrypt-on-read using the
  `DATA_ENCRYPTION_KEY` / `DATA_ENCRYPTION_KEY_ID` configuration. Legacy
  plaintext rows (not starting with `v1.`) are returned as-is, so the field
  is safe to deploy before a data backfill migration.
- AES-256-GCM encrypted nightly backups + tamper-evident SHA-256 manifest
- **TLS on all network hops** — external clients connect to the nginx
  proxy over TLS 1.2/1.3 with HSTS + plain-HTTP→HTTPS redirect. The
  internal nginx→api hop is **also TLS-protected**: gunicorn serves HTTPS
  using the same runtime cert/key material, and nginx verifies the upstream
  certificate against the self-signed CA (`proxy_ssl_verify on`,
  `proxy_ssl_trusted_certificate`). The self-signed cert includes the
  `api` DNS SAN so hostname verification succeeds. This means no network
  hop in the Docker topology carries plaintext HTTP traffic.
- Optimistic concurrency on every mutable resource via `If-Match: "<version>"`
- Idempotency on duplicate-prone POSTs (24h dedupe window) via the
  `Idempotency-Key` header
- Rate limiting defaults: 120 req/min/user, 30 req/min/IP
- **Client IP trust model** — a centralized `client_ip()` helper
  (`apps.platform_common.client_ip`) is used by both rate limiting and audit
  logging. It trusts `X-Real-IP` (set by the nginx proxy from `$remote_addr`)
  and falls back to `REMOTE_ADDR`. `X-Forwarded-For` is **not trusted** for
  primary identity, preventing spoofed-IP attacks.
- Audit log is append-only at the model layer (update/delete raise)
- Audit export endpoint is **administrator-only** (and not delegable via
  scoped grants — the grant endpoint actively rejects `audit:export*`)
- **Auto-created tickets** from failed P0 inspections now include:
  - **Owner assignment** via deterministic policy: dataset metadata owner
    → first operations user → first administrator → NULL.
  - **Initial remediation action** (type `investigate_and_fix`) with rule
    details, so each ticket is actionable immediately.
  - Due date default remains 7 days.
- Content body is HTML-escaped on persist (anti-XSS in downstream renderers)
- Governed query API enforces an allowlisted filter grammar; payloads
  containing SQL keywords are rejected; raw SQL is never accepted
- **Export file list** (`GET /exports/{id}/files`) no longer exposes internal
  filesystem `path` values. Only safe identifiers (`id`, `part_number`,
  `row_count`, `checksum_sha256`) are returned. The download endpoint
  (`GET /exports/{id}/files/{part}/download`) continues to work using
  `part_number`.
- MySQL binary logging enabled with 14-day retention for PITR
