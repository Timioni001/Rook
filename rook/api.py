"""Rook HTTP API.

    uvicorn rook.api:create_app --factory --port 8000

Every route except /api/health requires `Authorization: Bearer <token>`. The caller's identity,
organisation and roles come only from that token (server-side lookup); request bodies cannot
name an owner, org or approver. Incidents are scoped to the caller's organisation, and an
incident from another organisation is indistinguishable from one that does not exist.

The adapters behind this API are sandboxed mocks with synthetic credentials.
"""
import hashlib, hmac, json, os, pathlib, re, threading, time
from contextlib import asynccontextmanager
from typing import Literal, Optional
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from . import obs
from .domain import Principal
from .engine import Engine, RunInProgress, evidence_pack
from .playbooks import PLAYBOOKS
from .sandbox import SCENARIOS, Sandbox, playbook_of
from .store import Store

MAX_BODY = 8 * 1024
INCIDENT_ID = re.compile(r"^inc-[0-9a-f]{8}$")
ACTION_ID = re.compile(r"^inc-[0-9a-f]{8}-a\d{1,3}$")

# Local demo identities. Replace with ROOK_TOKENS (JSON {token: principal}) anywhere shared.
DEMO_TOKENS = {
    "demo-analyst-token": {"id": "u-sam", "name": "Sam (IT operations)", "org": "acme", "roles": ["analyst"]},
    "demo-approver-token": {"id": "u-priya", "name": "Priya (IT lead)", "org": "acme",
                            "roles": ["analyst", "approver"]},
    "demo-viewer-token": {"id": "u-lee", "name": "Lee (read only)", "org": "acme", "roles": ["viewer"]},
    "demo-other-org-token": {"id": "u-eve", "name": "Eve (other company)", "org": "globex",
                             "roles": ["analyst", "approver"]},
}

ScenarioName = Literal[tuple(SCENARIOS)]


class CreateIncident(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: ScenarioName = "signature"


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=500)


class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


def env(name, default=None):
    """ROOK_<name>, falling back to the earlier KEYWARDEN_<name> spelling."""
    return os.getenv(f"ROOK_{name}", os.getenv(f"KEYWARDEN_{name}", default))


def _h(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def load_tokens():
    raw = env("TOKENS")
    if raw:
        return json.loads(raw)
    if env("DEMO_TOKENS", "1") == "1":
        return DEMO_TOKENS
    return {}


def create_app(db_path=None, tokens=None, step_delay=None, background=True, rate_limit=30, read_rate_limit=900):
    db_path = db_path or env("DB", "rook.db")
    step_delay = float(env("STEP_DELAY", "0.6")) if step_delay is None else step_delay
    principals = {_h(t): Principal(**p) for t, p in (tokens if tokens is not None else load_tokens()).items()}
    store = Store(db_path)
    sb = Sandbox(store)
    engines: dict[str, Engine] = {}
    sandbox_lock = threading.Lock()
    hits: dict[str, list[float]] = {}

    @asynccontextmanager
    async def lifespan(app):
        obs.init_neatlogs(workflow_name="rook-api")
        yield
        obs.shutdown()

    app = FastAPI(title="Rook", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.store, app.state.sandbox = store, sb

    # ---------------------------------------------------------------- middleware + errors
    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            n = request.headers.get("content-length")
            if n is not None and (not n.isdigit() or int(n) > MAX_BODY):
                return JSONResponse({"detail": "request body too large"}, status_code=413)
            body = await request.body()
            if len(body) > MAX_BODY:
                return JSONResponse({"detail": "request body too large"}, status_code=413)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Cache-Control"] = "no-store"
        resp.headers["Referrer-Policy"] = "no-referrer"
        return resp

    @app.exception_handler(Exception)
    async def unhandled(request, exc):           # never leak internals or stack traces
        return JSONResponse({"detail": "internal error"}, status_code=500)

    # ---------------------------------------------------------------- auth
    def principal(request: Request) -> Principal:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        digest = _h(auth[7:].strip())
        match = next((p for h, p in principals.items() if hmac.compare_digest(h, digest)), None)
        if match is None:
            raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"})
        return match

    def limited(request: Request, p: Principal = Depends(principal)) -> Principal:
        """Per-principal sliding window: tight for changes, loose for reads (the dashboard polls)."""
        write = request.method != "GET"
        key, limit = (f"w:{p.id}", rate_limit) if write else (f"r:{p.id}", read_rate_limit)
        now = time.time()
        window = [t for t in hits.get(key, []) if now - t < 60]
        if len(window) >= limit:
            raise HTTPException(429, "too many requests")
        hits[key] = window + [now]
        return p

    def need(p: Principal, role: str):
        if not p.can(role):
            raise HTTPException(403, f"requires the {role} role")

    def owned_incident(iid: str, p: Principal):
        """Object-level authorization: the incident must belong to the caller's organisation."""
        if not INCIDENT_ID.match(iid):
            raise HTTPException(404, "incident not found")
        inc = store.incident(iid)
        if inc is None or inc.org != p.org:
            raise HTTPException(404, "incident not found")
        return inc

    def check_action_id(iid, aid):
        if not ACTION_ID.match(aid) or not aid.startswith(iid + "-"):
            raise HTTPException(404, "action not found")

    def start_run(iid):
        eng = Engine(store, sb, step_delay=step_delay)
        engines[iid] = eng

        def work():
            try:
                eng.run(iid)
            except RunInProgress:
                pass
        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    # ---------------------------------------------------------------- routes
    @app.get("/api/health")
    def health():
        return {"ok": True, "adapters": "sandboxed mock integrations, synthetic credentials only"}

    @app.get("/api/me")
    def me(p: Principal = Depends(limited)):
        return p.model_dump()

    @app.get("/api/scenarios")
    def scenarios(p: Principal = Depends(limited)):
        return [{"name": k, "description": v[0], "playbook": playbook_of(k)} for k, v in SCENARIOS.items()]

    @app.get("/api/playbooks")
    def playbooks(p: Principal = Depends(limited)):
        return [{"key": pb.key, "name": pb.name, "trigger": pb.trigger} for pb in PLAYBOOKS.values()]

    @app.get("/api/incidents")
    def list_incidents(p: Principal = Depends(limited)):
        return [{"id": i.id, "title": i.title, "status": i.status, "severity": i.severity,
                 "scenario": i.scenario, "playbook": i.playbook, "created_at": i.created_at,
                 "created_by": i.created_by}
                for i in store.incidents(org=p.org)]

    @app.post("/api/incidents", status_code=201)
    def create(body: Optional[CreateIncident] = None, p: Principal = Depends(limited)):
        need(p, "analyst")
        body = body or CreateIncident()
        with sandbox_lock:
            if any(store.run_active(i.id) for i in store.incidents()):
                raise HTTPException(409, "another incident is running in the sandbox; wait for it to finish")
            sb.reset(scenario=body.scenario)
            inc = Engine(store, sb).start(org=p.org, created_by=p.id, scenario=body.scenario)
        return {"id": inc.id, "status": inc.status, "title": inc.title}

    @app.get("/api/incidents/{iid}")
    def get(iid: str, p: Principal = Depends(limited)):
        owned_incident(iid, p)
        rep = Engine(store, sb).report(iid)
        return {"report": rep, "audit": store.audit_events(iid), "checkpoints": store.checkpoints(iid),
                "running": store.run_active(iid),
                "can": {"run": p.can("analyst"), "approve": p.can("approver")}}

    @app.get("/api/incidents/{iid}/evidence")
    def evidence(iid: str, p: Principal = Depends(limited)):
        owned_incident(iid, p)
        md = evidence_pack(Engine(store, sb).report(iid), store.audit_events(iid), store.verify_chain())
        return PlainTextResponse(md, media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="{iid}-evidence.md"'})

    @app.get("/api/incidents/{iid}/events")
    def events(iid: str, after: int = 0, p: Principal = Depends(limited)):
        owned_incident(iid, p)
        return [e for e in store.audit_events(iid) if e["n"] > after]

    @app.post("/api/incidents/{iid}/run", status_code=202)
    def run(iid: str, body: Optional[Empty] = None, p: Principal = Depends(limited)):
        need(p, "analyst")
        inc = owned_incident(iid, p)
        if store.run_active(iid):
            raise HTTPException(409, "already running")
        if inc.status == "closed_verified":
            raise HTTPException(409, "incident is already closed")
        store.audit(iid, "run_requested", {"by": p.id})
        start_run(iid)
        return {"started": iid}

    @app.post("/api/incidents/{iid}/cancel", status_code=202)
    def cancel(iid: str, body: Optional[Empty] = None, p: Principal = Depends(limited)):
        need(p, "analyst")
        owned_incident(iid, p)
        if iid in engines:
            engines[iid].cancel()
        store.audit(iid, "cancel_requested", {"by": p.id})
        return {"cancelled": iid}

    @app.post("/api/incidents/{iid}/actions/{aid}/approve")
    def approve(iid: str, aid: str, body: Optional[Empty] = None, p: Principal = Depends(limited)):
        need(p, "approver")
        owned_incident(iid, p)
        check_action_id(iid, aid)
        try:
            a = Engine(store, sb).approve(iid, aid, p)
        except KeyError:
            raise HTTPException(404, "action not found")
        except ValueError as e:
            raise HTTPException(409, str(e))
        except PermissionError as e:
            raise HTTPException(403, str(e))
        if not store.run_active(iid):
            start_run(iid)
        return {"action": a.id, "status": a.status.value, "policy": a.policy}

    @app.post("/api/incidents/{iid}/actions/{aid}/reject")
    def reject(iid: str, aid: str, body: Optional[RejectBody] = None, p: Principal = Depends(limited)):
        need(p, "approver")
        owned_incident(iid, p)
        check_action_id(iid, aid)
        try:
            a = Engine(store, sb).reject(iid, aid, p, (body or RejectBody()).note)
        except KeyError:
            raise HTTPException(404, "action not found")
        except ValueError as e:
            raise HTTPException(409, str(e))
        if not store.run_active(iid):
            start_run(iid)
        return {"action": a.id, "status": a.status.value}

    # Single-container deploys: serve the statically exported dashboard from the same origin.
    static = pathlib.Path(env("STATIC", pathlib.Path(__file__).parent.parent / "web" / "out"))
    if static.is_dir():
        app.mount("/", StaticFiles(directory=static, html=True), name="dashboard")
    return app
