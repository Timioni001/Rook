import hashlib, json, re, sqlite3, threading, time
from .domain import Action, Condition, Incident, fp

SECRET = re.compile(r"sk_test_SYNTH_[\w-]+")


def redact(obj) -> str:
    return SECRET.sub(lambda m: fp(m.group()), json.dumps(obj, default=str))


class Store:
    def __init__(self, path="rook.db"):
        self.c = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.lock = threading.RLock()
        self._x("CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, org TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY, incident_id TEXT, seq INTEGER, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS conditions(incident_id TEXT, id TEXT, seq INTEGER, data TEXT, PRIMARY KEY(incident_id,id))")
        self._x("CREATE TABLE IF NOT EXISTS audit(n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT, event TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS checkpoints(n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT, label TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS sandbox(id INTEGER PRIMARY KEY, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS tool_calls(n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT, action_id TEXT, attempt INTEGER, outcome TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS approvals(n INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, incident_id TEXT, action_id TEXT, decision TEXT, principal TEXT, data TEXT)")
        self._x("CREATE TABLE IF NOT EXISTS runs(incident_id TEXT PRIMARY KEY, owner TEXT, expires REAL)")
        if "hash" not in [r[1] for r in self._x("PRAGMA table_info(audit)")]:
            self._x("ALTER TABLE audit ADD COLUMN hash TEXT")
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
        self._x("INSERT OR REPLACE INTO incidents VALUES(?,?,?)", (inc.id, inc.org, inc.model_dump_json()))

    def incident(self, iid):
        r = self._x("SELECT data FROM incidents WHERE id=?", (iid,))
        return Incident.model_validate_json(r[0][0]) if r else None

    def incidents(self, org=None):
        rows = self._x("SELECT data FROM incidents WHERE org=?", (org,)) if org else self._x("SELECT data FROM incidents")
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
    @staticmethod
    def _chain(prev, ts, iid, event, data):
        return hashlib.sha256(json.dumps([prev, repr(ts), iid, event, data]).encode()).hexdigest()

    def audit(self, iid, event, data=None):
        """Append-only and hash-chained: each event commits to the one before it."""
        with self.lock:
            last = self.c.execute("SELECT hash FROM audit ORDER BY n DESC LIMIT 1").fetchone()
            ts, body = time.time(), redact(data or {})
            h = self._chain(last[0] if last and last[0] else "genesis", ts, iid, event, body)
            self.c.execute("INSERT INTO audit(ts,incident_id,event,data,hash) VALUES(?,?,?,?,?)",
                           (ts, iid, event, body, h))
            self.c.commit()

    def verify_chain(self):
        """Recompute the audit hash chain. Returns (intact, first_bad_event_number, events_checked)."""
        prev, n = "genesis", 0
        for n_, ts, iid, event, data, h in self._x("SELECT n,ts,incident_id,event,data,hash FROM audit ORDER BY n"):
            n += 1
            if h is None:                          # rows written before chaining existed
                continue
            if self._chain(prev, ts, iid, event, data) != h:
                return False, n_, n
            prev = h
        return True, None, n

    def audit_events(self, iid):
        return [{"n": r[0], "ts": r[1], "event": r[2], "data": json.loads(r[3]), "hash": r[4]}
                for r in self._x("SELECT n,ts,event,data,hash FROM audit WHERE incident_id=? ORDER BY n", (iid,))]

    def checkpoint(self, iid, label, data):
        self._x("INSERT INTO checkpoints(ts,incident_id,label,data) VALUES(?,?,?,?)",
                (time.time(), iid, label, redact(data)))

    def checkpoints(self, iid):
        return [{"n": r[0], "ts": r[1], "label": r[2], "data": json.loads(r[3])}
                for r in self._x("SELECT n,ts,label,data FROM checkpoints WHERE incident_id=? ORDER BY n", (iid,))]

    def last_checkpoint(self, iid):
        r = self.checkpoints(iid)
        return r[-1] if r else None

    # tool outcomes + approvals
    def tool_call(self, iid, action_id, attempt, outcome, data=None):
        self._x("INSERT INTO tool_calls(ts,incident_id,action_id,attempt,outcome,data) VALUES(?,?,?,?,?,?)",
                (time.time(), iid, action_id, attempt, outcome, redact(data or {})))

    def tool_calls(self, iid):
        return [{"n": r[0], "ts": r[1], "action": r[2], "attempt": r[3], "outcome": r[4], "data": json.loads(r[5])}
                for r in self._x("SELECT n,ts,action_id,attempt,outcome,data FROM tool_calls WHERE incident_id=? ORDER BY n", (iid,))]

    def approval(self, iid, action_id, decision, principal, data=None):
        self._x("INSERT INTO approvals(ts,incident_id,action_id,decision,principal,data) VALUES(?,?,?,?,?,?)",
                (time.time(), iid, action_id, decision, principal, redact(data or {})))

    def approvals(self, iid):
        return [{"n": r[0], "ts": r[1], "action": r[2], "decision": r[3], "by": r[4], "data": json.loads(r[5])}
                for r in self._x("SELECT n,ts,action_id,decision,principal,data FROM approvals WHERE incident_id=? ORDER BY n", (iid,))]

    # run lease: at most one executor per incident, across threads and processes
    def acquire_run(self, iid, owner, ttl=300):
        now = time.time()
        with self.lock:
            self.c.execute("DELETE FROM runs WHERE incident_id=? AND expires<?", (iid, now))
            try:
                self.c.execute("INSERT INTO runs VALUES(?,?,?)", (iid, owner, now + ttl))
                self.c.commit()
                return True
            except sqlite3.IntegrityError:
                self.c.rollback()
                return False

    def release_run(self, iid, owner):
        self._x("DELETE FROM runs WHERE incident_id=? AND owner=?", (iid, owner))

    def run_active(self, iid):
        return bool(self._x("SELECT 1 FROM runs WHERE incident_id=? AND expires>=?", (iid, time.time())))
