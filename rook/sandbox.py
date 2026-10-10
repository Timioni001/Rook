"""Five stateful SANDBOXED MOCK adapters over one persisted local state: one small company.

Nothing here talks to a real system. All credentials are synthetic (sk_test_SYNTH_*).
Every state change goes through Sandbox.mutate(), which provides idempotency and
deterministic failure injection so recovery paths can be demonstrated and tested.
"""
import copy
from .domain import fp


class Transient(Exception): ...
class Permanent(Exception): ...
class Timeout(Exception): ...


OLD = "sk_test_SYNTH_payments_v1"
REPORTS = "sk_test_SYNTH_reports_v1"

# name -> (description, failures, flags). Failures are consumed in order per operation.
SCENARIOS = {
    "signature": ("billing-app's config API returns a 503 once while Rook moves it to the new key",
                  {"app.update_config": ["transient"]}, {}),
    "clean": ("No injected faults", {}, {}),
    "ambiguous_applied": ("payments-worker update times out but was actually applied",
                          {"cloud.update_env": ["timeout_applied"]}, {}),
    "ambiguous_lost": ("payments-worker update times out and was not applied",
                       {"cloud.update_env": ["timeout_lost"]}, {}),
    "persistent": ("billing-app's config API keeps failing", {"app.update_config": ["transient"] * 20}, {}),
    "permission_denied": ("Cloud refuses to disable the leftover account",
                          {"disable:cloud": ["permanent"]}, {}),
    "revoke_noop": ("Vault reports the old key revoked but it still works", {}, {"revoke_noop": True}),
    "replacement_invalid": ("Vault issues a replacement key that does not work", {}, {"replacement_invalid": True}),
    "faulty_update": ("billing-app accepts the update but stores the wrong key", {}, {"faulty_update": ["app:billing-app"]}),
    "regression_fail": ("billing-app is healthy but its payment regression test fails", {},
                        {"regression_fail": ["app:billing-app"]}),
    # service outage playbook
    "outage": ("checkout-api's rollback call times out, but the rollback did happen",
               {"cloud.rollback": ["timeout_applied"]}, {}),
    "outage_clean": ("checkout-api outage with no injected faults", {}, {}),
    "outage_wrong_cause": ("Rolling back does not fix checkout-api: the deploy is not the cause", {},
                           {"outage_persists": ["checkout-api"]}),
    "outage_rollback_down": ("The cloud's rollback API keeps failing", {"cloud.rollback": ["transient"] * 20}, {}),
}
SCENARIO_PLAYBOOK = {k: "outage" for k in SCENARIOS if k.startswith("outage")}


def playbook_of(scenario):
    return SCENARIO_PLAYBOOK.get(scenario or "", "offboarding")


def seed() -> dict:
    return {
        "directory": {   # identity provider, read via the internal app
            "ident-jdoe": {"name": "Jordan Doe", "type": "contractor", "employer": "Northwind Consulting",
                           "status": "disabled", "disabled_at": "2026-10-09T17:30:00Z", "manager": "ident-asmith"},
            "ident-asmith": {"name": "Alex Smith", "type": "employee", "status": "active"},
        },
        "github": {
            "accounts": {"jdoe": {"status": "disabled", "owner": "ident-jdoe"},
                         "asmith": {"status": "active", "owner": "ident-asmith"}},
            "repos": {"billing-api": {".env.test": f"PAYMENTS_KEY={OLD}", "README.md": "billing api"}},
            "audit_log": [{"event": "file_committed", "repo": "billing-api", "path": ".env.test",
                           "actor": "jdoe", "at": "2026-06-02T11:04:00Z"}],
        },
        "cloud": {
            "accounts": {"jdoe": {"status": "active", "owner": "ident-jdoe"},
                         "asmith": {"status": "active", "owner": "ident-asmith"}},
            "services": {"payments-worker": {"env": {"PAYMENTS_KEY": OLD}, "team": "payments"},
                         "reports-cron": {"env": {"REPORTS_KEY": REPORTS}, "team": "analytics"}},
            # revisioned deployments + their auto-deploy pipeline (service outage playbook)
            "deployments": {"checkout-api": {"team": "commerce", "current": 42, "revisions": {
                "41": {"env": {"DB_HOST": "db-primary"}, "deployed_at": "2026-10-09T08:40:00Z",
                       "deployed_by": "deploy-bot", "commit": "4b1d0a7", "message": "Add order notes field",
                       "healthy_minutes": 1452},
                "42": {"env": {"DB_HOST": "db-replica-old"}, "deployed_at": "2026-10-10T08:52:00Z",
                       "deployed_by": "deploy-bot", "commit": "9f3c2e1", "message": "Point checkout at new database host",
                       "healthy_minutes": 0}}}},
            "pipelines": {"checkout-api": {"auto_deploy": True, "desired": 42, "blocked": []}},
            "databases": {"db-primary": "up", "db-replica-old": "decommissioned"},
        },
        "pm": {
            "accounts": {"jdoe": {"status": "active", "owner": "ident-jdoe"},
                         "ghost": {"status": "active", "owner": None}},     # orphaned account fixture
            "tickets": {"OPS-112": {"title": "Offboard contractor Jordan Doe", "status": "done",
                                    "subject": "ident-jdoe", "comments": []},
                        "OPS-131": {"title": "ALERT: checkout-api 5xx error rate above 30%", "status": "open",
                                    "kind": "alert", "subject": "cloud:checkout-api",
                                    "opened_at": "2026-10-10T08:53:00Z", "comments": []}},
            "next_ticket": 200,
        },
        "vault": {"credentials": {
            "cred-pay": {"owner": "ident-jdoe", "purpose": "Payments provider API key",
                         "created_by": "jdoe", "created_at": "2026-03-14T09:12:00Z",
                         "versions": [{"v": 1, "value": OLD, "status": "active"}],
                         # vault metadata is incomplete on purpose: payments-worker is only found by scanning
                         "used_by": ["app:billing-app"]},
            "cred-reports": {"owner": "ident-asmith", "purpose": "Reporting warehouse key",
                             "created_by": "asmith", "created_at": "2026-01-05T10:00:00Z",
                             "versions": [{"v": 1, "value": REPORTS, "status": "active"}],
                             "used_by": ["app:reports-app", "cloud:reports-cron"]},
        }},
        "apps": {"billing-app": {"config": {"PAYMENTS_KEY": OLD}},
                 "reports-app": {"config": {"REPORTS_KEY": REPORTS}},
                 "storefront": {"config": {"CHECKOUT_URL": "https://checkout-api.internal"}}},
        "failures": {}, "flags": {}, "applied": {}, "calls": 0, "mutations": 0,
    }


class Adapter:
    def __init__(self, core):
        self.core = core

    @property
    def s(self):
        return self.core.s


class AccountService(Adapter):
    """Accounts on github (source host), cloud and pm share this behaviour."""
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
    """Adapter 1: source-code host."""
    def find_secret(self, f):
        """Paths of files containing a secret with fingerprint f. Values never leave this method."""
        out = []
        for repo, files in self.s["github"]["repos"].items():
            for path, txt in files.items():
                for token in txt.replace("=", " ").split():
                    if token.startswith("sk_test_SYNTH") and fp(token) == f:
                        out.append(f"{repo}/{path}")
        return out

    def scrub_secret(self, path, f, idem):
        """Replace the leaked value in a tracked file with a placeholder (history still holds it)."""
        def fn():
            repo, file = path.split("/", 1)
            txt = self.s["github"]["repos"][repo][file]
            for token in txt.replace("=", " ").split():
                if token.startswith("sk_test_SYNTH") and fp(token) == f:
                    txt = txt.replace(token, "<removed by Rook: key rotated>")
            self.s["github"]["repos"][repo][file] = txt
            return {"path": path, "scrubbed": True}
        return self.core.mutate("github.scrub", idem, fn)

    def commit_history(self, path):
        repo, file = path.split("/", 1)
        return [e for e in self.s["github"]["audit_log"] if e["repo"] == repo and e["path"] == file]


class Cloud(AccountService):
    """Adapter 2: cloud environment (accounts + services with environment variables)."""
    def services(self):
        return self.s["cloud"]["services"]

    def env_fps(self, svc):
        return {k: fp(v) for k, v in self.services()[svc]["env"].items()}

    def set_secret_env(self, svc, cred_id, idem):
        def fn():
            env = self.services()[svc]["env"]
            key = next(k for k, v in env.items() if v.startswith("sk_test_SYNTH"))
            env[key] = self.core.vault.latest(cred_id)["value"]
            if svc in self.s["flags"].get("faulty_update", []) or f"cloud:{svc}" in self.s["flags"].get("faulty_update", []):
                env[key] = "sk_test_SYNTH_wrong"
            return {"dependent": f"cloud:{svc}", "env_key": key, "config_fp": fp(env[key])}
        return self.core.mutate("cloud.update_env", idem, fn)

    # ---- revisioned deployments and the pipeline that keeps redeploying its desired revision ----
    def deployment(self, svc):
        return self.s["cloud"]["deployments"][svc]

    def revision(self, svc, rev):
        return self.deployment(svc)["revisions"][str(rev)]

    def pipeline(self, svc):
        return self.s["cloud"]["pipelines"][svc]

    def database(self, host):
        return self.s["cloud"]["databases"].get(host, "unknown")

    def service_healthy(self, svc):
        """Health probe: the running revision reaches a working database and nothing else is wrong."""
        env = self.revision(svc, self.deployment(svc)["current"])["env"]
        return self.database(env.get("DB_HOST")) == "up" and svc not in self.s["flags"].get("outage_persists", [])

    def error_rate(self, svc):
        return 0.004 if self.service_healthy(svc) else 0.38

    def pause_pipeline(self, svc, idem):
        def fn():
            self.pipeline(svc)["auto_deploy"] = False
            return {"service": svc, "auto_deploy": False}
        return self.core.mutate("cloud.pipeline_pause", idem, fn)

    def rollback(self, svc, rev, idem):
        def fn():
            d, p = self.deployment(svc), self.pipeline(svc)
            d["current"] = rev
            out = {"service": svc, "running_revision": rev}
            # what bites people: an auto-deploy pipeline puts its desired revision straight back
            if p["auto_deploy"] and p["desired"] != rev and p["desired"] not in p["blocked"]:
                d["current"] = p["desired"]
                out["pipeline_redeployed"] = p["desired"]
            return out
        return self.core.mutate("cloud.rollback", idem, fn)

    def resume_pipeline(self, svc, block_rev, idem):
        def fn():
            p = self.pipeline(svc)
            if block_rev not in p["blocked"]:
                p["blocked"].append(block_rev)
            p["desired"] = self.deployment(svc)["current"]
            p["auto_deploy"] = True
            return {"service": svc, "auto_deploy": True, "blocked": list(p["blocked"]), "desired": p["desired"]}
        return self.core.mutate("cloud.pipeline_resume", idem, fn)


class InternalApp(Adapter):
    """Adapter 3: internal application (config, health, regression suite) + identity directory."""
    def directory(self, ident):
        return dict(self.s["directory"].get(ident, {}))

    def apps(self):
        return self.s["apps"]

    def config_fps(self, app):
        return {k: fp(v) for k, v in self.apps()[app]["config"].items()}

    def set_secret_config(self, app, cred_id, idem):
        def fn():
            cfg = self.apps()[app]["config"]
            key = next(k for k, v in cfg.items() if v.startswith("sk_test_SYNTH"))
            cfg[key] = self.core.vault.latest(cred_id)["value"]
            if f"app:{app}" in self.s["flags"].get("faulty_update", []):
                cfg[key] = "sk_test_SYNTH_wrong"
            return {"dependent": f"app:{app}", "config_key": key, "config_fp": fp(cfg[key])}
        return self.core.mutate("app.update_config", idem, fn)


class ProjectTracker(Adapter):
    """Adapter 4: project-management system (offboarding tickets, incident tickets)."""
    def tickets(self):
        return self.s["pm"]["tickets"]

    def open_alerts(self):
        return {tid: t for tid, t in self.tickets().items() if t.get("kind") == "alert" and t["status"] == "open"}

    def completed_offboardings(self):
        return {tid: t for tid, t in self.tickets().items()
                if t.get("subject") and t["status"] == "done" and t["title"].startswith("Offboard")}

    def open_ticket(self, title, subject, idem):
        def fn():
            n = self.s["pm"]["next_ticket"]
            self.s["pm"]["next_ticket"] += 1
            tid = f"SEC-{n}"
            self.tickets()[tid] = {"title": title, "status": "open", "subject": subject, "comments": []}
            return {"ticket": tid}
        return self.core.mutate("pm.open_ticket", idem, fn)

    def comment(self, tid, text, idem):
        def fn():
            self.tickets()[tid]["comments"].append(text)
            return {"ticket": tid}
        return self.core.mutate("pm.comment", idem, fn)

    def set_status(self, tid, status, idem):
        def fn():
            self.tickets()[tid]["status"] = status
            return {"ticket": tid, "status": status}
        return self.core.mutate("pm.set_status", idem, fn)


class Vault(Adapter):
    """Adapter 5: credential vault with versioned secrets."""
    def creds(self):
        return self.s["vault"]["credentials"]

    def meta(self, cid):
        c = self.creds().get(cid)
        if c is None:
            return None
        return {k: v for k, v in c.items() if k != "versions"} | {
            "versions": [{"v": x["v"], "status": x["status"], "fp": fp(x["value"])} for x in c["versions"]]}

    def owner(self, cid):
        return self.creds().get(cid, {}).get("owner")

    def latest(self, cid):
        return self.creds()[cid]["versions"][-1]

    def version_info(self, cid, v):
        x = next((x for x in self.creds()[cid]["versions"] if x["v"] == v), None)
        return None if x is None else {"v": x["v"], "status": x["status"], "fp": fp(x["value"])}

    def authenticate_fp(self, f):
        """Live probe: would a request signed with the key of fingerprint f be accepted?"""
        if f in self.s["flags"].get("_noop_revoked", []):
            return True
        return any(x["status"] == "active" and fp(x["value"]) == f
                   for c in self.creds().values() for x in c["versions"])

    def find_by_fp(self, f):
        return next((cid for cid, c in self.creds().items() for x in c["versions"] if fp(x["value"]) == f), None)

    def issue_replacement(self, cid, idem):
        def fn():
            c = self.creds()[cid]
            v = c["versions"][-1]["v"] + 1
            status = "invalid" if self.s["flags"].get("replacement_invalid") else "active"
            c["versions"].append({"v": v, "value": f"sk_test_SYNTH_{cid}_v{v}", "status": status})
            return {"cred": cid, "version": v, "new_fp": fp(c["versions"][-1]["value"])}
        return self.core.mutate("vault.issue", idem, fn)

    def revoke(self, cid, version, idem):
        def fn():
            x = next(x for x in self.creds()[cid]["versions"] if x["v"] == version)
            if self.s["flags"].get("revoke_noop"):         # reports success, key keeps working
                self.s["flags"].setdefault("_noop_revoked", []).append(fp(x["value"]))
            x["status"] = "revoked"
            return {"cred": cid, "version": version, "status": "revoked"}
        return self.core.mutate("vault.revoke", idem, fn)


class Sandbox:
    def __init__(self, store, failures=None, flags=None, scenario=None):
        self.store = store
        s = store.load_sandbox()
        if s is None or scenario is not None:
            s = self._seeded(failures, flags, scenario)
            store.save_sandbox(s)
        self.s = s
        self.github = SourceHost(self, "github")
        self.cloud = Cloud(self, "cloud")
        self.pm = ProjectTracker(self)
        self.pm_accounts = AccountService(self, "pm")
        self.vault = Vault(self)
        self.apps = InternalApp(self)

    @staticmethod
    def _seeded(failures=None, flags=None, scenario=None):
        s = seed()
        if scenario is not None:
            _, f, fl = SCENARIOS[scenario]
            s["failures"], s["flags"] = copy.deepcopy(f), copy.deepcopy(fl)
            s["scenario"] = scenario
        if failures is not None:
            s["failures"] = failures
        if flags is not None:
            s["flags"] = flags
        return s

    def account_service(self, name):
        return {"github": self.github, "cloud": self.cloud, "pm": self.pm_accounts}[name]

    def reset(self, failures=None, flags=None, scenario=None):
        self.s = self._seeded(failures, flags, scenario)
        self._save()

    def reload(self):
        s = self.store.load_sandbox()
        if s is not None:
            self.s = s

    def _save(self):
        self.store.save_sandbox(self.s)

    # ---- dependents: anything configured with a credential, found by scanning live config ----
    def dependents_of_fp(self, f):
        deps = []
        for app in sorted(self.apps.apps()):
            if f in self.apps.config_fps(app).values():
                deps.append(f"app:{app}")
        for svc in sorted(self.cloud.services()):
            if f in self.cloud.env_fps(svc).values():
                deps.append(f"cloud:{svc}")
        return deps

    def dependent_config_fp(self, dep):
        kind, name = dep.split(":", 1)
        fps = self.apps.config_fps(name) if kind == "app" else self.cloud.env_fps(name)
        return next(iter(fps.values()), None)

    def restore_dependent(self, dep, cred_id, version, idem):
        """Compensating action: put a dependent back on a known-good (still valid) key version."""
        kind, name = dep.split(":", 1)
        value = next(x["value"] for x in self.vault.creds()[cred_id]["versions"] if x["v"] == version)

        def fn():
            cfg = self.apps.apps()[name]["config"] if kind == "app" else self.cloud.services()[name]["env"]
            key = next(k for k, v in cfg.items() if v.startswith("sk_test_SYNTH"))
            cfg[key] = value
            return {"dependent": dep, "restored_version": version, "config_fp": fp(value)}
        return self.mutate(f"{kind}.restore", idem, fn)

    def callers_of(self, svc):
        """Apps whose configuration points at a cloud service (found by scanning config)."""
        return [f"app:{a}" for a, x in sorted(self.apps.apps().items())
                if any(f"//{svc}." in str(v) for v in x["config"].values())]

    def caller_healthy(self, dep, svc):
        """A caller is healthy when the service it depends on is."""
        return dep in self.callers_of(svc) and self.cloud.service_healthy(svc)

    def synthetic_checkout(self, svc):
        """End-to-end probe: place a test order through storefront -> checkout-api -> database."""
        return self.cloud.service_healthy(svc) and f"cloud:{svc}" not in self.s["flags"].get("regression_fail", [])

    def ownerless_accounts(self):
        out = []
        for name in ("github", "cloud", "pm"):
            for u, a in self.account_service(name).accounts().items():
                if not a.get("owner"):
                    out.append({"service": name, "user": u, "status": a["status"]})
        return out

    def update_dependent(self, dep, cred_id, idem):
        kind, name = dep.split(":", 1)
        if kind == "app":
            return self.apps.set_secret_config(name, cred_id, idem)
        if kind == "cloud":
            return self.cloud.set_secret_env(name, cred_id, idem)
        raise Permanent(f"unknown dependent kind {kind}")

    def health(self, dep):
        """Health probe: the dependent's configured key authenticates and the service is up."""
        f = self.dependent_config_fp(dep)
        return bool(f and self.vault.authenticate_fp(f) and dep not in self.s["flags"].get("unhealthy", []))

    def regression(self, dep):
        """Regression suite (e.g. a synthetic test charge for billing-app)."""
        return self.health(dep) and dep not in self.s["flags"].get("regression_fail", [])

    def mutate(self, op, idem, fn):
        """Idempotency + deterministic failure injection for every state change."""
        self.s["calls"] += 1
        if idem in self.s["applied"]:
            self._save()
            return {**self.s["applied"][idem], "replayed": True}
        q = self.s["failures"].get(op) or []
        kind = q.pop(0) if q else None
        if kind == "transient":
            self._save(); raise Transient(f"{op}: 503 service unavailable")
        if kind == "permanent":
            self._save(); raise Permanent(f"{op}: permission denied")
        if kind == "timeout_lost":        # request lost, nothing applied
            self._save(); raise Timeout(op)
        res = fn()
        self.s["mutations"] += 1
        self.s["applied"][idem] = res
        self._save()
        if kind == "timeout_applied":     # applied, but the caller never saw the response
            raise Timeout(op)
        return res
