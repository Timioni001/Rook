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


# Plain names for the clinics, because "cardiology" is not what a patient calls it.
SPECIALTY = {"cardiology": "heart clinic", "dermatology": "skin clinic"}

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
    # leaked-secret playbook
    "leak": ("reports-app's config API returns a 503 once while Rook moves it to the new key",
             {"app.update_config": ["transient"]}, {}),
    "leak_clean": ("A scanner finds a live key in an internal repo; no injected faults", {}, {}),
    "leak_already_revoked": ("The scanner's finding is a key that was already revoked, so rotating it would be "
                             "pointless churn", {}, {"leak_already_revoked": True}),
    "leak_unattributed": ("The leaked key matches no credential Rook can attribute to an owner", {},
                          {"leak_unattributed": True}),
    # referral & result follow-up playbook
    "referral": ("The clinic's booking system fails once while Rook is booking the appointment",
                 {"booking.book": ["transient"]}, {}),
    "referral_clean": ("Four things the record says are done. Three of them never happened", {}, {}),
    "referral_critical": ("One of the results is urgent, so what to do about it is a doctor's decision "
                          "and Rook will not touch it", {}, {"referral_critical": True}),
    "referral_unreachable": ("Every phone number on file for the patient is out of date, so she cannot "
                             "be told", {}, {"referral_unreachable": True}),
    # a doctor calls in sick and their whole list has to be moved
    "cover": ("The appointment book rejects one move, then accepts it",
              {"schedule.move": ["transient"]}, {"doctor_off": "clin-okafor"}),
    "cover_clean": ("A doctor calls in sick with 12 people booked in. No injected faults", {},
                    {"doctor_off": "clin-okafor"}),
    "cover_short": ("Only four colleagues' slots are free, so most of the list cannot be moved at all", {},
                    {"doctor_off": "clin-okafor", "slots_short": 4}),
    "cover_unreachable": ("One patient's phone number is out of date, so Rook will not move her appointment "
                          "without telling her", {},
                          {"doctor_off": "clin-okafor", "patient_unreachable": "pat-05"}),
    "cover_half": ("Colleagues can take half the list, so the other half stays with reception", {},
                   {"doctor_off": "clin-okafor", "slots_short": 6}),
    "cover_nobody_reachable": ("Nobody on the list can be contacted, so Rook moves none of them", {},
                               {"doctor_off": "clin-okafor", "unreachable_count": 12}),
    "referral_all_good": ("Everything the record says is done really is done, so there is nothing to fix", {},
                          {"care_all_done": True}),
}
SCENARIO_PLAYBOOK = {k: "outage" for k in SCENARIOS if k.startswith("outage")}
SCENARIO_PLAYBOOK |= {k: "leak" for k in SCENARIOS if k.startswith("leak")}
SCENARIO_PLAYBOOK |= {k: "care" for k in SCENARIOS if k.startswith("referral")}
SCENARIO_PLAYBOOK |= {k: "cover" for k in SCENARIOS if k.startswith("cover")}


def playbook_of(scenario):
    return SCENARIO_PLAYBOOK.get(scenario or "", "offboarding")


# A single clinic day: one doctor's list, and the colleagues who could absorb it.
DAY = "2026-10-12"
_PEOPLE = [
    ("Amara Chukwu", "09:00", "Blood pressure review"), ("Tomas Varga", "09:20", "Knee pain, follow-up"),
    ("Mei Lin Chan", "09:40", "Asthma review"), ("Yusuf Demir", "10:00", "Diabetes check"),
    ("Sofia Rossi", "10:20", "Rash, second visit"), ("Kwame Mensah", "10:40", "Back pain"),
    ("Hana Kovac", "11:00", "Thyroid results"), ("Diego Morales", "11:20", "Chest infection follow-up"),
    ("Priya Raman", "14:00", "Migraine review"), ("Noah Fischer", "14:20", "Ankle sprain"),
    ("Leila Haddad", "14:40", "Anxiety follow-up"), ("Sam Okonkwo", "15:00", "Medication review"),
]


def _clinic_day(n=None):
    """People booked in with one doctor, and two colleagues with room to take them."""
    n = len(_PEOPLE) if n is None else max(1, min(n, len(_PEOPLE)))
    patients, appts = {}, {}
    for i, (name, at, reason) in enumerate(_PEOPLE[:n], start=1):
        pid = f"pat-{i:02d}"
        patients[pid] = {"name": name, "born": "",
                         "channels": [{"kind": "text message", "value": f"mobile ending {1000 + i * 7}",
                                       "status": "active"}],
                         "opted_out": []}
        appts[f"ap-{i:02d}"] = {"patient": pid, "doctor": "clin-okafor", "at": f"{DAY}T{at}:00Z",
                                "status": "booked", "reason": reason}
    # Two colleagues, with free slots at roughly the same times.
    free = {"clin-bauer": [f"{DAY}T{t}:00Z" for t in
                           ("09:10", "09:30", "09:50", "10:10", "10:30", "10:50", "11:10")],
            "clin-ndiaye": [f"{DAY}T{t}:00Z" for t in ("14:10", "14:30", "14:50", "15:10", "15:30")]}
    return patients, appts, free


def seed(patients=None) -> dict:
    _day_patients, _day_appts, _day_free = _clinic_day(patients)
    return {
        "directory": {   # identity provider, read via the internal app
            "ident-jdoe": {"name": "Jordan Doe", "type": "contractor", "employer": "Northwind Consulting",
                           "status": "disabled", "disabled_at": "2026-10-09T17:30:00Z", "manager": "ident-asmith"},
            "ident-asmith": {"name": "Alex Smith", "type": "employee", "status": "active"},
        },
        "github": {
            "accounts": {"jdoe": {"status": "disabled", "owner": "ident-jdoe"},
                         "asmith": {"status": "active", "owner": "ident-asmith"}},
            "repos": {"billing-api": {".env.test": f"PAYMENTS_KEY={OLD}", "README.md": "billing api"},
                       # internal repo: where the secrets scanner finds the reporting key (leak playbook)
                       "analytics-jobs": {"config/settings.yml": f"warehouse_key: {REPORTS}\nschedule: nightly",
                                          "README.md": "nightly analytics jobs"}},
            "audit_log": [{"event": "file_committed", "repo": "billing-api", "path": ".env.test",
                           "actor": "jdoe", "at": "2026-06-02T11:04:00Z"},
                          {"event": "file_committed", "repo": "analytics-jobs", "path": "config/settings.yml",
                           "actor": "asmith", "at": "2026-04-21T14:26:00Z"}],
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
                                    "opened_at": "2026-10-10T08:53:00Z", "comments": []},
                        "SEC-240": {"title": "SCANNER: hardcoded credential in analytics-jobs", "status": "open",
                                    "kind": "leak", "path": "analytics-jobs/config/settings.yml",
                                    "scanner": "secret-scanner", "opened_at": "2026-10-10T07:15:00Z",
                                    "comments": []}},
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
        # ---- care coordination: the three systems a referral falls between ----
        "records": {       # the clinic's own record system
            "clinic": "northside",
            "clinicians": {"clin-okafor": {"name": "Dr Ada Okafor", "pager": "pg-okafor", "status": "on duty"}},
            "patients": {
                **_day_patients,
                "pat-alvarez": {"name": "Maria Alvarez", "born": "1968-03-11",
                                # the number on file is the one she changed last year
                                "channels": [{"kind": "text message", "value": "mobile ending 0102", "status": "stale"},
                                             {"kind": "phone call", "value": "home number ending 0177", "status": "active"},
                                             {"kind": "app message", "value": "m.alvarez", "status": "active"}],
                                "opted_out": ["email"]},
                "pat-osei": {"name": "Daniel Osei", "born": "1991-07-02",
                             "channels": [{"kind": "text message", "value": "mobile ending 0310", "status": "active"},
                                          {"kind": "phone call", "value": "mobile ending 0311", "status": "active"}],
                             "opted_out": []},
                "pat-rivera": {"name": "Lucia Rivera", "born": "1980-12-19",
                               "channels": [{"kind": "text message", "value": "mobile ending 0455", "status": "active"}],
                               "opted_out": []},
            },
            # Four handoffs the record calls done. Three of them never happened.
            "orders": {
                "ord-7741": {"patient": "pat-alvarez", "kind": "referral", "specialty": "cardiology",
                             "reason": "Abnormal ECG: new left bundle branch block",
                             "ordered_by": "clin-okafor", "ordered_at": "2026-09-28T09:20:00Z",
                             "urgency": "routine",
                             "record_status": "sent", "sent_via": "the old fax line", "loop_closed": False},
                "ord-7742": {"patient": "pat-alvarez", "kind": "result",
                             "reason": "Lipid panel: LDL 214 mg/dL, well above range",
                             "ordered_by": "clin-okafor", "ordered_at": "2026-09-30T07:45:00Z",
                             "urgency": "routine",
                             "record_status": "filed", "loop_closed": False},
                "ord-7743": {"patient": "pat-osei", "kind": "prescription", "drug": "Atorvastatin 20mg",
                             "reason": "Started after raised cholesterol",
                             "ordered_by": "clin-okafor", "ordered_at": "2026-10-01T16:10:00Z",
                             "urgency": "routine",
                             "record_status": "sent to pharmacy", "loop_closed": False},
                # This one genuinely completed. Rook has to notice and leave it alone.
                "ord-7744": {"patient": "pat-rivera", "kind": "referral", "specialty": "dermatology",
                             "reason": "Changing mole on left shoulder",
                             "ordered_by": "clin-okafor", "ordered_at": "2026-09-22T11:00:00Z",
                             "urgency": "routine",
                             "record_status": "sent", "sent_via": "their booking system", "loop_closed": True},
            },
            "results": {"ord-7742": {"kind": "Lipid panel", "finding": "LDL 214 mg/dL",
                                     "flag": "abnormal", "reported_at": "2026-09-30T07:45:00Z"}},
            "acknowledgements": {},   # order id -> clinician who signed it off
            "notifications": [],      # pages sent to a clinician
        },
        "booking": {       # the specialist clinics' scheduling systems
            "inboxes": {"cardiology": {"channels": {"the old fax line": "switched off",
                                                    "their booking system": "active"},
                                       "received": []},
                        "dermatology": {"channels": {"their booking system": "active"},
                                        "received": ["ord-7744"]}},
            "slots": {"cardiology": ["2026-10-21T10:30:00Z", "2026-10-23T14:00:00Z"],
                      "dermatology": ["2026-11-04T09:00:00Z"]},
            "appointments": {"appt-0": {"patient": "pat-rivera", "specialty": "dermatology",
                                        "at": "2026-10-18T09:30:00Z", "status": "booked", "order": "ord-7744"}},
        },
        # The day's list: who is booked in with whom, and who could cover.
        "schedule": {
            "doctors": {"clin-okafor": {"name": "Dr Ada Okafor", "available": True},
                        "clin-bauer": {"name": "Dr Jonas Bauer", "available": True},
                        "clin-ndiaye": {"name": "Dr Awa Ndiaye", "available": True}},
            "appointments": _day_appts,
            "free_slots": _day_free,
            "off_today": [],
        },
        "pharmacy": {"received": [], "dispensed": []},   # the pharmacy never got ord-7743
        "outreach": {"messages": [{"patient": "pat-rivera", "kind": "text message", "value": "mobile ending 0455",
                                   "delivered": True, "responded": True}]},
        "apps": {"billing-app": {"config": {"PAYMENTS_KEY": OLD}},
                 "reports-app": {"config": {"REPORTS_KEY": REPORTS}},
                 "storefront": {"config": {"CHECKOUT_URL": "https://checkout-api.internal"}}},
        "failures": {}, "flags": {}, "applied": {}, "calls": 0, "mutations": 0,
    }


# The first write each playbook makes, so "one step fails" means the same thing everywhere.
FLAKY_POINTS = ("schedule.move", "booking.book", "records.resend", "pharmacy.send",
                "app.update_config", "cloud.rollback", "vault.issue")


def _setup_flags(setup):
    """Turn a caller's description of a situation into the flags the seed already understands."""
    out = {}
    if setup.get("cover_slots") is not None:
        out["slots_short"] = max(0, int(setup["cover_slots"]))
    if setup.get("people_we_cannot_reach"):
        out["unreachable_count"] = max(0, int(setup["people_we_cannot_reach"]))
    if setup.get("one_result_is_urgent"):
        out["referral_critical"] = True
    return out


# Whose names appear in the output. A caller who tells Rook what their organisation is called,
# who is away and who can cover gets a plan, checks and an evidence pack in their own words,
# because every sentence downstream is built from these fields rather than from a fixed script.
AWAY = (("records", "clinicians", "clin-okafor"), ("schedule", "doctors", "clin-okafor"))
COVER = (("schedule", "doctors", "clin-bauer"), ("schedule", "doctors", "clin-ndiaye"))


def _apply_setup_identity(s, setup):
    """Put the caller's own organisation, people and words into the state Rook then reads."""
    name, about = setup.get("organisation"), setup.get("we_do")
    if name:
        s["records"]["clinic"] = name
        # What the care playbooks are scoped to, so a refusal says "belongs to <their name>".
        s["records"]["scope"] = name
    profile = {"name": name, "about": about,
               "who_reports": setup.get("who_reports"), "who_approves": setup.get("who_approves")}
    profile = {k: v for k, v in profile.items() if v}
    if profile:
        s["profile"] = profile
    away = setup.get("person_away")
    if away:
        for a, b, c in AWAY:
            s[a][b][c]["name"] = away
        was = s["directory"]["ident-jdoe"]["name"]       # the person who left, for offboarding
        s["directory"]["ident-jdoe"]["name"] = away
        for t in s["pm"]["tickets"].values():
            t["title"] = t["title"].replace(was, away)
    for (a, b, c), who in zip(COVER, setup.get("colleagues") or []):
        s[a][b][c]["name"] = who
    return s


def _apply_seed_flags(s):
    """Flags that describe the world Rook walks into, rather than a fault injected while it works."""
    if s["flags"].get("leak_already_revoked"):
        for v in s["vault"]["credentials"]["cred-reports"]["versions"]:
            v["status"] = "revoked"
    off = s["flags"].get("doctor_off")
    if off:
        s["schedule"]["off_today"] = [off]
        s["schedule"]["doctors"][off]["available"] = False
    if s["flags"].get("slots_short") is not None:
        keep = s["flags"]["slots_short"]
        pool = [(d, t) for d, ts in s["schedule"]["free_slots"].items() for t in ts][:keep]
        s["schedule"]["free_slots"] = {d: [] for d in s["schedule"]["free_slots"]}
        for d, t in pool:
            s["schedule"]["free_slots"][d].append(t)
    n_unreachable = s["flags"].get("unreachable_count")
    if n_unreachable:
        # Take them off the front of today's list, so the gap is visible early in the day.
        for pid in sorted(p for p in s["records"]["patients"] if p.startswith("pat-") and p[4:].isdigit())[:n_unreachable]:
            for c in s["records"]["patients"][pid]["channels"]:
                c["status"] = "stale"
    if s["flags"].get("patient_unreachable"):
        for c in s["records"]["patients"][s["flags"]["patient_unreachable"]]["channels"]:
            c["status"] = "stale"
    if s["flags"].get("care_all_done"):
        # The honest opposite of the usual case: every handoff really did complete.
        s["booking"]["inboxes"]["cardiology"]["received"].append("ord-7741")
        s["booking"]["appointments"]["appt-1"] = {"patient": "pat-alvarez", "specialty": "cardiology",
                                                  "at": "2026-10-20T11:00:00Z", "status": "booked",
                                                  "order": "ord-7741"}
        s["pharmacy"]["received"].append("ord-7743")
        s["records"]["notifications"].append({"order": "ord-7742", "clinician": "clin-okafor",
                                              "urgency": "routine", "reason": "Lipid panel"})
        for pid in ("pat-alvarez", "pat-osei"):
            s["outreach"]["messages"].append({"patient": pid, "kind": "text message", "value": "on file",
                                              "delivered": True, "responded": True})
        for oid in ("ord-7741", "ord-7742", "ord-7743"):
            s["records"]["orders"][oid]["loop_closed"] = True
    if s["flags"].get("referral_critical"):
        o = s["records"]["orders"]["ord-7742"]
        o["urgency"] = "critical"
        s["records"]["results"]["ord-7742"] = {
            "kind": "Potassium", "finding": "Serum potassium 6.9 mmol/L",
            "flag": "critical", "reported_at": "2026-09-30T07:45:00Z"}
    if s["flags"].get("referral_unreachable"):
        for c in s["records"]["patients"]["pat-alvarez"]["channels"]:
            c["status"] = "stale"
    if s["flags"].get("leak_unattributed"):
        # A key in the repo that belongs to no credential in the vault: Rook cannot attribute it.
        s["github"]["repos"]["analytics-jobs"]["config/settings.yml"] = (
            "warehouse_key: sk_test_SYNTH_unknown_v1\nschedule: nightly")


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
                for token in txt.replace("=", " ").replace(":", " ").split():
                    if token.startswith("sk_test_SYNTH") and fp(token) == f:
                        out.append(f"{repo}/{path}")
        return out

    def secrets_in(self, path):
        """Fingerprints of credentials hardcoded in one tracked file. Values never leave this method."""
        repo, _, file = path.partition("/")
        txt = self.s["github"]["repos"].get(repo, {}).get(file)
        if txt is None:
            return []
        return [fp(t) for t in txt.replace("=", " ").replace(":", " ").split() if t.startswith("sk_test_SYNTH")]

    def scrub_secret(self, path, f, idem):
        """Replace the leaked value in a tracked file with a placeholder (history still holds it)."""
        def fn():
            repo, file = path.split("/", 1)
            txt = self.s["github"]["repos"][repo][file]
            for token in txt.replace("=", " ").replace(":", " ").split():
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

    def open_leak_alerts(self):
        return {tid: t for tid, t in self.tickets().items() if t.get("kind") == "leak" and t["status"] == "open"}

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


class Records(Adapter):
    """Adapter 6: the clinic's record system. It knows what was ordered and what it believes happened."""
    def clinic(self):
        return self.s["records"]["clinic"]

    def scope(self):
        """What a care incident is about: the organisation, under the name its own staff use."""
        return self.s["records"].get("scope") or f"clinic:{self.clinic()}"

    def orders(self):
        return self.s["records"]["orders"]

    def order(self, oid):
        return self.orders().get(oid)

    def patient(self, pid):
        return self.s["records"]["patients"].get(pid)

    def clinician(self, cid):
        return self.s["records"]["clinicians"].get(cid)

    def result(self, oid):
        return self.s["records"]["results"].get(oid)

    def acknowledged(self, oid):
        return self.s["records"]["acknowledgements"].get(oid)

    def loop_closed(self, oid):
        o = self.order(oid)
        return bool(o and o.get("loop_closed"))

    def notified(self, oid):
        return [n for n in self.s["records"]["notifications"] if n["order"] == oid]

    def resend_referral(self, oid, channel, idem):
        """Send the referral again, this time on a channel the receiving clinic still reads."""
        def fn():
            o = self.orders()[oid]
            o["sent_via"] = channel
            o["record_status"] = "sent"
            inbox = self.s["booking"]["inboxes"][o["specialty"]]
            if inbox["channels"].get(channel) == "active" and oid not in inbox["received"]:
                inbox["received"].append(oid)       # a dead channel accepts the send and drops it
            return {"order": oid, "channel": channel, "delivered": oid in inbox["received"]}
        return self.core.mutate("records.resend", idem, fn)

    def notify_clinician(self, oid, cid, idem):
        def fn():
            o = self.orders()[oid]
            self.s["records"]["notifications"].append(
                {"order": oid, "clinician": cid, "urgency": o.get("urgency", "routine"),
                 "reason": o.get("reason", "")})
            return {"order": oid, "clinician": cid, "paged": True}
        return self.core.mutate("records.notify", idem, fn)

    def close_loop(self, oid, idem):
        def fn():
            self.orders()[oid]["loop_closed"] = True
            return {"order": oid, "loop_closed": True}
        return self.core.mutate("records.close_loop", idem, fn)


class Booking(Adapter):
    """Adapter 7: the specialist clinic's scheduling system, which the referring clinic cannot see."""
    def inbox(self, specialty):
        return self.s["booking"]["inboxes"].get(specialty, {"channels": {}, "received": []})

    def received(self, oid, specialty):
        return oid in self.inbox(specialty)["received"]

    def working_channel(self, specialty):
        return next((c for c, st in self.inbox(specialty)["channels"].items() if st == "active"), None)

    def appointment_for(self, patient, specialty):
        return next((a for a in self.s["booking"]["appointments"].values()
                     if a["patient"] == patient and a["specialty"] == specialty
                     and a["status"] == "booked"), None)

    def book(self, oid, patient, specialty, idem):
        def fn():
            if not self.received(oid, specialty):
                raise Permanent("the specialist clinic has no referral for this patient")
            slots = self.s["booking"]["slots"].get(specialty, [])
            if not slots:
                raise Permanent("no appointment slots available")
            at = slots.pop(0)
            aid = f"appt-{len(self.s['booking']['appointments']) + 1}"
            self.s["booking"]["appointments"][aid] = {
                "patient": patient, "specialty": specialty, "at": at, "status": "booked", "order": oid}
            return {"appointment": aid, "at": at, "specialty": specialty}
        return self.core.mutate("booking.book", idem, fn)


class Schedule(Adapter):
    """Adapter 9: the clinic's own appointment book."""
    def doctors(self):
        return self.s["schedule"]["doctors"]

    def doctor_name(self, did):
        return self.doctors().get(did, {}).get("name", did)

    def off_today(self):
        return list(self.s["schedule"]["off_today"])

    def appointments(self):
        return self.s["schedule"]["appointments"]

    def appointment(self, aid):
        return self.appointments().get(aid)

    def booked_with(self, did):
        return {aid: a for aid, a in self.appointments().items()
                if a["doctor"] == did and a["status"] == "booked"}

    def free_slots(self, did=None):
        f = self.s["schedule"]["free_slots"]
        return f.get(did, []) if did else f

    def cover_options(self, did):
        """Which other doctors are in today and have room."""
        return {d: list(sl) for d, sl in self.free_slots().items()
                if d != did and self.doctors().get(d, {}).get("available") and sl}

    def double_booked(self):
        seen, clashes = {}, []
        for aid, a in self.appointments().items():
            if a["status"] != "booked":
                continue
            key = (a["doctor"], a["at"])
            if key in seen:
                clashes.append({"doctor": a["doctor"], "at": a["at"], "appointments": [seen[key], aid]})
            seen[key] = aid
        return clashes

    def move(self, aid, to_doctor, to_time, idem):
        def fn():
            a = self.appointments()[aid]
            slots = self.s["schedule"]["free_slots"].get(to_doctor, [])
            if to_time not in slots:
                raise Permanent("that slot is no longer free")
            slots.remove(to_time)
            self.s["schedule"]["free_slots"].setdefault(a["doctor"], []).append(a["at"])
            a["doctor"], a["at"] = to_doctor, to_time
            return {"appointment": aid, "doctor": to_doctor, "at": to_time}
        return self.core.mutate("schedule.move", idem, fn)


class Pharmacy(Adapter):
    """Adapter 8: the pharmacy. "Sent to pharmacy" in the record is not the same as the pharmacy having it."""
    def has(self, oid):
        return oid in self.s["pharmacy"]["received"]

    def dispensed(self, oid):
        return oid in self.s["pharmacy"]["dispensed"]

    def send(self, oid, idem):
        def fn():
            if oid not in self.s["pharmacy"]["received"]:
                self.s["pharmacy"]["received"].append(oid)
            return {"order": oid, "at_pharmacy": True}
        return self.core.mutate("pharmacy.send", idem, fn)


class Outreach(Adapter):
    """Adapter 8: patient messaging. A message that leaves the building is not a message that arrived."""
    def channels(self, pid):
        p = self.s["records"]["patients"][pid]
        return [c for c in p["channels"] if c["kind"] not in p.get("opted_out", [])]

    def best_channel(self, pid):
        return next((c for c in self.channels(pid) if c["status"] == "active"), None)

    def messages(self, pid):
        return [m for m in self.s["outreach"]["messages"] if m["patient"] == pid]

    def reached(self, pid):
        """Reached means the patient answered, not that a message was sent."""
        return any(m["responded"] for m in self.messages(pid))

    def contact(self, pid, kind, value, idem):
        def fn():
            ch = next((c for c in self.channels(pid) if c["kind"] == kind), None)
            if ch is None:
                raise Permanent(f"the patient has no usable {kind} channel on file")
            live = ch["status"] == "active"
            self.s["outreach"]["messages"].append(
                {"patient": pid, "kind": kind, "value": value, "delivered": live, "responded": live})
            return {"patient": pid, "channel": kind, "delivered": live, "responded": live}
        return self.core.mutate("outreach.contact", idem, fn)


class Sandbox:
    def __init__(self, store, failures=None, flags=None, scenario=None, setup=None):
        self.store = store
        s = store.load_sandbox()
        if s is None or scenario is not None or setup:
            s = self._seeded(failures, flags, scenario, setup)
            store.save_sandbox(s)
        self.s = s
        self.github = SourceHost(self, "github")
        self.cloud = Cloud(self, "cloud")
        self.pm = ProjectTracker(self)
        self.pm_accounts = AccountService(self, "pm")
        self.vault = Vault(self)
        self.apps = InternalApp(self)
        self.records = Records(self)
        self.booking = Booking(self)
        self.outreach = Outreach(self)
        self.pharmacy = Pharmacy(self)
        self.schedule = Schedule(self)

    @staticmethod
    def _seeded(failures=None, flags=None, scenario=None, setup=None):
        setup = dict(setup or {})
        s = seed(patients=setup.get("people_booked_in"))
        if scenario is not None:
            _, f, fl = SCENARIOS[scenario]
            s["failures"], s["flags"] = copy.deepcopy(f), copy.deepcopy(fl)
            s["scenario"] = scenario
        if failures is not None:
            s["failures"] = failures
        if flags is not None:
            s["flags"] = flags
        if setup:
            s["setup"] = setup
            s["flags"] = dict(s["flags"], **_setup_flags(setup))
            if setup.get("one_step_fails"):
                # One transient failure on whichever write this playbook makes first.
                s["failures"] = dict(s["failures"], **{k: ["transient"] for k in FLAKY_POINTS})
        _apply_seed_flags(s)
        _apply_setup_identity(s, setup)
        return s

    def profile(self):
        """How this organisation described itself, or {} if nobody said."""
        return dict(self.s.get("profile") or {})

    def account_service(self, name):
        return {"github": self.github, "cloud": self.cloud, "pm": self.pm_accounts}[name]

    def reset(self, failures=None, flags=None, scenario=None, setup=None):
        self.s = self._seeded(failures, flags, scenario, setup)
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

    # ---- is this handoff actually finished? asked of the systems that would know ----
    def handoff_gaps(self, oid):
        """What is still missing before this handoff can honestly be called done.

        One place decides this, so the plan, the policy rule that guards the record's "closed"
        flag, and the closure checks can never drift apart.
        """
        o = self.records.order(oid)
        if o is None:
            return ["the order does not exist"]
        g = []
        if o["kind"] == "referral":
            if not self.booking.received(oid, o["specialty"]):
                g.append(f"the {SPECIALTY[o['specialty']]} never got the referral")
            if self.booking.appointment_for(o["patient"], o["specialty"]) is None:
                g.append("no appointment has been booked")
            if not self.outreach.reached(o["patient"]):
                g.append("the patient has not been told")
        elif o["kind"] == "result":
            if not self.records.notified(oid):
                g.append("the doctor who ordered it has not seen the result")
            if o.get("urgency") == "critical" and not self.records.acknowledged(oid):
                g.append("an urgent result has not been seen and signed off by a doctor")
        elif o["kind"] == "prescription":
            if not self.pharmacy.has(oid):
                g.append("the pharmacy never got the prescription")
            if not self.outreach.reached(o["patient"]):
                g.append("the patient has not been told")
        return g

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
