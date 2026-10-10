"""Tracing. Always safe to call.

Every span is recorded locally (optional JSONL) and, when neatlogs is initialised, exported as a
neatlogs/OpenTelemetry span. Attributes are redacted before they leave the process: synthetic
secret values are replaced by fingerprints and attribute keys that look sensitive are dropped.
"""
import contextlib, json, os, pathlib, re, time
from .store import redact

_hooks = []
_neatlogs = None          # the neatlogs module once init_neatlogs() succeeded

# span name prefix -> neatlogs span kind
KINDS = [
    ("incident.run", "WORKFLOW"), ("incident.start", "WORKFLOW"), ("demo.", "WORKFLOW"),
    ("plan", "AGENT"), ("investigate", "AGENT"), ("discover", "RETRIEVER"),
    ("policy", "GUARDRAIL"), ("approval", "GUARDRAIL"), ("verify", "GUARDRAIL"),
    ("closure", "GUARDRAIL"), ("probe", "GUARDRAIL"),
    ("execute", "TOOL"), ("adapter", "TOOL"), ("reconcile", "CHAIN"), ("checkpoint", "CHAIN"),
]
SENSITIVE_KEY = re.compile(r"(secret|token|password|authorization|api[_-]?key|value)", re.I)


def kind_for(name):
    for prefix, kind in KINDS:
        if name.startswith(prefix):
            return kind
    return "CHAIN"


def safe_attrs(attrs):
    """Redacted, flat, non-sensitive attributes suitable for export."""
    out = {}
    for k, v in json.loads(redact(attrs)).items():
        if SENSITIVE_KEY.search(k):
            continue
        out[f"rook.{k}"] = v if isinstance(v, (str, int, float, bool)) else json.dumps(v)
    return out


def init_neatlogs(workflow_name="rook-incident-response", tracer_provider=None, **kw):
    """Initialise neatlogs if an API key is configured (or a tracer provider is supplied for tests).

    Returns True when spans will be recorded through neatlogs.
    """
    global _neatlogs
    key = os.getenv("NEATLOGS_API_KEY")
    if not key and tracer_provider is None:
        return False
    import neatlogs
    args = dict(api_key=key or "local-test", workflow_name=workflow_name,
                tags=["keywarden", "rook", "sandbox"], user_id="svc-rook")
    if os.getenv("NEATLOGS_ENDPOINT"):
        args["endpoint"] = os.environ["NEATLOGS_ENDPOINT"]
    if tracer_provider is not None:
        args.update(tracer_provider=tracer_provider, disable_export=True,
                    register_shutdown_handlers=False)
    args.update(kw)
    neatlogs.init(**args)
    _neatlogs = neatlogs
    return True


def flush():
    if _neatlogs is not None:
        _neatlogs.flush()


def shutdown():
    global _neatlogs
    if _neatlogs is not None:
        _neatlogs.flush()
        _neatlogs.shutdown()
        _neatlogs = None


def delivery():
    return _neatlogs.get_delivery_diagnostics() if _neatlogs is not None else {}


def register_hook(fn):
    """fn(record: dict) is called for every finished span. Records are already redacted."""
    _hooks.append(fn)


class _Span:
    """Handle yielded by span(); lets callers attach results discovered inside the span."""
    def __init__(self, otel):
        self.otel, self.attrs = otel, {}

    def set(self, **attrs):
        self.attrs.update(attrs)
        if self.otel is not None:
            for k, v in safe_attrs(attrs).items():
                self.otel.set_attribute(k, v)


@contextlib.contextmanager
def span(name, **attrs):
    t0 = time.time()
    err = None
    cm = _neatlogs.trace(name, kind=kind_for(name)) if _neatlogs is not None else contextlib.nullcontext()
    with cm as otel:
        h = _Span(otel)
        h.set(**attrs)
        try:
            yield h
        except BaseException as e:
            err = type(e).__name__
            if otel is not None:
                from opentelemetry.trace import Status, StatusCode
                otel.set_attribute("rook.error", err)
                otel.set_status(Status(StatusCode.ERROR, err))
            raise
        finally:
            rec = {"name": name, "ts": t0, "duration_ms": round((time.time() - t0) * 1000, 2),
                   "attrs": {**attrs, **h.attrs}, "error": err}
            line = redact(rec)
            if os.getenv("ROOK_TRACE"):
                d = pathlib.Path(os.getenv("ROOK_TRACE_DIR", "traces"))
                d.mkdir(parents=True, exist_ok=True)
                with open(d / "rook-trace.jsonl", "a") as f:
                    f.write(line + "\n")
            for fn in _hooks:
                try:
                    fn(json.loads(line))
                except Exception:
                    pass            # observability must never break remediation
