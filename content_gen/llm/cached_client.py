"""
Оптимизированный LLM клиент с кэшированием и батчингом.
"""

import concurrent.futures
import hashlib
import json
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

from ..exceptions import LLMAPIError, LLMRateLimitError, LLMTimeoutError
from .client import LLMClient


@dataclass
class CacheEntry:
    """Запись в кэше."""
    response: str
    timestamp: float
    ttl: float


class CachedLLMClient(LLMClient):
    """
    LLM клиент с кэшированием и батчингом.
    
    Наследуется от базового LLMClient и добавляет:
    - Кэширование ответов (in-memory или Redis)
    - Батчинг независимых запросов (параллельные вызовы)
    - Retry с экспоненциальной задержкой
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        provider: str = "openai",
        temperature: float | None = None,
        enable_cache: bool | None = None,
        enable_batching: bool | None = None,
        cache_ttl: int | None = None,
        max_cache_size: int | None = None,
        max_retries: int | None = None,
        retry_delay: float | None = None,
    ):
        """
        Args:
            model: Модель LLM
            api_key: API ключ
            provider: Провайдер (openai, azure)
            temperature: Температура
            enable_cache: Включить кэширование (по умолчанию из env или True)
            enable_batching: Включить батчинг (по умолчанию из env или True)
            cache_ttl: TTL кэша в секундах (по умолчанию 3600)
            max_cache_size: Максимальный размер in-memory кэша (по умолчанию 10000)
            max_retries: Максимальное количество повторов (по умолчанию 3)
            retry_delay: Начальная задержка между повторами в секундах (по умолчанию 1.0)
        """
        super().__init__(model, api_key, provider, temperature)

        # Настройки из переменных окружения или значения по умолчанию
        self.enable_cache = enable_cache if enable_cache is not None else (
            os.getenv("LLM_CACHE_ENABLED", "true").lower() == "true"
        )
        self.enable_batching = enable_batching if enable_batching is not None else (
            os.getenv("LLM_BATCHING_ENABLED", "true").lower() == "true"
        )
        self._cache_ttl = cache_ttl or int(os.getenv("LLM_CACHE_TTL", "3600"))
        self._max_cache_size = max_cache_size or int(os.getenv("LLM_CACHE_MAX_SIZE", "10000"))
        self._max_retries = max_retries or int(os.getenv("LLM_MAX_RETRIES", "3"))
        self._retry_delay = retry_delay or float(os.getenv("LLM_RETRY_DELAY", "1.0"))

        # Кэш (in-memory)
        self._cache: dict[str, CacheEntry] = {}
        self._cache_lock = Lock()

        # Redis кэш (опционально)
        self._redis_client = None
        if self.enable_cache:
            redis_url = os.getenv("REDIS_URL")
            if redis_url and redis_url != "":
                try:
                    import redis
                    self._redis_client = redis.from_url(redis_url, decode_responses=True)
                except ImportError:
                    pass
                except Exception:
                    # Если Redis недоступен, продолжаем без него
                    pass

    def _cache_key(self, system: str, user: str, response_format: str | None, **kwargs) -> str:
        """Генерирует ключ кэша."""
        key_data = {
            "system": system,
            "user": user,
            "response_format": response_format,
            "model": self.model,
            "temperature": self.temperature,
            **kwargs
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.sha256(key_str.encode()).hexdigest()

    def _get_from_cache(self, cache_key: str) -> str | None:
        """Получает значение из кэша."""
        # Пробуем Redis
        if self._redis_client:
            try:
                cached = self._redis_client.get(f"llm_cache:{cache_key}")
                if cached:
                    return cached
            except Exception:
                pass

        # Пробуем in-memory кэш
        with self._cache_lock:
            entry = self._cache.get(cache_key)
            if entry:
                if time.time() - entry.timestamp < entry.ttl:
                    return entry.response
                else:
                    # Удаляем устаревшую запись
                    del self._cache[cache_key]

        return None

    def _save_to_cache(self, cache_key: str, response: str):
        """Сохраняет значение в кэш."""
        # Сохраняем в Redis
        if self._redis_client:
            try:
                self._redis_client.setex(
                    f"llm_cache:{cache_key}",
                    self._cache_ttl,
                    response
                )
            except Exception:
                pass

        # Сохраняем в in-memory кэш
        with self._cache_lock:
            # Очищаем старые записи, если кэш переполнен
            if len(self._cache) >= self._max_cache_size:
                # Удаляем 10% самых старых записей
                sorted_entries = sorted(
                    self._cache.items(),
                    key=lambda x: x[1].timestamp
                )
                to_remove = max(1, len(sorted_entries) // 10)
                for key, _ in sorted_entries[:to_remove]:
                    del self._cache[key]

            self._cache[cache_key] = CacheEntry(
                response=response,
                timestamp=time.time(),
                ttl=self._cache_ttl
            )

    def _retry_with_backoff(self, func, *args, **kwargs):
        """Выполняет функцию с retry и экспоненциальной задержкой."""
        last_error = None

        for attempt in range(self._max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                is_timeout = "timeout" in error_str or "timed out" in error_str
                is_rate_limit = "rate limit" in error_str or "429" in error_str

                if attempt < self._max_retries - 1:
                    # Другие ошибки - retry с задержкой
                    delay = self._retry_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue

                if is_timeout:
                    raise LLMTimeoutError(
                        f"Таймаут при вызове LLM: {e}",
                        context={"attempt": attempt + 1, "max_retries": self._max_retries}
                    ) from e
                if is_rate_limit:
                    raise LLMRateLimitError(
                        f"Превышен rate limit LLM: {e}",
                        context={"attempt": attempt + 1, "max_retries": self._max_retries}
                    ) from e
                else:
                    # Последняя попытка - пробрасываем ошибку
                    raise LLMAPIError(
                        f"Ошибка LLM API после {self._max_retries} попыток: {e}",
                        context={"attempt": attempt + 1, "max_retries": self._max_retries}
                    ) from e

        # Не должно сюда попасть, но на всякий случай
        raise LLMAPIError(
            f"Ошибка LLM API: {last_error}",
            context={"attempt": self._max_retries, "max_retries": self._max_retries}
        ) from last_error

    def complete(
        self,
        system: str,
        user: str,
        response_format: str | None = None,
        use_cache: bool = True,
        **kwargs,
    ) -> str:
        """
        Выполняет запрос к LLM с кэшированием и retry.
        
        Args:
            system: Системный промпт
            user: Пользовательский промпт
            response_format: Формат ответа
            use_cache: Использовать кэш (по умолчанию True)
            **kwargs: Дополнительные параметры
            
        Returns:
            Ответ от LLM
        """
        # Проверяем кэш
        if self.enable_cache and use_cache:
            cache_key = self._cache_key(system, user, response_format, **kwargs)
            cached_response = self._get_from_cache(cache_key)
            if cached_response is not None:
                return cached_response

        # Выполняем запрос с retry
        # Используем явную ссылку на базовый класс, чтобы избежать проблем с super() во вложенной функции
        def _call_llm():
            return LLMClient.complete(self, system, user, response_format, **kwargs)

        response = self._retry_with_backoff(_call_llm)

        # Сохраняем в кэш
        if self.enable_cache and use_cache:
            cache_key = self._cache_key(system, user, response_format, **kwargs)
            self._save_to_cache(cache_key, response)

        return response

    def complete_batch(
        self,
        requests: list[tuple[str, str, str | None, dict[str, Any]]],
    ) -> list[str]:
        """
        Выполняет батч запросов к LLM (параллельно).
        
        Args:
            requests: Список кортежей (system, user, response_format, kwargs)
            
        Returns:
            Список ответов
        """
        if not self.enable_batching:
            # Если батчинг отключен, выполняем последовательно
            results = []
            for system, user, response_format, kwargs in requests:
                results.append(self.complete(system, user, response_format, **kwargs))
            return results

        # Параллельные вызовы
        results = [""] * len(requests)
        max_workers = min(len(requests), 10)  # Максимум 10 параллельных запросов

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict[concurrent.futures.Future[str], int] = {}
            for idx, (system, user, response_format, kwargs) in enumerate(requests):
                future = executor.submit(
                    self.complete,
                    system=system,
                    user=user,
                    response_format=response_format,
                    **kwargs
                )
                futures[future] = idx

            for future in concurrent.futures.as_completed(futures):
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    # В случае ошибки добавляем пустую строку и логируем
                    import sys
                    print(f"⚠️ Ошибка в батч запросе: {e}", file=sys.stderr, flush=True)
                    results[idx] = ""

        return results
