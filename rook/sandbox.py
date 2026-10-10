"""Five stateful sandbox adapters over one persisted local state. Synthetic secrets only."""
from .domain import fp


class Transient(Exception): ...
class Permanent(Exception): ...
class Timeout(Exception): ...


OLD = "sk_test_SYNTH_payments_v1"
OTHER = "sk_test_SYNTH_other_v1"


def seed() -> dict:
    return {
        "github": {
            "accounts": {
                "jdoe": {"status": "disabled", "owner": "ident-jdoe"},
                "asmith": {"status": "active", "owner": "ident-asmith"},
            },
            "repos": {"billing-api": {".env.test": f"PAYMENTS_KEY={OLD}"}},
        },
        "cloud": {"accounts": {
            "jdoe": {"status": "active", "owner": "ident-jdoe"},
            "asmith": {"status": "active", "owner": "ident-asmith"}}},
        "pm": {"accounts": {
            "jdoe": {"status": "active", "owner": "ident-jdoe"},
            "ghost": {"status": "active", "owner": None}}},      # orphaned account fixture
        "vault": {"credentials": {
            "cred-pay": {"owner": "ident-jdoe", "status": "active", "value": OLD,
                         "version": 1, "revoked": [], "used_by": ["billing-app"]},
            "cred-other": {"owner": "ident-asmith", "status": "active", "value": OTHER,
                           "version": 1, "revoked": [], "used_by": ["reports-app"]},
        }},
        "apps": {"billing-app": {"config": {"api_key": OLD}},
                 "reports-app": {"config": {"api_key": OTHER}}},
        "failures": {"app.repair": ["transient"]},   # signature scenario
        "flags": {},
        "applied": {}, "calls": 0, "rotations": 0,
    }


class Adapter:
    def __init__(self, core):
        self.core = core

    @property
    def s(self):
        return self.core.s


class AccountService(Adapter):
    def __init__(self, core, name):
        super().__init__(core)
        self.name = name

    def accounts(self):
        return self.s[self.name]["accounts"]

    def status(self, user):
        return self.accounts().get(user, {}).get("status")

    def owner(self, user):
        return self.accounts().get(user, {}).get("owner")

    def disable(self, user, idem):
        def fn():
            self.accounts()[user]["status"] = "disabled"
            return {"service": self.name, "user": user, "status": "disabled"}
        return self.core.mutate(f"disable:{self.name}", idem, fn)


class SourceHost(AccountService):
    def find_secret(self, value):
        """Paths only; the secret value never leaves this method."""
        return [f"{r}/{f}" for r, files in self.s["github"]["repos"].items()
                for f, txt in files.items() if value in txt]


class Vault(Adapter):
    def creds(self):
        return self.s["vault"]["credentials"]

    def owner(self, cid):
        return self.creds().get(cid, {}).get("owner")

    def used_by(self, cid):
        return list(self.creds()[cid]["used_by"])

    def version(self, cid):
        return self.creds()[cid]["version"]

    def current_fp(self, cid):
        return fp(self.creds()[cid]["value"])

    def accepts_current(self, cid):
        return self.creds()[cid]["status"] == "active"

    def accepts_fp(self, f):
        return any(c["status"] == "active" and fp(c["value"]) == f for c in self.creds().values())

    def rotate(self, cid, idem):
        def fn():
            c = self.creds()[cid]
            if self.s["flags"].get("rotate_noop"):      # reports success, changes nothing
                return {"cred": cid, "new_fp": fp(c["value"]), "version": c["version"]}
            c["revoked"].append(c["value"])
            c["version"] += 1
            c["value"] = f"sk_test_SYNTH_{cid}_v{c['version']}"
            if self.s["flags"].get("bad_replacement"):  # replacement issued but unusable
                c["status"] = "invalid"
            self.s["rotations"] += 1
            return {"cred": cid, "new_fp": fp(c["value"]), "version": c["version"]}
        return self.core.mutate("vault.rotate", idem, fn)


class InternalApp(Adapter):
    def config_fp(self, app):
        return fp(self.s["apps"][app]["config"]["api_key"])

    def repair_config(self, app, cred_id, idem):
        def fn():
            value = self.s["vault"]["credentials"][cred_id]["value"]
            if self.s["flags"].get("faulty_patch"):
                value = "sk_test_SYNTH_wrong"
            self.s["apps"][app]["config"]["api_key"] = value
            return {"app": app, "config_fp": fp(value)}
        return self.core.mutate("app.repair", idem, fn)

    def health(self, app):
        """Regression/health check: configured key is accepted and the app is healthy."""
        key_ok = self.core.vault.accepts_fp(self.config_fp(app))
        return bool(key_ok and not self.s["flags"].get("unhealthy_app"))


class Sandbox:
    def __init__(self, store, failures=None, flags=None):
        self.store = store
        s = store.load_sandbox()
        if s is None:
            s = seed()
            if failures is not None:
                s["failures"] = failures
            if flags is not None:
                s["flags"] = flags
            store.save_sandbox(s)
        self.s = s
        self.github = SourceHost(self, "github")
        self.cloud = AccountService(self, "cloud")
        self.pm = AccountService(self, "pm")
        self.vault = Vault(self)
        self.apps = InternalApp(self)

    def account_service(self, name):
        return {"github": self.github, "cloud": self.cloud, "pm": self.pm}[name]

    def reset(self, failures=None, flags=None):
        self.s = seed()
        if failures is not None:
            self.s["failures"] = failures
        if flags is not None:
            self.s["flags"] = flags
        self._save()

    def _save(self):
        self.store.save_sandbox(self.s)

    def mutate(self, op, idem, fn):
        """Idempotency + deterministic failure injection for every state change."""
        self.s["calls"] += 1
        if idem in self.s["applied"]:
            self._save()
            return {**self.s["applied"][idem], "replayed": True}
        q = self.s["failures"].get(op) or []
        kind = q.pop(0) if q else None
        if kind == "transient":
            self._save(); raise Transient(op)
        if kind == "permanent":
            self._save(); raise Permanent(f"{op}: permission denied")
        if kind == "timeout_lost":        # request lost, nothing applied
            self._save(); raise Timeout(op)
        res = fn()
        self.s["applied"][idem] = res
        self._save()
        if kind == "timeout_applied":     # applied, but the caller never saw the response
            raise Timeout(op)
        return res
