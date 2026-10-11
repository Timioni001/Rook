import json
import pytest
from fastapi.testclient import TestClient
from rook.api import DEMO_TOKENS, create_app

ANALYST, APPROVER, VIEWER, OTHER = ("demo-analyst-token", "demo-approver-token",
                                    "demo-viewer-token", "demo-other-org-token")


def h(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "api.db"), tokens=DEMO_TOKENS, step_delay=0, background=False)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def new_incident(client, scenario="signature", token=ANALYST):
    r = client.post("/api/incidents", json={"scenario": scenario}, headers=h(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def revoke_id(client, iid, token=ANALYST):
    rep = client.get(f"/api/incidents/{iid}", headers=h(token)).json()["report"]
    return next(a["id"] for a in rep["actions"] if a["type"] == "revoke_credential")


def test_full_flow_over_http(client):
    iid = new_incident(client)
    assert client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST)).status_code == 202
    body = client.get(f"/api/incidents/{iid}", headers=h(ANALYST)).json()
    assert body["report"]["status"] == "awaiting_approval"
    r = client.post(f"/api/incidents/{iid}/actions/{revoke_id(client, iid)}/approve", headers=h(APPROVER))
    assert r.status_code == 200 and r.json()["policy"]["approval"]["by"] == "u-priya"
    body = client.get(f"/api/incidents/{iid}", headers=h(VIEWER)).json()
    assert body["report"]["status"] == "closed_verified"
    assert body["report"]["approvals"][0]["by"] == "u-priya"
    ev = client.get(f"/api/incidents/{iid}/events?after=0", headers=h(VIEWER)).json()
    assert ev and all(e["n"] > 0 for e in ev)


# 14. API authorization on every sensitive route
SENSITIVE = [
    ("get", "/api/me"), ("get", "/api/scenarios"), ("get", "/api/incidents"),
    ("post", "/api/incidents"), ("get", "/api/incidents/{iid}"), ("get", "/api/incidents/{iid}/events"),
    ("get", "/api/incidents/{iid}/evidence"),
    ("post", "/api/incidents/{iid}/run"), ("post", "/api/incidents/{iid}/cancel"),
    ("post", "/api/incidents/{iid}/actions/{aid}/approve"), ("post", "/api/incidents/{iid}/actions/{aid}/reject"),
]


@pytest.mark.parametrize("method,path", SENSITIVE)
def test_every_route_requires_authentication(client, method, path):
    iid = new_incident(client)
    url = path.format(iid=iid, aid=f"{iid}-a6")
    assert getattr(client, method)(url).status_code == 401
    assert getattr(client, method)(url, headers=h("forged-token")).status_code == 401
    assert getattr(client, method)(url, headers={"Authorization": "Basic abc"}).status_code == 401


@pytest.mark.parametrize("method,path", [p for p in SENSITIVE if "{iid}" in p[1]])
def test_other_org_cannot_see_or_touch_incident(client, method, path):
    iid = new_incident(client)
    url = path.format(iid=iid, aid=f"{iid}-a6")
    assert getattr(client, method)(url, headers=h(OTHER)).status_code == 404


def test_other_org_incident_list_is_empty(client):
    new_incident(client)
    assert client.get("/api/incidents", headers=h(OTHER)).json() == []
    assert len(client.get("/api/incidents", headers=h(VIEWER)).json()) == 1


def test_roles_enforced(client):
    assert client.post("/api/incidents", json={}, headers=h(VIEWER)).status_code == 403
    iid = new_incident(client)
    assert client.post(f"/api/incidents/{iid}/run", headers=h(VIEWER)).status_code == 403
    client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST))
    aid = revoke_id(client, iid)
    assert client.post(f"/api/incidents/{iid}/actions/{aid}/approve", headers=h(ANALYST)).status_code == 403
    assert client.post(f"/api/incidents/{iid}/actions/{aid}/reject", headers=h(VIEWER)).status_code == 403
    rep = client.get(f"/api/incidents/{iid}", headers=h(ANALYST)).json()["report"]
    assert rep["status"] == "awaiting_approval" and not rep["approvals"]


# 6. tampered request identity rejected
@pytest.mark.parametrize("field", ["owner", "org", "created_by", "approver", "principal"])
def test_identity_fields_in_body_rejected(client, field):
    r = client.post("/api/incidents", json={"scenario": "clean", field: "u-priya"}, headers=h(ANALYST))
    assert r.status_code == 422
    iid = new_incident(client)
    client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST))
    aid = revoke_id(client, iid)
    r = client.post(f"/api/incidents/{iid}/actions/{aid}/approve", json={field: "u-priya"}, headers=h(ANALYST))
    assert r.status_code in (403, 422)
    r = client.post(f"/api/incidents/{iid}/actions/{aid}/approve", json={"approved_by": "u-priya"},
                    headers=h(APPROVER))
    assert r.status_code == 422                 # even an approver cannot name someone else


def test_created_by_comes_from_token(client):
    iid = new_incident(client, token=APPROVER)
    inc = client.get(f"/api/incidents/{iid}", headers=h(ANALYST)).json()["report"]["incident"]
    assert inc["created_by"] == "u-priya" and inc["org"] == "acme"


def test_validation_and_limits(client):
    assert client.post("/api/incidents", json={"scenario": "rm -rf"}, headers=h(ANALYST)).status_code == 422
    big = json.dumps({"scenario": "clean", "x": "a" * 20000})
    r = client.post("/api/incidents", content=big, headers={**h(ANALYST), "Content-Type": "application/json"})
    assert r.status_code == 413
    assert client.get("/api/incidents/../../etc", headers=h(ANALYST)).status_code == 404
    assert client.get("/api/incidents/inc-zzzz", headers=h(ANALYST)).status_code == 404
    iid = new_incident(client)
    assert client.post(f"/api/incidents/{iid}/actions/inc-00000000-a1/approve",
                       headers=h(APPROVER)).status_code == 404


def test_rate_limit(tmp_path):
    app = create_app(db_path=str(tmp_path / "r.db"), tokens=DEMO_TOKENS, step_delay=0, background=False,
                     rate_limit=2, read_rate_limit=3)
    with TestClient(app) as c:
        reads = [c.get("/api/me", headers=h(VIEWER)).status_code for _ in range(4)]
        writes = [c.post("/api/incidents", json={"scenario": "clean"}, headers=h(ANALYST)).status_code
                  for _ in range(3)]
    assert reads == [200, 200, 200, 429]
    assert writes == [201, 201, 429]


def test_errors_do_not_leak_internals(client, monkeypatch):
    from rook import engine
    monkeypatch.setattr(engine.Engine, "report", lambda *a, **k: 1 / 0)
    iid = new_incident(client)
    r = client.get(f"/api/incidents/{iid}", headers=h(ANALYST))
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}


def test_double_run_and_closed_incident_conflicts(client):
    iid = new_incident(client, scenario="clean")
    client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST))
    client.post(f"/api/incidents/{iid}/actions/{revoke_id(client, iid)}/approve", headers=h(APPROVER))
    assert client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST)).status_code == 409
    r = client.post(f"/api/incidents/{iid}/actions/{revoke_id(client, iid)}/approve", headers=h(APPROVER))
    assert r.status_code == 409


def test_no_secrets_in_api_responses(client):
    iid = new_incident(client)
    client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST))
    client.post(f"/api/incidents/{iid}/actions/{revoke_id(client, iid)}/approve", headers=h(APPROVER))
    body = client.get(f"/api/incidents/{iid}", headers=h(ANALYST)).text
    assert "sk_test_SYNTH" not in body and "closed_verified" in body


def test_evidence_pack_download(client):
    iid = new_incident(client)
    client.post(f"/api/incidents/{iid}/run", headers=h(ANALYST))
    client.post(f"/api/incidents/{iid}/actions/{revoke_id(client, iid)}/approve", headers=h(APPROVER))
    r = client.get(f"/api/incidents/{iid}/evidence", headers=h(VIEWER))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    body = r.text
    # the approval reads as a person, with the account it came from beside it
    assert "Status: **closed_verified**" in body
    assert "approved by Priya (manager) (account u-priya" in body
    assert "Hash chain over" in body and "intact" in body and "sk_test_SYNTH" not in body


# ---------------------------------------------------------------- the waitlist

def test_waitlist_takes_one_email_and_bounds_the_rest(client):
    r = client.post("/api/waitlist", json={"email": "Ada@Example.com ", "name": "Ada Okafor",
                                           "organisation": "Riverside Family Practice",
                                           "sector": "Clinic or practice", "size": "11–50",
                                           "use_for": "Cover for absences"})
    assert r.status_code == 201 and r.json() == {"ok": True}
    for bad in ({"email": "not-an-address"}, {"email": "a@b"}, {"email": ""},
                {"email": "a@b.com", "sector": "Something I made up"},
                {"email": "a@b.com", "size": "a few"},
                {"email": "a@b.com", "name": "<script>x</script>"},
                {"email": "a@b.com", "use_for": "x" * 301},
                {"email": "a@b.com", "unexpected": True},
                {}):
        assert client.post("/api/waitlist", json=bad).status_code == 422, bad


def test_the_waitlist_is_write_only_and_deduplicated(client, tmp_path):
    """Nothing reads it back over HTTP, and signing up twice does not make two rows."""
    for _ in range(2):
        assert client.post("/api/waitlist", json={"email": "same@example.com"}).status_code == 201
    assert client.app.state.store.waitlist_size() == 1
    for path in ("/api/waitlist", "/api/waitlist/list", "/api/waitlist/same@example.com"):
        assert client.get(path, headers=h(APPROVER)).status_code in (404, 405)


def test_waitlist_sign_ups_are_rate_limited(client):
    codes = [client.post("/api/waitlist", json={"email": f"a{i}@example.com"}).status_code for i in range(7)]
    assert codes.count(201) == 5 and codes[-1] == 429
