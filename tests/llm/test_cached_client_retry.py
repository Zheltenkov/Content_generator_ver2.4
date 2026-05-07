"""Tests for retry behavior in CachedLLMClient."""

from unittest.mock import patch

import pytest

from content_gen.exceptions import LLMTimeoutError
from content_gen.llm.cached_client import CachedLLMClient


def test_cached_client_retries_timeout_and_then_succeeds():
    client = object.__new__(CachedLLMClient)
    client._max_retries = 3
    client._retry_delay = 0.1

    calls = {"n": 0}

    def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise Exception("timeout")
        return "ok"

    with patch("time.sleep"):
        result = client._retry_with_backoff(_flaky)

    assert result == "ok"
    assert calls["n"] == 3


def test_cached_client_raises_timeout_after_retries_exhausted():
    client = object.__new__(CachedLLMClient)
    client._max_retries = 2
    client._retry_delay = 0.1

    def _always_timeout():
        raise Exception("timed out")

    with patch("time.sleep"):
        with pytest.raises(LLMTimeoutError):
            client._retry_with_backoff(_always_timeout)

