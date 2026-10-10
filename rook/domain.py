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
    S.authorized: {S.executing},
    S.executing: {S.executed, S.retry_pending, S.failed, S.unknown, S.verified},
    S.executed: {S.verified, S.failed, S.unknown},
    S.retry_pending: {S.executing, S.failed},
    S.unknown: {S.verified, S.retry_pending, S.failed},
    S.verified: set(),
    S.failed: set(),
    S.blocked: set(),
}


class InvalidTransition(Exception):
    ...


class Incident(BaseModel):
    id: str
    subject: str
    status: str = "open"
    created_at: float = Field(default_factory=time.time)
    relationships: list[dict] = []     # fingerprints only, never secret values
    exposure: str = ""


class Action(BaseModel):
    id: str
    incident_id: str
    type: str                 # disable_account | rotate_credential | repair_config
    target: str
    params: dict = {}
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
