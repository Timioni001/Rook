"""Tracing. Always safe to call.

Every span is recorded locally (optional JSONL) and, when neatlogs is initialised, exported as a
neatlogs/OpenTelemetry span. Attributes are redacted before they leave the process: synthetic
secret values are replaced by fingerprints and attribute keys that look sensitive are dropped.
"""
import contextlib, json, os, pathlib, re, subprocess, time
from .store import SECRET, redact
from .domain import fp

_hooks = []
_neatlogs = None          # the neatlogs module once init_neatlogs() succeeded
_version = "dev"

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


def version():
    """Code version stamped on every root trace, so before/after runs can be compared in neatlogs."""
    if os.getenv("ROOK_VERSION"):
        return os.environ["ROOK_VERSION"]
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              timeout=2, cwd=os.path.dirname(__file__)).stdout.strip() or "dev"
    except Exception:
        return "dev"


def mask_span(span):
    """Last line of defence before export: replace any synthetic key value with its fingerprint."""
    def clean(v):
        if isinstance(v, str):
            return SECRET.sub(lambda m: fp(m.group()), v)
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items()}
        if isinstance(v, list):
            return [clean(x) for x in v]
        return v
    return clean(span)


def init_neatlogs(workflow_name="rook-incident-response", tracer_provider=None, **kw):
    """Initialise neatlogs if an API key is configured (or a tracer provider is supplied for tests).

    Returns True when spans will be recorded through neatlogs.
    """
    global _neatlogs, _version
    key = os.getenv("NEATLOGS_API_KEY")
    if not key and tracer_provider is None:
        return False
    import neatlogs
    _version = version()
    args = dict(api_key=key or "local-test", workflow_name=workflow_name,
                tags=["rook", "sandbox", f"version:{_version}"], user_id="svc-rook",
                mask=mask_span, capture_logs=True, pii_enabled=True)
    if os.getenv("ROOK_PLANNER") == "llm":
        args["instrumentations"] = ["anthropic"]      # model planner calls become LLM spans
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


def log(template, level="info", **data):
    """A timestamped step inside the current span (neatlogs LOG span). Values are redacted."""
    if _neatlogs is None:
        return
    try:
        _neatlogs.log(template, level=level, **json.loads(redact(data)))
    except Exception:
        pass


class _Span:
    """Handle yielded by span(); lets callers attach results discovered inside the span."""
    def __init__(self, otel):
        self.otel, self.attrs = otel, {}
        self.sent = set()               # which of input.value / output.value were written
        self.failure = None             # a failure the caller handled, recorded anyway

    def set(self, **attrs):
        self.attrs.update(attrs)
        if self.otel is not None:
            for k, v in safe_attrs(attrs).items():
                self.otel.set_attribute(k, v)

    def _raw(self, **attrs):
        if self.otel is not None:
            for k, v in json.loads(redact(attrs)).items():
                self.otel.set_attribute(k, v if isinstance(v, (str, int, float, bool)) else json.dumps(v))

    # neatlogs custom attributes, so the dashboard renders each kind natively
    def guardrail(self, input, passed, output):
        # the SDK resolves a guardrail span's input/output from these, so a generic input.value or
        # output.value written afterwards would overwrite them: count them as already sent.
        self.sent.update(("input.value", "output.value"))
        self._raw(**{"neatlogs.guardrail.input": input, "neatlogs.guardrail.passed": bool(passed),
                     "neatlogs.guardrail.output": output})

    def tool(self, name, description, parameters):
        self.sent.add("input.value")
        self._raw(**{"neatlogs.tool.name": name, "neatlogs.tool.description": description,
                     "neatlogs.tool.parameters": json.dumps(parameters)})

    def io(self, input=None, output=None):
        """The flat input.value / output.value pair the neatlogs UI shows as the opening message
        and the last reply. Without them a session renders as empty and reads as incomplete."""
        kw = {}
        if input is not None:
            kw["input.value"] = input
        if output is not None:
            kw["output.value"] = output
        if kw:
            self.sent.update(kw)
            self._raw(**kw)

    def failed(self, kind, message, retrying=None):
        """A failure the caller is handling itself.

        Without this the span closes OK and exports an empty output, so a timeout on a tool looks
        exactly like a tool that did nothing: the span is green, the trace has no error on it, and
        the only trace of the failure is in our own audit log. Record it on the span too.
        """
        self.failure = (kind, message)
        self.attrs.update(error=kind, error_message=str(message))
        if retrying is not None:
            self.attrs["retrying"] = bool(retrying)
        if self.otel is None:
            return
        from opentelemetry.trace import Status, StatusCode
        self._raw(**{"rook.error": kind, "rook.error.kind": kind, "rook.error.message": str(message)})
        if retrying is not None:
            self._raw(**{"rook.retrying": bool(retrying)})
        self.otel.set_status(Status(StatusCode.ERROR, f"{kind}: {message}"))
        self.io(output=f"{kind}: {message}"
                       + ("" if retrying is None else
                          " (will retry after re-reading live state)" if retrying else " (not retried)"))

    def retriever(self, query, documents):
        self.sent.add("input.value")
        self._raw(**{"neatlogs.retriever.query": query, "neatlogs.retriever.top_k": len(documents),
                     **{f"neatlogs.retriever.documents.{i}": d for i, d in enumerate(documents)}})


def _pairs(d):
    return ", ".join(f"{k}={v}" for k, v in d.items() if v not in (None, "", [], {}))


def _fill_io(h, name, attrs, err):
    """No span leaves here with an empty input or output.

    A span with neither reads, in the neatlogs session view, as a step that produced nothing, which
    is how a degraded tool call hid in plain sight: the trace was there, the content was not.
    """
    if h.otel is None:
        return
    if "input.value" not in h.sent:
        h.io(input=f"{name}({_pairs(attrs)})" if attrs else name)
    if "output.value" not in h.sent:
        done = {k: v for k, v in h.attrs.items() if k not in attrs}
        h.io(output=(f"raised {err}" if err else _pairs(done) or f"{name}: nothing to report"))


@contextlib.contextmanager
def span(name, session=None, user=None, user_meta=None, **attrs):
    """Trace a step. `session` groups every trace of one incident into a neatlogs session;
    `user` records the human principal that caused it (never a secret)."""
    t0 = time.time()
    err = None
    if _neatlogs is not None:
        kw = {"version": _version}
        if session:
            kw["session_id"] = session
        if user:
            kw["end_user_id"] = user
            if user_meta:
                kw["end_user_metadata"] = user_meta
        cm = _neatlogs.trace(name, kind=kind_for(name), **kw)
    else:
        cm = contextlib.nullcontext()
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
            _fill_io(h, name, attrs, err)
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
