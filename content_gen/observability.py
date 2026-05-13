"""Typed observability contracts for LLM and generation node calls."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def stable_input_hash(payload: Any) -> str:
    """Return a deterministic short hash for JSON-like node input payloads."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class TokenUsage(BaseModel):
    """Provider-neutral token usage snapshot."""

    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class ValidationTrace(BaseModel):
    """Validation outcome attached to a node or LLM call."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_run", "passed", "warning", "failed"] = "not_run"
    issues_count: int = 0
    issues: list[str] = Field(default_factory=list)


class NodeTraceEvent(BaseModel):
    """Minimal reproducible trace for one generation node execution."""

    model_config = ConfigDict(extra="forbid")

    node: str
    input_hash: str
    prompt_version: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    tokens: TokenUsage | None = None
    validation: ValidationTrace = Field(default_factory=ValidationTrace)
    repair_attempts: int = 0
    output_schema: str | None = None
    status: str = "success"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_node_execution(
        cls,
        *,
        node: str,
        inputs: Any,
        latency_ms: float | None,
        status: str,
        issues: list[str] | None = None,
        prompt_version: str | None = None,
        model: str | None = None,
        repair_attempts: int = 0,
        output_schema: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "NodeTraceEvent":
        """Build a trace event from runtime execution data."""
        issue_list = [str(issue) for issue in issues or [] if str(issue)]
        if status == "error":
            validation_status = "failed"
        elif issue_list:
            validation_status = "warning"
        else:
            validation_status = "passed"
        return cls(
            node=node,
            input_hash=stable_input_hash(inputs),
            prompt_version=prompt_version,
            model=model,
            latency_ms=latency_ms,
            validation=ValidationTrace(
                status=validation_status,
                issues_count=len(issue_list),
                issues=issue_list,
            ),
            repair_attempts=max(0, int(repair_attempts or 0)),
            output_schema=output_schema,
            status=status,
            metadata=metadata or {},
        )


class FallbackTraceEvent(BaseModel):
    """Machine-readable trace for deterministic degradation paths."""

    model_config = ConfigDict(extra="forbid")

    node: str
    fallback_type: str
    reason: str
    quality_risk: Literal["none", "low", "medium", "high"] = "low"
    input_hash: str | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_fallback(
        cls,
        *,
        node: str,
        fallback_type: str,
        reason: str,
        quality_risk: Literal["none", "low", "medium", "high"] = "low",
        inputs: Any | None = None,
        trace: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "FallbackTraceEvent":
        """Build a fallback trace with optional deterministic input hashing."""
        return cls(
            node=node,
            fallback_type=fallback_type,
            reason=str(reason),
            quality_risk=quality_risk,
            input_hash=stable_input_hash(inputs) if inputs is not None else None,
            trace=trace or {},
            metadata=metadata or {},
        )


class CompatibilityEvent(BaseModel):
    """Machine-readable trace for intentional legacy compatibility behavior."""

    model_config = ConfigDict(extra="forbid")

    source: str
    compatibility_type: str
    reason: str
    risk: Literal["none", "low", "medium", "high"] = "low"
    metadata: dict[str, Any] = Field(default_factory=dict)


def record_runtime_fallback_traces(
    runtime: Any,
    events: Iterable[FallbackTraceEvent | dict[str, Any]] | None,
) -> None:
    """Append fallback events to a runtime object that exposes ``fallback_traces``."""
    normalized: list[dict[str, Any]] = []
    for event in events or []:
        if isinstance(event, FallbackTraceEvent):
            normalized.append(event.model_dump(mode="json"))
        elif isinstance(event, dict):
            normalized.append(event)
    if not normalized:
        return

    traces = getattr(runtime, "fallback_traces", None)
    if traces is None:
        runtime.fallback_traces = []
        traces = runtime.fallback_traces
    traces.extend(normalized)


class LLMCallTraceEvent(BaseModel):
    """Reproducible trace for one LLM invocation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    node: str
    agent: str
    input_hash: str
    prompt_version: str | None = None
    model: str | None = None
    latency_ms: float | None = None
    tokens: TokenUsage | None = None
    output_schema: str | None = Field(default=None, alias="schema")
    validation: ValidationTrace = Field(default_factory=ValidationTrace)
    repair_attempts: int = 0
    status: str = "success"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_llm_call(
        cls,
        *,
        node: str,
        agent: str,
        system: str,
        user: str,
        response_format: Any,
        model: str | None,
        latency_ms: float,
        status: str,
        error: str | None = None,
        tokens: TokenUsage | dict[str, Any] | None = None,
        prompt_version: str | None = None,
        repair_attempts: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> "LLMCallTraceEvent":
        """Build a trace event from an LLM complete call."""
        issues = [error] if error else []
        output_schema = None
        if isinstance(response_format, str):
            output_schema = response_format
        elif isinstance(response_format, dict):
            output_schema = str(
                response_format.get("json_schema", {}).get("name")
                or response_format.get("type")
                or "structured"
            )
        token_snapshot = tokens if isinstance(tokens, TokenUsage) else TokenUsage.model_validate(tokens) if tokens else None
        return cls(
            node=node,
            agent=agent,
            input_hash=stable_input_hash({"system": system, "user": user, "response_format": response_format}),
            prompt_version=prompt_version,
            model=model,
            latency_ms=latency_ms,
            tokens=token_snapshot,
            output_schema=output_schema,
            validation=ValidationTrace(
                status="failed" if error else "not_run",
                issues_count=len(issues),
                issues=issues,
            ),
            repair_attempts=max(0, int(repair_attempts or 0)),
            status=status,
            metadata=metadata or {},
        )


class LLMTraceRecorder:
    """In-memory trace sink for one generation run."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def append(self, event: LLMCallTraceEvent) -> None:
        """Append a JSON-safe event."""
        self.events.append(event.model_dump(mode="json", by_alias=True))
