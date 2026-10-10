import json
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from rook import obs
from rook.domain import Principal
from rook.engine import Engine
from rook.sandbox import Sandbox
from rook.store import Store


@pytest.fixture
def spans():
    exp = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exp))
    assert obs.init_neatlogs(tracer_provider=tp)
    yield exp
    obs.shutdown()


def run(scenario):
    st = Store(":memory:")
    sb = Sandbox(st, scenario=scenario)
    e = Engine(st, sb, sleep=lambda s: None)
    inc = e.start()
    e.run(inc.id)
    rev = next(a for a in st.actions(inc.id) if a.type == "revoke_credential")
    e.approve(inc.id, rev.id, Principal(id="u-approver", org="acme", roles=["approver"]))
    return e.run(inc.id)


def test_workflow_spans_exported_through_neatlogs(spans):
    rep = run("signature")
    assert rep["status"] == "closed_verified"
    got = spans.get_finished_spans()
    names = {s.name for s in got}
    assert {"incident.start", "investigate", "discover.dependencies", "incident.run", "plan",
            "policy.decide", "policy.recheck", "approval.decide", "execute", "reconcile", "verify",
            "closure.evaluate"} <= names
    kinds = {s.name: s.attributes.get("openinference.span.kind") for s in got if s.name in names}
    assert kinds["incident.run"] == "WORKFLOW" and kinds["execute"] == "TOOL"
    assert kinds["policy.decide"] == "GUARDRAIL"
    assert any(s.attributes.get("rook.incident") for s in got)


def test_secret_values_never_reach_trace_attributes(spans):
    run("clean")
    with obs.span("adapter.test", api_key="sk_test_SYNTH_leak", note="sk_test_SYNTH_leak2"):
        pass
    dump = json.dumps([dict(s.attributes) for s in spans.get_finished_spans()])
    assert "sk_test_SYNTH" not in dump
    assert "rook.api_key" not in dump and "rook.note" in dump


def test_span_records_errors(spans):
    with pytest.raises(ValueError):
        with obs.span("execute", action="x"):
            raise ValueError("boom")
    s = [x for x in spans.get_finished_spans() if x.name == "execute"][0]
    assert s.attributes["rook.error"] == "ValueError" and not s.status.is_ok
