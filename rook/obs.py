"""Local tracing. Always safe to call. Exporters (e.g. neatlogs) attach via register_hook()."""
import contextlib, json, os, pathlib, time
from .store import redact

_hooks = []


def register_hook(fn):
    """fn(record: dict) is called for every finished span. Records are already redacted."""
    _hooks.append(fn)


@contextlib.contextmanager
def span(name, **attrs):
    t0 = time.time()
    err = None
    try:
        yield
    except BaseException as e:
        err = type(e).__name__
        raise
    finally:
        rec = {"name": name, "ts": t0, "duration_ms": round((time.time() - t0) * 1000, 2),
               "attrs": attrs, "error": err}
        line = redact(rec)
        if os.getenv("ROOK_TRACE"):
            d = pathlib.Path(os.getenv("ROOK_TRACE_DIR", "traces"))
            d.mkdir(parents=True, exist_ok=True)
            with open(d / "rook-trace.jsonl", "a") as f:
                f.write(line + "\n")
        for h in _hooks:
            try:
                h(json.loads(line))
            except Exception:
                pass            # observability must never break remediation
