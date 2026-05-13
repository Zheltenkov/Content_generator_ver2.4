"""Observability wrapper for LLM clients."""

from __future__ import annotations

import time
from typing import Any

from content_gen.observability import LLMCallTraceEvent, LLMTraceRecorder, TokenUsage


class ObservedLLMClient:
    """Proxy that records every LLM call while preserving the wrapped client API."""

    def __init__(
        self,
        inner: Any,
        recorder: LLMTraceRecorder,
        *,
        node: str = "generation",
        agent: str = "unknown",
        prompt_version: str | None = None,
    ) -> None:
        self._inner = inner
        self._recorder = recorder
        self._node = node
        self._agent = agent
        self._prompt_version = prompt_version

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @property
    def model(self) -> str | None:
        return getattr(self._inner, "model", None)

    def scoped(
        self,
        *,
        node: str | None = None,
        agent: str | None = None,
        prompt_version: str | None = None,
    ) -> "ObservedLLMClient":
        """Return a view with more specific trace metadata."""
        return ObservedLLMClient(
            self._inner,
            self._recorder,
            node=node or self._node,
            agent=agent or self._agent,
            prompt_version=prompt_version or self._prompt_version,
        )

    def complete(
        self,
        system: str,
        user: str,
        response_format: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Call wrapped client and record latency/status/schema metadata."""
        started = time.perf_counter()
        try:
            response = self._inner.complete(system=system, user=user, response_format=response_format, **kwargs)
        except Exception as exc:
            self._record(
                system=system,
                user=user,
                response_format=response_format,
                started=started,
                status="error",
                error=str(exc),
                kwargs=kwargs,
            )
            raise
        self._record(
            system=system,
            user=user,
            response_format=response_format,
            started=started,
                status="success",
                error=None,
                kwargs=kwargs,
            )
        return response

    def complete_batch(
        self,
        requests: list[tuple[str, str, str | dict[str, Any] | None, dict[str, Any]]],
    ) -> list[str]:
        """Run a batch through the wrapped client and record one trace per item."""
        if not hasattr(self._inner, "complete_batch"):
            return [
                self.complete(system=system, user=user, response_format=response_format, **(kwargs or {}))
                for system, user, response_format, kwargs in requests
            ]
        started = time.perf_counter()
        try:
            results = self._inner.complete_batch(requests)
        except Exception as exc:
            for system, user, response_format, kwargs in requests:
                self._record(
                    system=system,
                    user=user,
                    response_format=response_format,
                    started=started,
                    status="error",
                    error=str(exc),
                    kwargs=dict(kwargs or {}),
                    include_last_usage=False,
                )
            raise
        for system, user, response_format, kwargs in requests:
            self._record(
                system=system,
                user=user,
                response_format=response_format,
                started=started,
                status="success",
                error=None,
                kwargs=dict(kwargs or {}),
                include_last_usage=False,
            )
        return results

    def _record(
        self,
        *,
        system: str,
        user: str,
        response_format: Any,
        started: float,
        status: str,
        error: str | None,
        kwargs: dict[str, Any],
        include_last_usage: bool = True,
    ) -> None:
        latency_ms = (time.perf_counter() - started) * 1000
        event = LLMCallTraceEvent.from_llm_call(
            node=str(kwargs.pop("trace_node", self._node) or self._node),
            agent=str(kwargs.pop("trace_agent", self._agent) or self._agent),
            system=system,
            user=user,
            response_format=response_format,
            model=self.model,
            latency_ms=latency_ms,
            status=status,
            error=error,
            prompt_version=str(kwargs.pop("prompt_version", self._prompt_version) or self._prompt_version or ""),
            repair_attempts=int(kwargs.pop("repair_attempts", 0) or 0),
            tokens=self._token_usage_snapshot() if include_last_usage and status == "success" else None,
            metadata={
                "finish_reason": getattr(self._inner, "_last_finish_reason", None)
                if include_last_usage and status == "success"
                else None,
                "batch": not include_last_usage,
            },
        )
        self._recorder.append(event)

    def _token_usage_snapshot(self) -> TokenUsage | None:
        """Read token usage from clients that expose provider usage on the last call."""
        usage = getattr(self._inner, "_last_token_usage", None)
        if usage is None:
            return None
        if isinstance(usage, TokenUsage):
            return usage
        if isinstance(usage, dict):
            return TokenUsage.model_validate(usage)
        return TokenUsage(
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
            total_tokens=getattr(usage, "total_tokens", None),
        )
