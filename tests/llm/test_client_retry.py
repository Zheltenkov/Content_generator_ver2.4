"""Тесты для retry logic в LLM клиенте."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from content_gen.exceptions import LLMAPIError
from content_gen.llm.client import LLMClient


class TestLLMClientRetry:
    """Тесты retry logic в LLMClient."""

    @pytest.fixture
    def mock_openai_client(self):
        """Мок OpenAI клиента."""
        mock_client = Mock()
        mock_chat = Mock()
        mock_completions = Mock()
        mock_client.chat = mock_chat
        mock_chat.completions = mock_completions
        return mock_client, mock_completions

    @patch('content_gen.llm.client.OpenAI')
    def test_retry_on_rate_limit(self, mock_openai_class, mock_openai_client):
        """Тест retry при rate limit."""
        mock_client, mock_completions = mock_openai_client
        mock_openai_class.return_value = mock_client

        # Первые две попытки - rate limit, третья - успех
        mock_completions.create.side_effect = [
            Exception("rate limit exceeded"),
            Exception("rate limit exceeded"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Success"), finish_reason="stop")])
        ]

        with patch('time.sleep'):  # Пропускаем sleep в тестах
            client = LLMClient(max_retries=3, retry_delay=0.1)
            result = client.complete("system", "user")

            assert result == "Success"
            assert mock_completions.create.call_count == 3

    @patch('content_gen.llm.client.OpenAI')
    def test_retry_on_timeout(self, mock_openai_class, mock_openai_client):
        """Тест retry при timeout."""
        mock_client, mock_completions = mock_openai_client
        mock_openai_class.return_value = mock_client

        mock_completions.create.side_effect = [
            Exception("timeout"),
            Exception("timeout"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Success"), finish_reason="stop")])
        ]

        with patch('time.sleep'):
            client = LLMClient(max_retries=3, retry_delay=0.1)
            result = client.complete("system", "user")

            assert result == "Success"
            assert mock_completions.create.call_count == 3

    @patch('content_gen.llm.client.OpenAI')
    def test_max_retries_exceeded(self, mock_openai_class, mock_openai_client):
        """Тест превышения max retries."""
        mock_client, mock_completions = mock_openai_client
        mock_openai_class.return_value = mock_client

        mock_completions.create.side_effect = Exception("API error")

        with patch('time.sleep'):
            client = LLMClient(max_retries=2, retry_delay=0.1)

            with pytest.raises(LLMAPIError):
                client.complete("system", "user")

            assert mock_completions.create.call_count == 2

    @patch('content_gen.llm.client.OpenAI')
    def test_exponential_backoff(self, mock_openai_class, mock_openai_client):
        """Тест exponential backoff."""
        mock_client, mock_completions = mock_openai_client
        mock_openai_class.return_value = mock_client

        mock_completions.create.side_effect = [
            Exception("rate limit"),
            Exception("rate limit"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="Success"), finish_reason="stop")])
        ]

        sleep_calls = []
        def mock_sleep(delay):
            sleep_calls.append(delay)

        with patch('time.sleep', side_effect=mock_sleep):
            client = LLMClient(max_retries=3, retry_delay=1.0)
            client.complete("system", "user")

            # Проверяем, что задержки увеличиваются экспоненциально
            assert len(sleep_calls) == 2
            assert sleep_calls[0] == 1.0  # 2^0 * 1.0
            assert sleep_calls[1] == 2.0  # 2^1 * 1.0

