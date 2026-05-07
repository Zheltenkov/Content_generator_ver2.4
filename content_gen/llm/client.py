"""
content_gen/llm/client.py

Универсальный LLM клиент с поддержкой OpenAI и Azure OpenAI.

Единая точка доступа к LLM API. Поддерживает:
- OpenAI (GPT-4, GPT-3.5)
- Azure OpenAI
- Настройка через переменные окружения (.env)
"""

import os
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class LLMClient:
    """Унифицированный клиент LLM с оптимизированным API."""

    # Параметры, которые нужно удалять, если модель не поддерживает
    UNSUPPORTED_ARGS = {"temperature", "top_p", "logprobs"}

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        provider: str = "openai",
        temperature: float | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
    ):
        if not OPENAI_AVAILABLE:
            raise ImportError("Установите: pip install openai>=1.0.0")

        self.provider = provider.lower()
        self._max_retries = max_retries or int(os.getenv("LLM_MAX_RETRIES", "3"))
        self._retry_delay = retry_delay or float(os.getenv("LLM_RETRY_DELAY", "1.0"))

        if self.provider == "openai":
            self.api_key = api_key or os.getenv("OPENAI_API_KEY")
            self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            self.temperature = temperature if temperature is not None else float(os.getenv("OPENAI_TEMPERATURE", "0.2"))
            base_url = os.getenv("OPENAI_BASE_URL")
            # Увеличиваем таймаут для длинных запросов (по умолчанию 60 секунд, увеличиваем до 120)
            import httpx
            timeout = httpx.Timeout(120.0, connect=10.0)  # 120 секунд на запрос, 10 секунд на подключение
            self.client = OpenAI(api_key=self.api_key, base_url=base_url or None, timeout=timeout)

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
        else:
            raise ValueError("provider должен быть 'openai' или 'azure'")

        if not self.api_key:
            raise ValueError("API KEY не найден в .env")

        self._last_finish_reason: str | None = None

    def _clean_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Удаляет несовместимые параметры и приводит max_tokens → max_completion_tokens."""
        kwargs = dict(kwargs)

        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")

        # Удаляем несовместимые параметры
        for bad in self.UNSUPPORTED_ARGS:
            kwargs.pop(bad, None)

        return kwargs

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
        create_kwargs.update(self._clean_kwargs(kwargs))

        # Retry logic с exponential backoff
        last_error = None
        for attempt in range(self._max_retries):
            try:
                response = self.client.chat.completions.create(**create_kwargs)

                choice = response.choices[0]
                content = choice.message.content
                self._last_finish_reason = choice.finish_reason

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

