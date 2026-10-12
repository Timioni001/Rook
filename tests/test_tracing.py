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


def test_every_exported_span_says_what_went_in_and_what_came_back(spans):
    """The failure this guards against: a span that exports no input and no output.

    In the neatlogs session view such a span renders as a step that produced nothing, which is
    exactly how a degraded tool call hid — the trace was there, the content was not.
    """
    run("signature")
    thin = []
    for s in spans.get_finished_spans():
        a = s.attributes
        got_in = a.get("input.value") or a.get("neatlogs.guardrail.input") or a.get("neatlogs.retriever.query")
        got_out = a.get("output.value") or a.get("neatlogs.guardrail.output")
        if not (got_in and str(got_in).strip()) or not (got_out and str(got_out).strip()):
            thin.append(s.name)
    assert thin == []


def test_a_failure_the_engine_handles_still_marks_the_span(spans):
    """A handled timeout used to close the span green: status ok, no error, empty output."""
    with obs.span("execute.open_ticket", incident="inc-x") as sp:
        sp.failed("ticket_timeout", "pm.open_ticket", retrying=False)
    s = [x for x in spans.get_finished_spans() if x.name == "execute.open_ticket"][0]
    assert not s.status.is_ok
    assert s.attributes["rook.error.kind"] == "ticket_timeout"
    assert s.attributes["rook.retrying"] is False
    assert "pm.open_ticket" in s.attributes["output.value"]


def test_a_transient_on_a_best_effort_write_is_visible_in_the_trace(spans):
    """Opening the tracking ticket is best effort. Best effort is not the same as invisible."""
    st = Store(":memory:")
    sb = Sandbox(st, scenario="signature")
    sb.s["failures"] = dict(sb.s["failures"], **{"pm.open_ticket": ["transient"]})
    Engine(st, sb, sleep=lambda s: None).start()
    s = [x for x in spans.get_finished_spans() if x.name == "execute.open_ticket"][0]
    assert not s.status.is_ok and s.attributes["rook.error.kind"] == "ticket_transient"
    assert "503" in s.attributes["output.value"]


def test_a_tool_span_carries_the_call_and_its_result(spans):
    run("signature")
    tools = [s for s in spans.get_finished_spans() if s.name == "execute"]
    first = tools[0]
    assert "attempt 1" in first.attributes["input.value"]
    assert "idempotency key" in first.attributes["input.value"]
    assert first.attributes["output.value"].startswith("{")
