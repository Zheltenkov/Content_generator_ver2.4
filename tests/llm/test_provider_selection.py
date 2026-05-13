"""Provider selection tests for the shared LLM client."""

from unittest.mock import Mock, patch

from content_gen.llm.client import DEFAULT_DEEPSEEK_BASE_URL, LLMClient, get_llm_provider_summary, resolve_llm_provider


def test_resolve_llm_provider_uses_env_and_aliases(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gpt")

    assert resolve_llm_provider() == "openai"
    assert resolve_llm_provider("deepseek") == "deepseek"
    assert resolve_llm_provider("giga") == "gigachat"


@patch("content_gen.llm.client.OpenAI")
def test_deepseek_uses_openai_compatible_transport(mock_openai, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-test-model")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)

    client = LLMClient()

    assert client.provider == "deepseek"
    assert client.model == "deepseek-test-model"
    assert mock_openai.call_args.kwargs["api_key"] == "deepseek-test-key"
    assert mock_openai.call_args.kwargs["base_url"] == DEFAULT_DEEPSEEK_BASE_URL


def test_gigachat_fetches_access_token_and_calls_chat_completions(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "gigachat-basic-token")
    monkeypatch.setenv("GIGACHAT_MODEL", "GigaChat-test")

    auth_response = Mock()
    auth_response.json.return_value = {"access_token": "access-token", "expires_at": 4_102_444_800_000}
    auth_response.raise_for_status.return_value = None

    chat_response = Mock()
    chat_response.json.return_value = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    chat_response.raise_for_status.return_value = None

    http_client = Mock()
    http_client.post.side_effect = [auth_response, chat_response]

    with patch("httpx.Client", return_value=http_client):
        client = LLMClient()
        result = client.complete("system", "user", response_format="json_object")

    assert result == "ok"
    assert client.provider == "gigachat"
    assert client.model == "GigaChat-test"
    assert http_client.post.call_count == 2

    auth_call = http_client.post.call_args_list[0]
    assert auth_call.kwargs["headers"]["Authorization"] == "Basic gigachat-basic-token"
    assert auth_call.kwargs["data"] == {"scope": "GIGACHAT_API_PERS"}

    chat_call = http_client.post.call_args_list[1]
    assert chat_call.args[0].endswith("/chat/completions")
    assert chat_call.kwargs["headers"]["Authorization"] == "Bearer access-token"
    assert chat_call.kwargs["json"]["response_format"] == {"type": "json_object"}
    assert chat_call.kwargs["json"]["temperature"] == 0.3


def test_llm_provider_summary_reports_selected_provider_without_secret(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_CREDENTIALS", "secret")
    monkeypatch.setenv("GIGACHAT_MODEL", "GigaChat-test")

    summary = get_llm_provider_summary()

    assert summary["provider"] == "gigachat"
    assert summary["available"] is True
    assert summary["model"] == "GigaChat-test"
    assert "secret" not in str(summary)
