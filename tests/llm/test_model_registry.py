from content_gen.llm.model_registry import (
    ModelRegistry,
    ModelRoleConfig,
    ModelRoute,
    get_llm_provider_summary,
    normalize_provider,
    resolve_configured_provider,
)


def test_openrouter_is_default_provider(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    assert resolve_configured_provider() == "openrouter"
    assert normalize_provider("gpt") == "openrouter"


def test_openrouter_route_uses_open_router_env_aliases(monkeypatch) -> None:
    monkeypatch.setenv("OPEN_ROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPEN_ROUTER_MODEL", "anthropic/claude-3.5-sonnet")
    monkeypatch.setenv("OPEN_ROUTER_BASE_URL", "https://openrouter.example/api/v1")

    route = ModelRoute(provider="open_router")

    assert route.provider == "openrouter"
    assert route.resolved_api_key() == "openrouter-key"
    assert route.resolved_model() == "anthropic/claude-3.5-sonnet"
    assert route.resolved_base_url() == "https://openrouter.example/api/v1"
    assert route.litellm_name() == "openrouter/anthropic/claude-3.5-sonnet"


def test_openrouter_summary_is_password_safe(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "openrouter-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-5.4-mini")

    summary = get_llm_provider_summary("openrouter")

    assert summary["provider"] == "openrouter"
    assert summary["available"] is True
    assert summary["model"] == "openai/gpt-5.4-mini"
    assert "openrouter-key" not in str(summary)


def test_registry_prefers_requested_provider_and_skips_unconfigured_routes(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")

    registry = ModelRegistry(
        roles={
            "planner": ModelRoleConfig(
                fallback_chain=[
                    ModelRoute(provider="openai", model="gpt-test"),
                    ModelRoute(provider="deepseek", model="deepseek-chat"),
                ]
            )
        }
    )

    chain = registry.chain_for_role("planner")

    assert [route.provider for route in chain] == ["deepseek"]
    assert chain[0].resolved_model() == "deepseek-chat"


def test_registry_maps_node_alias_to_role() -> None:
    registry = ModelRegistry(
        aliases={"title_annotation": "planner"},
        roles={"planner": ModelRoleConfig(fallback_chain=[])},
    )

    assert registry.canonical_role("title_annotation") == "planner"
    assert registry.role_config("title_annotation") is registry.roles["planner"]
