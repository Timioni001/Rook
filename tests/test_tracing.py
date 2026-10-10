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
    assert obs.init_neatlogs(tracer_provider=tp, capture_logs=False)   # log export would try the network
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


def test_neatlogs_features_sessions_guardrails_tools(spans):
    rep = run("signature")
    iid = rep["incident"]["id"]
    got = spans.get_finished_spans()
    roots = [s for s in got if s.name in ("incident.start", "incident.run")]
    assert roots and all(s.attributes["neatlogs.session.id"] == iid for s in roots)
    appr = next(s for s in got if s.name == "approval.decide")
    assert appr.attributes["neatlogs.guardrail.passed"] is True
    blocked_or_open = next(s for s in got if s.name == "closure.evaluate"
                           and s.attributes["neatlogs.guardrail.passed"] is False)
    assert "needs_approval" in blocked_or_open.attributes["neatlogs.guardrail.output"]
    tool = next(s for s in got if s.name == "execute")
    assert tool.attributes["neatlogs.tool.name"].endswith(".disable_account")
    assert "idempotency_key" in tool.attributes["neatlogs.tool.parameters"]
    ret = next(s for s in got if s.name == "discover.dependencies")
    assert ret.attributes["neatlogs.retriever.documents.1"] == "cloud:payments-worker"
    assert all("version:" in s.attributes.get("neatlogs.tags", "version:") for s in got)


def test_export_mask_replaces_secret_values():
    span = {"attributes": {"x": "key sk_test_SYNTH_payments_v1", "n": [{"y": "sk_test_SYNTH_a"}]}}
    out = json.dumps(obs.mask_span(span))
    assert "sk_test_SYNTH" not in out and "fp:" in out
