"""Tests for didactics integration in API routers."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.dependencies import get_current_user
from api.routers import generation, readme_improvement


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(readme_improvement.router)
    app.include_router(generation.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    return app


def test_rewrite_uses_composer_context(monkeypatch):
    app = _build_app()
    client = TestClient(app)

    monkeypatch.setattr(
        "api.routers.readme_improvement.compose_didactics_context",
        lambda _agent: ("RULE: keep concise", {"didactics_mode": "mixed", "didactics_skills_used": ["rewrite_style"]}),
    )

    captured = {}

    class _DummyLLM:
        def complete(self, **kwargs):
            captured["system"] = kwargs.get("system", "")
            captured["user"] = kwargs.get("user", "")
            return "# rewritten"

    monkeypatch.setattr("api.routers.readme_improvement.LLMClient", _DummyLLM)

    response = client.post(
        "/readme/rewrite",
        json={"markdown": "# old", "instruction": "Сделай короче", "seed_optional": {"language": "ru"}},
    )
    assert response.status_code == 200
    assert response.json()["markdown"] == "# rewritten"
    assert "RULE: keep concise" in captured["system"]


def test_stepwise_state_contains_didactics_metadata(monkeypatch):
    app = _build_app()
    client = TestClient(app)

    monkeypatch.setattr(
        "api.routers.generation.compose_didactics_context",
        lambda _agent: ("RULE: intro", {"didactics_mode": "strict", "didactics_skills_used": ["intro_rules"]}),
    )
    monkeypatch.setattr(
        "api.routers.generation.get_didactics_trace",
        lambda: {"didactics_bundle_version": "1.2.3", "didactics_mode": "strict", "didactics_bindings": {"intro_rules": ["intro_rules"]}},
    )

    start_resp = client.post("/generation/start", json={"seed": {"title_seed": "x"}, "stepwise": True})
    assert start_resp.status_code == 200
    request_id = start_resp.json()["request_id"]

    continue_resp = client.post(f"/generation/{request_id}/continue")
    assert continue_resp.status_code == 200
    payload = continue_resp.json()
    assert payload["metadata"]["didactics"]["trace"]["didactics_mode"] == "strict"
    assert payload["metadata"]["didactics"]["agent_trace"]["didactics_skills_used"] == ["intro_rules"]
    assert payload["metadata"]["didactics"]["has_context"] is True

