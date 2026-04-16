# Verification Report: 4 Remediation Issues

## Scope
- Static-only verification in current repository.
- No app startup, Docker run, or test execution performed.

## Overall Result
- **Status: All 4 issues are fixed at static code/config/documentation level.**
- Runtime-dependent behaviors (especially end-to-end TLS handshake in live containers) remain **Manual Verification Required** by audit policy.

---

## Issue 1 — TLS on all network hops
- **Previous finding:** internal `proxy -> api` hop used/plainly documented as HTTP.
- **Current status:** **Fixed (static evidence).**
- **Evidence:**
  - Nginx upstream now proxies over HTTPS: `docker/proxy/nginx.conf:47`
  - Upstream certificate verification enabled: `docker/proxy/nginx.conf:48`
  - API process configured with cert/key: `Dockerfile:55`
  - README now states HTTPS + verification for `proxy -> api`: `README.md:255`
- **Boundary:** live handshake/trust-chain behavior still requires manual runtime check.

## Issue 2 — Inspection results immutability enforcement
- **Previous finding:** `InspectionRuleResult` not enforced append-only.
- **Current status:** **Fixed.**
- **Evidence:**
  - Update blocked on existing results: `apps/quality/models.py:121`
  - Delete blocked for results: `apps/quality/models.py:129`
  - Additional hardening for completed runs (update/delete blocked): `apps/quality/models.py:78`, `apps/quality/models.py:96`

## Issue 3 — Schedule default timezone should be local default, not hardcoded UTC
- **Previous finding:** default timezone behavior/static schema inconsistency around UTC.
- **Current status:** **Fixed.**
- **Evidence:**
  - Model default uses callable derived from settings/local TZ: `apps/quality/models.py:27`, `apps/quality/models.py:140`
  - API schedule default uses settings timezone: `apps/quality/views.py:251`
  - Migration added to align schema default policy with callable default: `apps/quality/migrations/0004_alter_inspectionschedule_timezone_default.py:21`

## Issue 4 — Missing tests proving inspection-result immutability
- **Previous finding:** no explicit tests for update/delete rejection.
- **Current status:** **Fixed.**
- **Evidence:**
  - Unit tests for `InspectionRuleResult` update/delete rejection: `Unit_tests/test_inspection_result_immutability.py:46`, `Unit_tests/test_inspection_result_immutability.py:59`
  - Unit tests for completed `InspectionRun` immutability: `Unit_tests/test_inspection_result_immutability.py:88`, `Unit_tests/test_inspection_result_immutability.py:100`
  - API-level test covering post-inspection immutability behavior: `api_test/test_inspection_immutability_api.py:28`

---

## Residual Notes
- No open defect remains among the original 4 issues under static inspection.
- For acceptance closure, perform manual runtime verification for TLS topology and integration behavior in deployed container stack.
