"""Tests for CachedLLMClient batch behavior."""

import time

from content_gen.llm.cached_client import CachedLLMClient


def test_complete_batch_preserves_request_order():
    client = object.__new__(CachedLLMClient)
    client.enable_batching = True

    def _mock_complete(system: str, user: str, response_format=None, **kwargs) -> str:
        if user == "slow":
            time.sleep(0.05)
        if user == "fast":
            time.sleep(0.01)
        return f"{system}:{user}"

    client.complete = _mock_complete

    requests = [
        ("s1", "slow", None, {}),
        ("s2", "fast", None, {}),
    ]
    result = client.complete_batch(requests)
    assert result == ["s1:slow", "s2:fast"]

