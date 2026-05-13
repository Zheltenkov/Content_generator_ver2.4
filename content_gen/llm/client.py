"""
content_gen/llm/client.py

Универсальный LLM клиент с поддержкой OpenAI, DeepSeek, Azure OpenAI и GigaChat.

Единая точка доступа к LLM API. Поддерживает:
- OpenAI
- DeepSeek через OpenAI-compatible API
- Azure OpenAI
- GigaChat через REST API и OAuth access token
- Настройка через переменные окружения (.env)
"""

import os
import time
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_GIGACHAT_BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"
DEFAULT_GIGACHAT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

SUPPORTED_LLM_PROVIDERS = {"openai", "azure", "deepseek", "gigachat"}
PROVIDER_ALIASES = {
    "gpt": "openai",
    "openai": "openai",
    "azure": "azure",
    "azure_openai": "azure",
    "deepseek": "deepseek",
    "gigachat": "gigachat",
    "giga": "gigachat",
}


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean environment flag without accepting ambiguous values silently."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def resolve_llm_provider(provider: str | None = None) -> str:
    """Resolve a configured LLM provider name to a supported canonical value."""
    raw_provider = (provider or os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    resolved = PROVIDER_ALIASES.get(raw_provider, raw_provider)
    if resolved not in SUPPORTED_LLM_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_LLM_PROVIDERS))
        raise ValueError(f"Неизвестный LLM_PROVIDER='{raw_provider}'. Поддерживаются: {supported}")
    return resolved


def get_llm_provider_summary(provider: str | None = None) -> dict[str, Any]:
    """Return password-safe diagnostics for the currently configured LLM provider."""
    resolved = resolve_llm_provider(provider)
    if resolved == "openai":
        configured = bool(os.getenv("OPENAI_API_KEY"))
        return {
            "provider": resolved,
            "available": configured,
            "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            "base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            "credential_env": "OPENAI_API_KEY",
        }
    if resolved == "azure":
        configured = bool(os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"))
        return {
            "provider": resolved,
            "available": configured,
            "model": os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini"),
            "base_url": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            "credential_env": "AZURE_OPENAI_API_KEY + AZURE_OPENAI_ENDPOINT",
        }
    if resolved == "deepseek":
        configured = bool(os.getenv("DEEPSEEK_API_KEY"))
        return {
            "provider": resolved,
            "available": configured,
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            "base_url": os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL,
            "credential_env": "DEEPSEEK_API_KEY",
        }

    configured = bool(os.getenv("GIGACHAT_CREDENTIALS") or os.getenv("GIGACHAT_API_KEY"))
    return {
        "provider": resolved,
        "available": configured,
        "model": os.getenv("GIGACHAT_MODEL", "GigaChat-2-Pro"),
        "base_url": os.getenv("GIGACHAT_BASE_URL") or DEFAULT_GIGACHAT_BASE_URL,
        "credential_env": "GIGACHAT_CREDENTIALS",
    }


class LLMClient:
    """Унифицированный клиент LLM с оптимизированным API."""

    # Параметры, которые нужно удалять, если модель не поддерживает
    UNSUPPORTED_ARGS = {"temperature", "top_p", "logprobs"}

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        temperature: float | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
    ):
        resolved_provider = resolve_llm_provider(provider)
        if resolved_provider != "gigachat" and not OPENAI_AVAILABLE:
            raise ImportError("Установите: pip install openai>=1.0.0")

        self.provider = resolved_provider
        self._max_retries = max_retries or int(os.getenv("LLM_MAX_RETRIES", "3"))
        self._retry_delay = retry_delay or float(os.getenv("LLM_RETRY_DELAY", "1.0"))
        self._last_finish_reason: str | None = None
        self._last_token_usage: dict[str, int | None] | None = None

        if self.provider == "openai":
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            self.temperature = temperature if temperature is not None else float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
            base_url = os.getenv("OPENAI_BASE_URL")
            # Увеличиваем таймаут для длинных запросов (по умолчанию 60 секунд, увеличиваем до 120)
            import httpx
            timeout = httpx.Timeout(120.0, connect=10.0)  # 120 секунд на запрос, 10 секунд на подключение
            self.client = OpenAI(api_key=self.api_key, base_url=base_url or None, timeout=timeout)

        elif self.provider == "deepseek":
            self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
            self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
            self.temperature = temperature if temperature is not None else float(os.getenv("DEEPSEEK_TEMPERATURE", "0.3"))
            base_url = os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_DEEPSEEK_BASE_URL
            import httpx
            timeout = httpx.Timeout(120.0, connect=10.0)
            self.client = OpenAI(api_key=self.api_key, base_url=base_url, timeout=timeout)

        elif self.provider == "azure":
            self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY")
            self.model = model or os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-4o-mini")
            self.temperature = temperature if temperature is not None else float(os.getenv("AZURE_OPENAI_TEMPERATURE", "0.2"))
            endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
            api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
            if not endpoint:
                raise ValueError("AZURE_OPENAI_ENDPOINT не указан в .env")
            # Увеличиваем таймаут для длинных запросов (по умолчанию 60 секунд, увеличиваем до 120)
            import httpx
            timeout = httpx.Timeout(120.0, connect=10.0)  # 120 секунд на запрос, 10 секунд на подключение
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=f"{endpoint.rstrip('/')}/openai/deployments/{self.model}",
                api_version=api_version,
                timeout=timeout,
            )
        elif self.provider == "gigachat":
            self.api_key = api_key or os.getenv("GIGACHAT_CREDENTIALS") or os.getenv("GIGACHAT_API_KEY")
            self.model = model or os.getenv("GIGACHAT_MODEL", "GigaChat-2-Pro")
            self.temperature = temperature if temperature is not None else float(os.getenv("GIGACHAT_TEMPERATURE", "0.3"))
            self.base_url = (os.getenv("GIGACHAT_BASE_URL") or DEFAULT_GIGACHAT_BASE_URL).rstrip("/")
            self._gigachat_auth_url = os.getenv("GIGACHAT_AUTH_URL") or DEFAULT_GIGACHAT_AUTH_URL
            self._gigachat_scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
            self._gigachat_verify_ssl_certs = _env_bool("GIGACHAT_VERIFY_SSL_CERTS", True)
            self._gigachat_token: str | None = None
            self._gigachat_token_expires_at: float = 0.0
            import httpx
            timeout = httpx.Timeout(120.0, connect=10.0)
            self.client = httpx.Client(timeout=timeout, verify=self._gigachat_verify_ssl_certs)
        else:
            raise ValueError("provider должен быть 'openai', 'deepseek', 'azure' или 'gigachat'")

        if not self.api_key:
            credential_env = get_llm_provider_summary(self.provider)["credential_env"]
            raise ValueError(f"API KEY не найден в .env: задайте {credential_env}")

    def _clean_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Удаляет несовместимые параметры и приводит max_tokens → max_completion_tokens."""
        kwargs = dict(kwargs)

        if self.provider in {"openai", "azure"} and "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        if self.provider in {"openai", "azure"}:
            # Удаляем несовместимые параметры для актуального OpenAI-контура.
            for bad in self.UNSUPPORTED_ARGS:
                kwargs.pop(bad, None)

        return kwargs

    def _gigachat_auth_header(self) -> str:
        """Return a GigaChat OAuth Authorization header from credentials."""
        credentials = (self.api_key or "").strip()
        if credentials.lower().startswith(("basic ", "bearer ")):
            return credentials
        return f"Basic {credentials}"

    def _get_gigachat_access_token(self) -> str:
        """Fetch and cache a short-lived GigaChat access token."""
        now = time.time()
        if self._gigachat_token and now < self._gigachat_token_expires_at - 30:
            return self._gigachat_token

        response = self.client.post(
            self._gigachat_auth_url,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
                "RqUID": str(uuid.uuid4()),
                "Authorization": self._gigachat_auth_header(),
            },
            data={"scope": self._gigachat_scope},
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("GigaChat OAuth не вернул access_token")

        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)):
            # В разных примерах встречаются seconds и milliseconds epoch.
            self._gigachat_token_expires_at = float(expires_at) / 1000 if expires_at > 10_000_000_000 else float(expires_at)
        else:
            self._gigachat_token_expires_at = now + 30 * 60

        self._gigachat_token = str(token)
        return self._gigachat_token

    def _complete_gigachat(
        self,
        system: str,
        user: str,
        response_format: str | dict[str, Any] | None = None,
        **kwargs,
    ) -> str:
        """Call GigaChat REST chat completions with cached OAuth credentials."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        elif isinstance(response_format, dict):
            payload["response_format"] = response_format

        provider_kwargs = self._clean_kwargs(kwargs)
        provider_kwargs.setdefault("temperature", self.temperature)
        payload.update(provider_kwargs)

        response = self.client.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self._get_gigachat_access_token()}",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or ""
        self._last_finish_reason = choice.get("finish_reason")
        usage = data.get("usage") or {}
        self._last_token_usage = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        } if usage else None
        return str(content).strip()

    def complete(
        self,
        system: str,
        user: str,
        response_format: str | dict[str, Any] | None = None,
        **kwargs,
    ) -> str:
        """
        Вызов chat.completions в унифицированном виде.
        
        Args:
            system: Системный промпт
            user: Пользовательский промпт
            response_format: Формат ответа:
                - "json_object" для базового JSON mode
                - Dict с JSON Schema для structured outputs
                - None для обычного текста
            **kwargs: Дополнительные параметры
        """
        if self.provider == "gigachat":
            last_error = None
            for attempt in range(self._max_retries):
                try:
                    return self._complete_gigachat(system, user, response_format, **kwargs)
                except Exception as e:
                    last_error = e
                    error_str = str(e).lower()
                    if "timeout" in error_str or "timed out" in error_str:
                        from ..exceptions import LLMTimeoutError
                        if attempt < self._max_retries - 1:
                            delay = self._retry_delay * (2 ** attempt)
                            time.sleep(delay)
                            continue
                        raise LLMTimeoutError(f"Таймаут при вызове LLM: {e}") from e
                    if "rate limit" in error_str or "429" in error_str:
                        from ..exceptions import LLMRateLimitError
                        if attempt < self._max_retries - 1:
                            delay = self._retry_delay * (2 ** attempt)
                            time.sleep(delay)
                            continue
                        raise LLMRateLimitError(f"Превышен rate limit LLM: {e}") from e
                    if attempt < self._max_retries - 1:
                        delay = self._retry_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    from ..exceptions import LLMAPIError
                    raise LLMAPIError(f"Ошибка LLM API после {self._max_retries} попыток: {e}") from e

            from ..exceptions import LLMAPIError
            raise LLMAPIError(f"Ошибка LLM API: {last_error}") from last_error

        create_kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        # JSON MODE или STRUCTURED OUTPUTS
        if response_format == "json_object":
            create_kwargs["response_format"] = {"type": "json_object"}
        elif isinstance(response_format, dict):
            # Structured outputs с JSON Schema
            create_kwargs["response_format"] = response_format

        # Param cleanup
        provider_kwargs = self._clean_kwargs(kwargs)
        if self.provider == "deepseek":
            provider_kwargs.setdefault("temperature", self.temperature)
        create_kwargs.update(provider_kwargs)

        # Retry logic с exponential backoff
        last_error = None
        for attempt in range(self._max_retries):
            try:
                response = self.client.chat.completions.create(**create_kwargs)

                choice = response.choices[0]
                content = choice.message.content
                self._last_finish_reason = choice.finish_reason
                usage = getattr(response, "usage", None)
                self._last_token_usage = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                    "total_tokens": getattr(usage, "total_tokens", None),
                } if usage is not None else None

                if choice.finish_reason == "length":
                    import sys
                    print("Ответ обрезан токенами (finish_reason=length)", file=sys.stderr, flush=True)

                return content.strip() if content else ""

            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Определяем тип ошибки
                if "timeout" in error_str or "timed out" in error_str:
                    from ..exceptions import LLMTimeoutError
                    if attempt < self._max_retries - 1:
                        delay = self._retry_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    raise LLMTimeoutError(f"Таймаут при вызове LLM: {e}") from e
                elif "rate limit" in error_str or "429" in error_str:
                    from ..exceptions import LLMRateLimitError
                    if attempt < self._max_retries - 1:
                        delay = self._retry_delay * (2 ** attempt)
                        time.sleep(delay)
                        continue
                    raise LLMRateLimitError(f"Превышен rate limit LLM: {e}") from e
                elif attempt < self._max_retries - 1:
                    # Другие ошибки - retry с задержкой
                    delay = self._retry_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                else:
                    # Последняя попытка
                    from ..exceptions import LLMAPIError
                    raise LLMAPIError(f"Ошибка LLM API после {self._max_retries} попыток: {e}") from e

        # Не должно сюда попасть
        from ..exceptions import LLMAPIError
        raise LLMAPIError(f"Ошибка LLM API: {last_error}") from last_error

