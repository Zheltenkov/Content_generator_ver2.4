"""Базовый класс для всех агентов."""

from abc import ABC, abstractmethod
from typing import Any

from .llm_client import LLMClientProtocol


class BaseAgent(ABC):
    """Базовый класс для всех агентов генерации контента."""

    def __init__(self, llm_client: LLMClientProtocol):
        """
        Инициализация агента.
        
        Args:
            llm_client: LLM клиент для генерации (реализует LLMClientProtocol)
        """
        self.llm = llm_client
        self._validate_llm_client(llm_client)

    def _validate_llm_client(self, llm_client: LLMClientProtocol) -> None:
        """
        Валидирует, что llm_client реализует необходимый интерфейс.
        
        Args:
            llm_client: LLM клиент для проверки
        """
        if not hasattr(llm_client, 'complete'):
            raise TypeError(
                f"LLM клиент должен иметь метод 'complete'. "
                f"Получен: {type(llm_client)}"
            )

    @abstractmethod
    def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Обрабатывает входные данные и возвращает результат.
        
        Args:
            input_data: Входные данные для обработки
            
        Returns:
            Словарь с результатами обработки
        """
        pass

    def __repr__(self) -> str:
        """Строковое представление агента."""
        return f"{self.__class__.__name__}(llm={type(self.llm).__name__})"

    def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Совместимый алиас для старого контракта run() -> process()."""
        return self.process(input_data)
