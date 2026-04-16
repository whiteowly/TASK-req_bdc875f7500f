"""Content version listing visibility for user vs operations."""
def _entry(client, slug):
    return client.post(
        "/api/v1/content/entries",
        {"content_type": "tribute", "slug": slug, "title": slug.title()},
        format="json",
    ).json()


def test_user_only_sees_published_versions(authed_client):
    ops, _, _ = authed_client(roles=("operations",))
    e = _entry(ops, "verlist")
    v_draft = ops.post(f"/api/v1/content/entries/{e['id']}/versions",
                       {"body": "draft body"}, format="json").json()
    v_pub = ops.post(f"/api/v1/content/entries/{e['id']}/versions",
                     {"body": "to-be-published"}, format="json").json()
    ops.post(
        f"/api/v1/content/entries/{e['id']}/publish",
        {"version_id": v_pub["id"], "reason": "publish second version"},
        format="json", HTTP_IF_MATCH='"1"',
    )
    user_client, _, _ = authed_client(roles=("user",))
    listing = user_client.get(f"/api/v1/content/entries/{e['id']}/versions").json()
    states = {v["state"] for v in listing["versions"]}
    assert states == {"published"}
    assert listing["versions"][0]["id"] == v_pub["id"]
