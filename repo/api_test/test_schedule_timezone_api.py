"""API test proving schedule creation uses settings.TIME_ZONE as default,
and that explicit timezone overrides are preserved."""
import pytest

from django.conf import settings


def _ds(client, code):
    return client.post("/api/v1/datasets",
                       {"code": code, "display_name": code}, format="json").json()


def test_schedule_default_timezone_is_settings_time_zone(authed_client):
    """Creating a schedule without specifying timezone should use
    settings.TIME_ZONE, not hardcoded UTC."""
    client, _, _ = authed_client(roles=("operations",))
    ds = _ds(client, "tz_default")
    res = client.post("/api/v1/quality/schedules",
                      {"dataset_id": ds["id"]}, format="json")
    assert res.status_code in (200, 201), res.content
    body = res.json()
    expected = settings.TIME_ZONE or "UTC"
    assert body["timezone"] == expected, (
        f"Expected default timezone '{expected}', got '{body['timezone']}'"
    )


def test_schedule_explicit_timezone_override_preserved(authed_client):
    """An explicit timezone in the request must be preserved verbatim."""
    client, _, _ = authed_client(roles=("operations",))
    ds = _ds(client, "tz_explicit")
    res = client.post("/api/v1/quality/schedules",
                      {"dataset_id": ds["id"], "timezone": "America/New_York"},
                      format="json")
    assert res.status_code in (200, 201), res.content
    assert res.json()["timezone"] == "America/New_York"
