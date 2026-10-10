import json, re, sqlite3, threading, time
from .domain import Action, Condition, Incident, fp

SECRET = re.compile(r"sk_test_SYNTH_[\w-]+")


def redact(obj) -> str:
    return SECRET.sub(lambda m: fp(m.group()), json.dumps(obj, default=str))


class Store:
    def __init__(self, path="rook.db"):
        self.c = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        self._x("CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, incident_id TEXT, seq INTEGER, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS conditions(incident_id TEXT, id TEXT, seq INTEGER, data TEXT, PRIMARY KEY(incident_id,id))")
        self._x("CREATE TABLE IF NOT EXISTS audit(n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT, event TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS checkpoints(n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT, label TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS sandbox(id INTEGER PRIMARY KEY, data TEXT)")
        self._x("CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END")
        self._x("CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END")

    def _x(self, sql, args=()):
        with self.lock:
            cur = self.c.execute(sql, args)
            self.c.commit()
            return cur.fetchall()

    # sandbox state
    def load_sandbox(self):
        r = self._x("SELECT data FROM sandbox WHERE id=1")
        return json.loads(r[0][0]) if r else None

    def save_sandbox(self, s):
        self._x("INSERT OR REPLACE INTO sandbox(id,data) VALUES(1,?)", (json.dumps(s),))

    # incidents
    def save_incident(self, inc: Incident):
        self._x("INSERT OR REPLACE INTO incidents VALUES(?,?)", (inc.id, inc.model_dump_json()))

    def incident(self, iid) -> Incident:
        return Incident.model_validate_json(self._x("SELECT data FROM incidents WHERE id=?", (iid,))[0][0])

    def incidents(self):
        rows = self._x("SELECT data FROM incidents")
        return sorted((Incident.model_validate_json(r[0]) for r in rows), key=lambda i: -i.created_at)

    # actions
    def add_action(self, a: Action, seq: int):
        self._x("INSERT INTO actions VALUES(?,?,?,?)", (a.id, a.incident_id, seq, a.model_dump_json()))

    def save_action(self, a: Action):
        self._x("UPDATE actions SET data=? WHERE id=?", (a.model_dump_json(), a.id))

    def actions(self, iid):
        rows = self._x("SELECT data FROM actions WHERE incident_id=? ORDER BY seq", (iid,))
        return [Action.model_validate_json(r[0]) for r in rows]

    # closure conditions
    def save_conditions(self, iid, conds):
        for i, c in enumerate(conds):
            self._x("INSERT OR REPLACE INTO conditions(incident_id,id,seq,data) VALUES(?,?,?,?)",
                    (iid, c.id, i, c.model_dump_json()))

    def conditions(self, iid):
        rows = self._x("SELECT data FROM conditions WHERE incident_id=? ORDER BY seq", (iid,))
        return [Condition.model_validate_json(r[0]) for r in rows]

    # audit + checkpoints (secrets redacted before write)
    def audit(self, iid, event, data=None):
        self._x("INSERT INTO audit(ts,incident_id,event,data) VALUES(?,?,?,?)",
                (time.time(), iid, event, redact(data or {})))

    def audit_events(self, iid):
        return [{"n": r[0], "ts": r[1], "event": r[2], "data": json.loads(r[3])}
                for r in self._x("SELECT n,ts,event,data FROM audit WHERE incident_id=? ORDER BY n", (iid,))]

    def checkpoint(self, iid, label, data):
        self._x("INSERT INTO checkpoints(ts,incident_id,label,data) VALUES(?,?,?,?)",
                (time.time(), iid, label, redact(data)))

    def checkpoints(self, iid):
        return [{"n": r[0], "ts": r[1], "label": r[2], "data": json.loads(r[3])}
                for r in self._x("SELECT n,ts,label,data FROM checkpoints WHERE incident_id=? ORDER BY n", (iid,))]
