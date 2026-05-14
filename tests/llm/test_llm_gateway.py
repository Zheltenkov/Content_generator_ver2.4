import pytest
from pydantic import BaseModel

from content_gen.exceptions import LLMAPIError
from content_gen.llm.gateway import LLMGateway, LLMUsageBudgetTracker
from content_gen.llm.model_registry import ModelRegistry, ModelRoleConfig, ModelRoute


def _registry_with_openai_deepseek(*, budget_usd: float | None = None) -> ModelRegistry:
    return ModelRegistry(
        aliases={"enhancement_plan": "planner"},
        roles={
            "planner": ModelRoleConfig(
                budget_usd=budget_usd,
                fallback_chain=[
                    ModelRoute(
                        provider="openai",
                        model="gpt-test",
                        input_cost_per_1m=1000.0,
                        output_cost_per_1m=1000.0,
                    ),
                    ModelRoute(provider="deepseek", model="deepseek-chat"),
                ],
            )
        }
    )


def test_gateway_falls_back_to_next_configured_provider(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    gateway = LLMGateway(
        registry=_registry_with_openai_deepseek(),
        provider="openai",
        model="gpt-test",
        enable_cache=False,
        budget_tracker=LLMUsageBudgetTracker(),
    )
    calls: list[str] = []

    def fake_complete_route(**kwargs):
        route = kwargs["route"]
        calls.append(route.provider)
        if route.provider == "openai":
            raise RuntimeError("provider down")
        gateway._last_token_usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        return "ok"

    monkeypatch.setattr(gateway, "_complete_route", fake_complete_route)

    assert gateway.complete(system="s", user="u", llm_role="planner") == "ok"
    assert calls == ["openai", "deepseek"]
    assert gateway.provider == "deepseek"
    assert gateway._last_route["fallback_errors"]


def test_gateway_tracks_budget_by_user_run_and_role(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    tracker = LLMUsageBudgetTracker()
    gateway = LLMGateway(
        registry=_registry_with_openai_deepseek(budget_usd=0.001),
        provider="openai",
        model="gpt-test",
        enable_cache=False,
        budget_tracker=tracker,
        user_id="user-1",
        run_id="run-1",
    )

    def fake_complete_route(**_kwargs):
        gateway._last_token_usage = {"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2}
        gateway._last_cost_usd = 0.002
        return "ok"

    monkeypatch.setattr(gateway, "_complete_route", fake_complete_route)

    assert gateway.complete(system="s", user="u", llm_role="planner") == "ok"
    assert tracker.spent(user_id="user-1", run_id="run-1", role="planner") == pytest.approx(0.002)
    with pytest.raises(LLMAPIError, match="budget exceeded"):
        gateway.complete(system="s2", user="u2", llm_role="planner")


class StructuredGatewayPayload(BaseModel):
    title: str


def test_gateway_structured_output_uses_same_route_budget_and_node(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    tracker = LLMUsageBudgetTracker()
    gateway = LLMGateway(
        registry=_registry_with_openai_deepseek(budget_usd=0.001),
        provider="openai",
        model="gpt-test",
        enable_cache=False,
        budget_tracker=tracker,
        user_id="user-1",
        run_id="run-1",
    )

    def fake_structured_route(**kwargs):
        assert kwargs["output_model"] is StructuredGatewayPayload
        gateway._last_token_usage = {"prompt_tokens": 2, "completion_tokens": 0, "total_tokens": 2}
        gateway._last_cost_usd = 0.002
        return StructuredGatewayPayload(title="ok")

    monkeypatch.setattr(gateway, "_complete_structured_route", fake_structured_route)

    result = gateway.complete_structured(
        output_model=StructuredGatewayPayload,
        system="s",
        user="u",
        llm_role="enhancement_plan",
    )

    assert result.title == "ok"
    assert gateway._last_route["node"] == "enhancement_plan"
    assert gateway._last_route["structured_schema"] == "StructuredGatewayPayload"
    assert tracker.spent(user_id="user-1", run_id="run-1", node="enhancement_plan") == pytest.approx(0.002)
