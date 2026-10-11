import hashlib, time
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


def fp(v: str) -> str:
    return "fp:" + hashlib.sha256(v.encode()).hexdigest()[:8]


class Status(str, Enum):
    planned = "planned"
    needs_approval = "needs_approval"
    blocked = "blocked"
    authorized = "authorized"
    executing = "executing"
    executed = "executed"
    verified = "verified"
    retry_pending = "retry_pending"
    failed = "failed"
    unknown = "unknown"


S = Status
TRANSITIONS = {
    S.planned: {S.authorized, S.blocked, S.needs_approval},
    S.needs_approval: {S.authorized, S.blocked},
    S.authorized: {S.executing, S.blocked},          # blocked: pre-execution policy re-check failed
    S.executing: {S.executed, S.retry_pending, S.failed, S.unknown, S.verified},
    S.executed: {S.verified, S.failed, S.unknown},
    S.retry_pending: {S.executing, S.failed, S.blocked},
    S.unknown: {S.verified, S.retry_pending, S.failed},
    S.verified: set(),
    S.failed: set(),
    S.blocked: set(),
}


class InvalidTransition(Exception):
    ...


class IncidentStatus(str, Enum):
    investigating = "investigating"
    ready = "ready"
    awaiting_approval = "awaiting_approval"
    remediating = "remediating"
    escalated = "escalated"
    closed_verified = "closed_verified"
    open = "open"


class Incident(BaseModel):
    id: str
    org: str
    created_by: str
    subject: str
    title: str = ""
    severity: str = "high"
    scenario: str = "signature"
    playbook: str = "offboarding"      # which kind of incident: see rook/playbooks.py
    status: str = IncidentStatus.investigating.value
    created_at: float = Field(default_factory=time.time)
    closed_at: Optional[float] = None
    relationships: list[dict] = []     # fingerprints only, never secret values
    graph: dict = {}                   # {nodes: [...], edges: [...]}
    findings: list[dict] = []          # plain-language, evidence-backed
    exposure: str = ""
    ticket: Optional[str] = None
    reported: str = ""                 # what the person who raised it typed, in their own words
    organisation: dict = {}            # {name, about}: how the company described itself at setup


class Action(BaseModel):
    id: str
    incident_id: str
    type: str                 # one of policy.ALLOWED, e.g. revoke_credential or rollback_service
    target: str
    params: dict = {}
    depends_on: list[str] = []
    summary: str = ""         # what this does, in plain language
    risk: str = "low"         # low | medium (production change, reversible) | high (irreversible)
    status: Status = Status.planned
    retries: int = 0
    max_retries: int = 3
    idem_key: str
    policy: dict = {}
    result: dict = {}
    evidence: dict = {}

    def move(self, new: Status):
        if new == self.status:
            return
        if new not in TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.id}: {self.status.value} -> {new.value}")
        self.status = new


class Condition(BaseModel):
    """A closure condition, defined BEFORE remediation begins."""
    id: str
    description: str
    expected: str
    method: str               # name of an independent observer
    args: dict = {}
    mandatory: bool = True
    result: Optional[bool] = None     # None = not evaluated / inconclusive
    evidence: dict = {}
    evaluated_at: Optional[float] = None


class Principal(BaseModel):
    """An authenticated caller. Always derived server-side from the credential presented."""
    id: str
    org: str
    roles: list[str] = []
    name: str = ""

    def can(self, role: str) -> bool:
        return role in self.roles
