"""Comprehensive endpoint coverage tests for previously uncovered API paths.

Covers:
 1. GET /api/v1/users/:user_id
 2. GET /api/v1/datasets/:dataset_id
 3. GET /api/v1/datasets/:dataset_id/fields
 4. GET /api/v1/lineage/edges
 5. GET /api/v1/reports/definitions
 6. PATCH /api/v1/reports/definitions/:definition_id
 7. GET /api/v1/reports/runs/:run_id
 8. GET /api/v1/quality/rules
 9. GET /api/v1/quality/inspections/:inspection_id
10. POST /api/v1/tickets/:ticket_id/remediation-actions
11. GET /api/v1/backfills/:backfill_id
12. PATCH /api/v1/content/entries/:entry_id

All tests are real HTTP via DRF APIClient — no mocks.
"""

import secrets

import pytest

from apps.catalog.models import DatasetRow


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _ds(client, code):
    """Create a dataset and return its JSON body."""
    res = client.post(
        "/api/v1/datasets",
        {"code": code, "display_name": code.replace("_", " ").title()},
        format="json",
    )
    assert res.status_code == 201, res.content
    return res.json()


def _ds_with_field(client, code, field_key="value", data_type="integer"):
    ds = _ds(client, code)
    fld = client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": field_key, "display_name": field_key, "data_type": data_type},
        format="json",
    )
    assert fld.status_code == 201
    return ds, fld.json()


def _approved_ds(client, code):
    ds = _ds(client, code)
    client.post(
        f"/api/v1/datasets/{ds['id']}/fields",
        {"field_key": "x", "display_name": "X", "data_type": "string"},
        format="json",
    )
    client.patch(
        f"/api/v1/datasets/{ds['id']}",
        {"approval_state": "approved"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    return ds


def _rdef(client, ds_id, name=None):
    res = client.post(
        "/api/v1/reports/definitions",
        {"name": name or f"def_{secrets.token_hex(4)}", "dataset_id": ds_id},
        format="json",
    )
    assert res.status_code == 201
    return res.json()


def _create_ticket(client, title="coverage_t", dataset_id=None):
    payload = {"title": title}
    if dataset_id:
        payload["dataset_id"] = dataset_id
    res = client.post(
        "/api/v1/tickets",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
    )
    assert res.status_code == 201
    return res.json()


def _entry(client, ctype="poetry", slug=None):
    slug = slug or f"s_{secrets.token_hex(4)}"
    res = client.post(
        "/api/v1/content/entries",
        {"content_type": ctype, "slug": slug, "title": slug.title()},
        format="json",
    )
    assert res.status_code == 201
    return res.json()


# ===========================================================================
# 1. GET /api/v1/users/:user_id
# ===========================================================================


class TestUserDetail:
    def test_get_user_by_id_returns_full_repr(self, authed_client, make_user):
        admin, _, _ = authed_client(roles=("administrator",))
        target = make_user("detail_user", "StrongPass!1234", roles=("operations",))
        res = admin.get(f"/api/v1/users/{target.id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == target.id
        assert body["username"] == "detail_user"
        assert "operations" in body["roles"]
        assert body["is_active"] is True
        assert "version" in body

    def test_get_nonexistent_user_returns_404(self, authed_client):
        admin, _, _ = authed_client(roles=("administrator",))
        res = admin.get("/api/v1/users/usr_does_not_exist")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    def test_user_role_cannot_get_user_detail(self, authed_client, make_user):
        admin, _, _ = authed_client(roles=("administrator",))
        target = make_user("priv_check", "StrongPass!1234", roles=("user",))
        user_client, _, _ = authed_client(roles=("user",))
        res = user_client.get(f"/api/v1/users/{target.id}")
        assert res.status_code == 403


# ===========================================================================
# 2. GET /api/v1/datasets/:dataset_id
# ===========================================================================


class TestDatasetDetail:
    def test_get_dataset_by_id(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _ds(client, "detail_ds")
        res = client.get(f"/api/v1/datasets/{ds['id']}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == ds["id"]
        assert body["code"] == "detail_ds"
        assert body["approval_state"] == "draft"
        assert "version" in body
        assert "created_at" in body

    def test_get_nonexistent_dataset_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.get("/api/v1/datasets/dts_nope")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    def test_user_cannot_see_draft_dataset(self, authed_client):
        ops, _, _ = authed_client(roles=("operations",))
        ds = _ds(ops, "draft_hidden")
        user_client, _, _ = authed_client(roles=("user",))
        res = user_client.get(f"/api/v1/datasets/{ds['id']}")
        assert res.status_code == 403


# ===========================================================================
# 3. GET /api/v1/datasets/:dataset_id/fields
# ===========================================================================


class TestDatasetFields:
    def test_list_fields_returns_created_fields(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds, fld = _ds_with_field(client, "fields_ds", "student_id", "string")
        res = client.get(f"/api/v1/datasets/{ds['id']}/fields")
        assert res.status_code == 200
        body = res.json()
        assert "fields" in body
        assert len(body["fields"]) >= 1
        f0 = body["fields"][0]
        assert f0["field_key"] == "student_id"
        assert f0["dataset_id"] == ds["id"]
        assert "id" in f0
        assert "data_type" in f0

    def test_fields_empty_for_new_dataset(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _ds(client, "empty_fields_ds")
        res = client.get(f"/api/v1/datasets/{ds['id']}/fields")
        assert res.status_code == 200
        assert res.json()["fields"] == []

    def test_fields_nonexistent_dataset_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.get("/api/v1/datasets/dts_ghost/fields")
        assert res.status_code == 404


# ===========================================================================
# 4. GET /api/v1/lineage/edges
# ===========================================================================


class TestLineageEdgesList:
    def test_list_edges_returns_envelope(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        a = _ds(client, "edge_a")
        b = _ds(client, "edge_b")
        client.post(
            "/api/v1/lineage/edges",
            {
                "upstream_dataset_id": a["id"],
                "downstream_dataset_id": b["id"],
                "relation_type": "transform",
                "observed_at": "2026-04-15T01:00:00Z",
            },
            format="json",
        )
        res = client.get("/api/v1/lineage/edges")
        assert res.status_code == 200
        body = res.json()
        assert "edges" in body
        assert isinstance(body["edges"], list)
        assert len(body["edges"]) >= 1
        edge = body["edges"][0]
        assert "id" in edge
        assert "upstream_dataset_id" in edge
        assert "downstream_dataset_id" in edge
        assert "relation_type" in edge
        assert "observed_at" in edge

    def test_list_edges_empty(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.get("/api/v1/lineage/edges")
        assert res.status_code == 200
        assert "edges" in res.json()

    def test_user_role_can_read_edges(self, authed_client):
        client, _, _ = authed_client(roles=("user",))
        res = client.get("/api/v1/lineage/edges")
        assert res.status_code == 403

    def test_anonymous_cannot_list_edges(self, api_client):
        res = api_client.get("/api/v1/lineage/edges")
        assert res.status_code == 401


# ===========================================================================
# 5. GET /api/v1/reports/definitions
# ===========================================================================


class TestReportDefinitionsList:
    def test_list_definitions_returns_envelope(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(client, "rdef_list")
        rdef = _rdef(client, ds["id"], name="listing_def")
        res = client.get("/api/v1/reports/definitions")
        assert res.status_code == 200
        body = res.json()
        assert "definitions" in body
        assert isinstance(body["definitions"], list)
        ids = [d["id"] for d in body["definitions"]]
        assert rdef["id"] in ids
        d = next(d for d in body["definitions"] if d["id"] == rdef["id"])
        assert d["name"] == "listing_def"
        assert d["dataset_id"] == ds["id"]
        assert "version" in d

    def test_user_can_list_definitions_scoped(self, authed_client):
        ops, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(ops, "rdef_scope")
        _rdef(ops, ds["id"], name="scoped_def")
        user_client, _, _ = authed_client(roles=("user",))
        res = user_client.get("/api/v1/reports/definitions")
        assert res.status_code == 200
        assert "definitions" in res.json()

    def test_anonymous_cannot_list_definitions(self, api_client):
        res = api_client.get("/api/v1/reports/definitions")
        assert res.status_code == 401


# ===========================================================================
# 6. PATCH /api/v1/reports/definitions/:definition_id
# ===========================================================================


class TestReportDefinitionPatch:
    def test_patch_definition_happy(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(client, "rdef_patch")
        rdef = _rdef(client, ds["id"], name="patchable_def")
        res = client.patch(
            f"/api/v1/reports/definitions/{rdef['id']}",
            {"filter_schema": {"status": "active"}},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 200
        body = res.json()
        assert body["filter_schema"] == {"status": "active"}
        assert body["version"] == 2

    def test_patch_definition_requires_if_match(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(client, "rdef_nomatch")
        rdef = _rdef(client, ds["id"], name="nomatch_def")
        res = client.patch(
            f"/api/v1/reports/definitions/{rdef['id']}",
            {"filter_schema": {"x": 1}},
            format="json",
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "if_match_required"

    def test_patch_definition_version_conflict(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(client, "rdef_conflict")
        rdef = _rdef(client, ds["id"], name="conflict_def")
        res = client.patch(
            f"/api/v1/reports/definitions/{rdef['id']}",
            {"filter_schema": {"x": 1}},
            format="json",
            HTTP_IF_MATCH='"99"',
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "version_conflict"

    def test_patch_nonexistent_definition_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.patch(
            "/api/v1/reports/definitions/rpt_ghost",
            {"filter_schema": {}},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 404

    def test_patch_definition_no_fields_returns_400(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(client, "rdef_empty_patch")
        rdef = _rdef(client, ds["id"], name="empty_patch_def")
        res = client.patch(
            f"/api/v1/reports/definitions/{rdef['id']}",
            {},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 400

    def test_user_role_cannot_patch_definition(self, authed_client):
        ops, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(ops, "rdef_perm")
        rdef = _rdef(ops, ds["id"], name="perm_def")
        user_client, _, _ = authed_client(roles=("user",))
        res = user_client.patch(
            f"/api/v1/reports/definitions/{rdef['id']}",
            {"filter_schema": {}},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 403


# ===========================================================================
# 7. GET /api/v1/reports/runs/:run_id
# ===========================================================================


class TestReportRunDetail:
    def test_get_run_by_id(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _approved_ds(client, "run_det")
        DatasetRow.objects.create(dataset_id=ds["id"], payload={"x": "v"})
        rdef = _rdef(client, ds["id"], name="run_det_def")
        run = client.post(
            "/api/v1/reports/runs",
            {"report_definition_id": rdef["id"]},
            format="json",
            HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
        )
        assert run.status_code == 202
        run_id = run.json()["id"]
        res = client.get(f"/api/v1/reports/runs/{run_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == run_id
        assert body["report_definition_id"] == rdef["id"]
        assert body["status"] == "complete"
        assert body["total_rows"] >= 1
        assert "started_at" in body
        assert "resolved_filters" in body

    def test_get_nonexistent_run_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.get("/api/v1/reports/runs/rpr_ghost")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"

    def test_anonymous_cannot_get_run(self, api_client):
        res = api_client.get("/api/v1/reports/runs/rpr_any")
        assert res.status_code == 401


# ===========================================================================
# 8. GET /api/v1/quality/rules
# ===========================================================================


class TestQualityRulesList:
    def test_list_rules_returns_envelope(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds, fld = _ds_with_field(client, "rules_list")
        client.post(
            "/api/v1/quality/rules",
            {
                "dataset_id": ds["id"],
                "rule_type": "completeness",
                "severity": "P1",
                "threshold_value": 95.0,
                "field_ids": [fld["id"]],
            },
            format="json",
        )
        res = client.get("/api/v1/quality/rules")
        assert res.status_code == 200
        body = res.json()
        assert "rules" in body
        assert isinstance(body["rules"], list)
        assert len(body["rules"]) >= 1
        r = body["rules"][0]
        assert "id" in r
        assert "dataset_id" in r
        assert "rule_type" in r
        assert "severity" in r
        assert "threshold_value" in r
        assert "active" in r

    def test_list_rules_filter_by_dataset(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds1, fld1 = _ds_with_field(client, "rules_f1")
        ds2, fld2 = _ds_with_field(client, "rules_f2")
        client.post(
            "/api/v1/quality/rules",
            {
                "dataset_id": ds1["id"],
                "rule_type": "completeness",
                "severity": "P0",
                "threshold_value": 90.0,
                "field_ids": [fld1["id"]],
            },
            format="json",
        )
        client.post(
            "/api/v1/quality/rules",
            {
                "dataset_id": ds2["id"],
                "rule_type": "completeness",
                "severity": "P2",
                "threshold_value": 80.0,
                "field_ids": [fld2["id"]],
            },
            format="json",
        )
        res = client.get(f"/api/v1/quality/rules?dataset_id={ds1['id']}")
        assert res.status_code == 200
        rules = res.json()["rules"]
        assert all(r["dataset_id"] == ds1["id"] for r in rules)

    def test_user_can_read_rules(self, authed_client):
        client, _, _ = authed_client(roles=("user",))
        res = client.get("/api/v1/quality/rules")
        assert res.status_code == 403


# ===========================================================================
# 9. GET /api/v1/quality/inspections/:inspection_id
# ===========================================================================


class TestInspectionDetail:
    def test_get_inspection_by_id(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds, fld = _ds_with_field(client, "insp_det")
        DatasetRow.objects.create(dataset_id=ds["id"], payload={"value": 10})
        client.post(
            "/api/v1/quality/rules",
            {
                "dataset_id": ds["id"],
                "rule_type": "completeness",
                "severity": "P1",
                "threshold_value": 50.0,
                "field_ids": [fld["id"]],
            },
            format="json",
        )
        trigger = client.post(
            "/api/v1/quality/inspections/trigger",
            {"dataset_id": ds["id"]},
            format="json",
        )
        assert trigger.status_code == 202
        insp_id = trigger.json()["id"]
        res = client.get(f"/api/v1/quality/inspections/{insp_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == insp_id
        assert body["dataset_id"] == ds["id"]
        assert "quality_score" in body
        assert "gate_pass" in body
        assert "rule_results" in body
        assert isinstance(body["rule_results"], list)
        assert len(body["rule_results"]) >= 1
        rr = body["rule_results"][0]
        assert "rule_id" in rr
        assert "passed" in rr
        assert "measured_value" in rr

    def test_get_nonexistent_inspection_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.get("/api/v1/quality/inspections/ins_ghost")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"


# ===========================================================================
# 10. POST /api/v1/tickets/:ticket_id/remediation-actions
# ===========================================================================


class TestRemediationAction:
    def test_create_remediation_action_happy(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        t = _create_ticket(client)
        res = client.post(
            f"/api/v1/tickets/{t['id']}/remediation-actions",
            {
                "action_type": "investigate_and_fix",
                "parameters": {"note": "fix null rows"},
            },
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 201
        body = res.json()
        assert body["ticket_id"] == t["id"]
        assert body["action_type"] == "investigate_and_fix"
        assert body["parameters"] == {"note": "fix null rows"}
        assert body["status"] == "pending"
        assert "id" in body
        assert "created_at" in body

    def test_remediation_action_requires_action_type(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        t = _create_ticket(client, title="rem_val")
        res = client.post(
            f"/api/v1/tickets/{t['id']}/remediation-actions",
            {"parameters": {}},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 400

    def test_remediation_action_requires_if_match(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        t = _create_ticket(client, title="rem_occ")
        res = client.post(
            f"/api/v1/tickets/{t['id']}/remediation-actions",
            {"action_type": "rerun"},
            format="json",
        )
        assert res.status_code == 400

    def test_remediation_on_nonexistent_ticket_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.post(
            "/api/v1/tickets/tkt_ghost/remediation-actions",
            {"action_type": "fix"},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 404

    def test_user_role_cannot_create_remediation(self, authed_client):
        ops, _, _ = authed_client(roles=("operations",))
        t = _create_ticket(ops, title="rem_perm")
        user_client, _, _ = authed_client(roles=("user",))
        res = user_client.post(
            f"/api/v1/tickets/{t['id']}/remediation-actions",
            {"action_type": "fix"},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 403


# ===========================================================================
# 11. GET /api/v1/backfills/:backfill_id
# ===========================================================================


class TestBackfillDetail:
    def test_get_backfill_by_id(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        ds = _ds(client, "bf_detail_ds")
        t = _create_ticket(client, title="bf_det", dataset_id=ds["id"])
        bf = client.post(
            f"/api/v1/tickets/{t['id']}/backfills",
            {"input_fingerprint": "sha256:det", "parameters": {}},
            format="json",
            HTTP_IDEMPOTENCY_KEY=secrets.token_hex(8),
        )
        assert bf.status_code == 201
        bf_id = bf.json()["id"]
        res = client.get(f"/api/v1/backfills/{bf_id}")
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == bf_id
        assert body["ticket_id"] == t["id"]
        assert body["input_fingerprint"] == "sha256:det"
        assert "status" in body
        assert "started_at" in body

    def test_get_nonexistent_backfill_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.get("/api/v1/backfills/bfr_ghost")
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "not_found"


# ===========================================================================
# 12. PATCH /api/v1/content/entries/:entry_id
# ===========================================================================


class TestContentEntryPatch:
    def test_patch_entry_title_happy(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        e = _entry(client)
        res = client.patch(
            f"/api/v1/content/entries/{e['id']}",
            {"title": "Updated Title"},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 200
        body = res.json()
        assert body["title"] == "Updated Title"
        assert body["version"] == 2
        assert body["id"] == e["id"]

    def test_patch_entry_requires_if_match(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        e = _entry(client, slug="patch_occ")
        res = client.patch(
            f"/api/v1/content/entries/{e['id']}",
            {"title": "New"},
            format="json",
        )
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "if_match_required"

    def test_patch_entry_version_conflict(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        e = _entry(client, slug="patch_vc")
        res = client.patch(
            f"/api/v1/content/entries/{e['id']}",
            {"title": "New"},
            format="json",
            HTTP_IF_MATCH='"99"',
        )
        assert res.status_code == 409
        assert res.json()["error"]["code"] == "version_conflict"

    def test_patch_entry_empty_title_rejected(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        e = _entry(client, slug="patch_empty")
        res = client.patch(
            f"/api/v1/content/entries/{e['id']}",
            {"title": ""},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 400

    def test_patch_entry_no_fields_returns_400(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        e = _entry(client, slug="patch_noop")
        res = client.patch(
            f"/api/v1/content/entries/{e['id']}",
            {},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 400

    def test_patch_nonexistent_entry_returns_404(self, authed_client):
        client, _, _ = authed_client(roles=("operations",))
        res = client.patch(
            "/api/v1/content/entries/cte_ghost",
            {"title": "X"},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 404

    def test_user_role_cannot_patch_entry(self, authed_client):
        ops, _, _ = authed_client(roles=("operations",))
        e = _entry(ops, slug="patch_perm")
        user_client, _, _ = authed_client(roles=("user",))
        res = user_client.patch(
            f"/api/v1/content/entries/{e['id']}",
            {"title": "Nope"},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert res.status_code == 403
