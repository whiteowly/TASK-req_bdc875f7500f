# Fix Check Report: 5 Targeted Issues

Scope note:
- Static analysis only (no runtime execution, no tests run).
- Statuses below are evidence-based from code and test artifacts.

## 1) Encryption-at-rest for sensitive domain fields
- Status: **Fixed**
- What changed:
  - Added reusable encrypted model field.
  - Applied it to sensitive persisted fields (`ContentVersion.body`, `DatasetMetadata.owner`).
  - Added migrations and dedicated tests asserting ciphertext-at-rest + plaintext-on-read.
- Evidence:
  - `apps/platform_common/fields.py:21`
  - `apps/content/models.py:40`
  - `apps/catalog/models.py:61`
  - `apps/content/migrations/0002_encrypted_body.py:17`
  - `apps/catalog/migrations/0002_encrypted_owner.py:17`
  - `Unit_tests/test_encrypted_fields.py:23`
- Residual note: Runtime key handling and migration rollout still require manual operational verification.

## 2) Auto-open failed-check tickets missing owner/remediation
- Status: **Fixed**
- What changed:
  - Auto-ticket flow now resolves owner via deterministic fallback policy.
  - Auto-created remediation action is now created for each auto-ticket.
  - Due-date behavior preserved.
- Evidence:
  - `apps/tickets/services.py:58`
  - `apps/tickets/services.py:112`
  - `apps/tickets/services.py:123`
  - `apps/tickets/services.py:132`
  - `Unit_tests/test_auto_ticket_owner.py:64`
  - `Unit_tests/test_auto_ticket_owner.py:105`
- Residual note: Policy correctness for real org assignment rules is business-dependent; logic is now present and test-covered.

## 3) Audit IP trust model inconsistency
- Status: **Fixed**
- What changed:
  - Introduced centralized client IP helper.
  - Both rate limiter and audit now use same trust model (`X-Real-IP` then `REMOTE_ADDR`; no primary trust in `X-Forwarded-For`).
- Evidence:
  - `apps/platform_common/client_ip.py:17`
  - `apps/platform_common/middleware.py:14`
  - `apps/platform_common/middleware.py:125`
  - `apps/platform_common/audit.py:6`
  - `apps/platform_common/audit.py:28`
  - `Unit_tests/test_audit_ip_trust.py:52`
- Residual note: End-to-end proxy/header behavior still needs environment validation.

## 4) Nightly backup scheduling depended on host cron
- Status: **Fixed**
- What changed:
  - Added in-service backup scheduler tick and backup schedule state model.
  - Backup schedule now tracked and surfaced in monitoring metrics.
  - Env-backed defaults wired on first singleton creation; DB/operator overrides preserved after creation.
  - Added tests for creation seeding, non-overwrite behavior, due/not-due logic.
- Evidence:
  - `apps/platform_common/models.py:39`
  - `apps/platform_common/models.py:59`
  - `apps/platform_common/models.py:73`
  - `apps/platform_common/scheduler.py:132`
  - `apps/platform_common/scheduler.py:142`
  - `apps/platform_common/scheduler.py:172`
  - `apps/audit_monitoring/services.py:33`
  - `Unit_tests/test_backup_schedule.py:40`
  - `Unit_tests/test_backup_schedule.py:51`
  - `Unit_tests/test_backup_schedule.py:90`
  - `README.md:165`
- Residual note: Actual backup execution reliability remains manual/runtime verification.

## 5) Export API path leakage
- Status: **Fixed**
- What changed:
  - Export file response representation no longer exposes internal file path.
  - API tests explicitly assert `path` is absent.
- Evidence:
  - `apps/exports/views.py:42`
  - `api_test/test_export_no_path_api.py:48`
  - `api_test/test_xlsx_export_api.py:49`
- Residual note: None material from static view.

## Overall Fixing Situation (5-issue summary)
- Resolved: **5 / 5** (static evidence)
- Current conclusion: The previously tracked five remediation items appear implemented and test-covered at code level.
- Boundary: Runtime correctness, performance, and operational reliability remain **Manual Verification Required**.
