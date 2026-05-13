from content_gen.llm.observed_client import ObservedLLMClient
from content_gen.observability import (
    CompatibilityEvent,
    FallbackTraceEvent,
    LLMTraceRecorder,
    NodeTraceEvent,
    record_runtime_fallback_traces,
    stable_input_hash,
)


def test_stable_input_hash_is_order_independent_for_json_payloads() -> None:
    assert stable_input_hash({"b": 2, "a": 1}) == stable_input_hash({"a": 1, "b": 2})


def test_node_trace_event_captures_required_generation_fields() -> None:
    event = NodeTraceEvent.from_node_execution(
        node="theory",
        inputs={"seed": {"title": "Проект"}},
        latency_ms=42.5,
        status="success",
        issues=["minor warning"],
        prompt_version="flow-v1",
        model="gpt-test",
        repair_attempts=1,
        output_schema="markdown,theory_parts",
    )

    payload = event.model_dump(mode="json")

    assert payload["node"] == "theory"
    assert payload["input_hash"]
    assert payload["prompt_version"] == "flow-v1"
    assert payload["model"] == "gpt-test"
    assert payload["latency_ms"] == 42.5
    assert payload["validation"]["status"] == "warning"
    assert payload["validation"]["issues_count"] == 1
    assert payload["repair_attempts"] == 1
    assert payload["output_schema"] == "markdown,theory_parts"


def test_observed_llm_client_records_complete_calls() -> None:
    class FakeLLM:
        model = "test-model"
        _last_finish_reason = "stop"
        _last_token_usage = {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}

        def complete(self, **_kwargs):
            return "ok"

    recorder = LLMTraceRecorder()
    client = ObservedLLMClient(FakeLLM(), recorder, node="generation", agent="root").scoped(
        node="theory",
        agent="TheoryAgent",
        prompt_version="theory-v1",
    )

    assert client.complete(system="s", user="u", response_format="json_object") == "ok"

    event = recorder.events[0]
    assert event["node"] == "theory"
    assert event["agent"] == "TheoryAgent"
    assert event["prompt_version"] == "theory-v1"
    assert event["model"] == "test-model"
    assert event["schema"] == "json_object"
    assert event["tokens"]["total_tokens"] == 5
    assert event["status"] == "success"
    assert event["input_hash"]


def test_fallback_trace_event_captures_degradation_contract() -> None:
    event = FallbackTraceEvent.from_fallback(
        node="task_planning",
        fallback_type="default_task_plan",
        reason="planner failed",
        quality_risk="medium",
        inputs={"title": "Проект"},
        trace={"resolved_tasks_count": 2},
    )

    payload = event.model_dump(mode="json")
    assert payload["node"] == "task_planning"
    assert payload["fallback_type"] == "default_task_plan"
    assert payload["reason"] == "planner failed"
    assert payload["quality_risk"] == "medium"
    assert payload["trace"] == {"resolved_tasks_count": 2}
    assert payload["input_hash"]


def test_compatibility_event_captures_legacy_contract() -> None:
    event = CompatibilityEvent(
        source="paused_generation_codec",
        compatibility_type="unknown_paused_type",
        reason="unsupported stored type",
        risk="medium",
        metadata={"type_name": "old.module:Thing"},
    )

    payload = event.model_dump(mode="json")
    assert payload["source"] == "paused_generation_codec"
    assert payload["compatibility_type"] == "unknown_paused_type"
    assert payload["metadata"] == {"type_name": "old.module:Thing"}


def test_record_runtime_fallback_traces_normalizes_events() -> None:
    class Runtime:
        pass

    runtime = Runtime()
    event = FallbackTraceEvent.from_fallback(
        node="quality",
        fallback_type="style_guard_markdown_boundary",
        reason="typed style guard unavailable",
        quality_risk="low",
    )

    record_runtime_fallback_traces(runtime, [event, {"node": "practice", "fallback_type": "critic"}])

    assert runtime.fallback_traces[0]["node"] == "quality"
    assert runtime.fallback_traces[0]["fallback_type"] == "style_guard_markdown_boundary"
    assert runtime.fallback_traces[1] == {"node": "practice", "fallback_type": "critic"}
