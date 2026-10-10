import threading
from typing import Optional
from fastapi import Body, FastAPI, HTTPException
from .store import Store
from .sandbox import Sandbox
from .engine import Engine

store = Store("rook.db")
sb = Sandbox(store)
app = FastAPI(title="Keywarden / Rook")
ENGINES: dict[str, Engine] = {}


def _start_run(iid):
    eng = Engine(store, sb, step_delay=0.8)
    ENGINES[iid] = eng
    threading.Thread(target=lambda: eng.run(iid), daemon=True).start()


@app.post("/reset")
def reset(body: Optional[dict] = Body(default=None)):
    body = body or {}
    sb.reset(body.get("failures"), body.get("flags"))
    return {"ok": True}


@app.get("/incidents")
def list_incidents():
    return [i.model_dump(mode="json") for i in store.incidents()]


@app.post("/incidents")
def create(body: Optional[dict] = Body(default=None)):
    body = body or {}
    return Engine(store, sb).start(body.get("subject", "ident-jdoe")).model_dump(mode="json")


@app.post("/incidents/{iid}/run")
def run(iid: str):
    _start_run(iid)
    return {"started": iid}


@app.post("/incidents/{iid}/cancel")
def cancel(iid: str):
    if iid in ENGINES:
        ENGINES[iid].cancel()
    return {"cancelled": iid}


@app.post("/incidents/{iid}/actions/{aid}/approve")
def approve(iid: str, aid: str):
    try:
        a = Engine(store, sb).approve(iid, aid)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    if a.status.value == "authorized":
        _start_run(iid)
    return {"action": a.id, "status": a.status.value, "policy": a.policy}


@app.get("/incidents/{iid}")
def get(iid: str):
    return {"report": Engine(store, sb).report(iid), "audit": store.audit_events(iid),
            "checkpoints": len(store.checkpoints(iid))}
