from content_gen.llm.model_registry import ModelRegistry, ModelRoleConfig, ModelRoute


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
