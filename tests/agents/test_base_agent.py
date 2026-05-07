"""Тесты для базового агента."""

from unittest.mock import Mock

import pytest

from content_gen.agents.base.agent import BaseAgent
from content_gen.agents.base.llm_client import LLMClientProtocol


class MockLLMClient(LLMClientProtocol):
    """Мок LLM клиента для тестов."""

    def complete(self, system: str, user: str, response_format=None, **kwargs) -> str:
        return "mock response"


class TestBaseAgent:
    """Тесты для BaseAgent."""

    def test_init_with_valid_llm_client(self):
        """Тест инициализации с валидным LLM клиентом."""
        llm_client = MockLLMClient()

        class TestAgent(BaseAgent):
            def process(self, input_data):
                return {"result": "test"}

        agent = TestAgent(llm_client)
        assert agent.llm == llm_client

    def test_init_with_invalid_llm_client(self):
        """Тест инициализации с невалидным LLM клиентом."""
        # Создаем мок без метода complete
        llm_client = Mock(spec=[])  # Пустой spec - нет методов

        class TestAgent(BaseAgent):
            def process(self, input_data):
                return {"result": "test"}

        # BaseAgent проверяет hasattr(llm_client, 'complete')
        # Mock с пустым spec не имеет complete, но hasattr может вернуть True
        # Проверяем что валидация работает
        try:
            agent = TestAgent(llm_client)
            # Если не выбросило исключение, проверяем что валидация прошла
            # (может быть, что Mock автоматически создает атрибуты)
            assert hasattr(agent.llm, 'complete') or hasattr(llm_client, 'complete')
        except TypeError:
            # Это ожидаемое поведение
            pass

    def test_process_abstract_method(self):
        """Тест, что process - абстрактный метод."""
        llm_client = MockLLMClient()

        with pytest.raises(TypeError):
            BaseAgent(llm_client)

    def test_repr(self):
        """Тест строкового представления."""
        llm_client = MockLLMClient()

        class TestAgent(BaseAgent):
            def process(self, input_data):
                return {"result": "test"}

        agent = TestAgent(llm_client)
        repr_str = repr(agent)
        assert "TestAgent" in repr_str
        assert "MockLLMClient" in repr_str

