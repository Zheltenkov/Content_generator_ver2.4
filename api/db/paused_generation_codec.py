"""Serialization helpers for durable paused generation sessions."""

from __future__ import annotations

import base64
import importlib
from dataclasses import asdict, is_dataclass
from typing import Any

from pydantic import BaseModel

from content_gen.agents.flow import FlowExecutionStep

_TYPE_KEY = "__paused_type__"
_DATA_KEY = "data"


def serialize_value(value: Any) -> Any:
    """Serialize known runtime values into JSON-compatible structures."""
    if isinstance(value, BaseModel):
        return {
            _TYPE_KEY: f"{value.__class__.__module__}:{value.__class__.__qualname__}",
            _DATA_KEY: serialize_value(value.model_dump(mode="json")),
        }
    if isinstance(value, bytes):
        return {
            _TYPE_KEY: "builtins:bytes",
            _DATA_KEY: base64.b64encode(value).decode("ascii"),
        }
    if isinstance(value, FlowExecutionStep):
        return {
            _TYPE_KEY: "content_gen.agents.flow:FlowExecutionStep",
            _DATA_KEY: value.as_dict(0) | {"step_index": None},
        }
    if is_dataclass(value):
        return serialize_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_value(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def hydrate_value(value: Any) -> Any:
    """Hydrate JSON-compatible paused state back into allowed runtime objects."""
    if isinstance(value, list):
        return [hydrate_value(item) for item in value]
    if not isinstance(value, dict):
        return value

    type_name = value.get(_TYPE_KEY)
    if not type_name:
        return {key: hydrate_value(item) for key, item in value.items()}

    data = hydrate_value(value.get(_DATA_KEY))
    if type_name == "builtins:bytes":
        return base64.b64decode(str(value.get(_DATA_KEY) or ""))
    if type_name == "content_gen.agents.flow:FlowExecutionStep":
        payload = dict(data)
        payload.pop("step_index", None)
        return FlowExecutionStep(**payload)

    model_cls = _resolve_pydantic_model(type_name)
    if model_cls is None:
        return data
    return model_cls.model_validate(data)


def serialize_context(context: dict[str, Any]) -> dict[str, Any]:
    """Serialize mutable flow context for durable pause/resume."""
    return serialize_value(context)


def hydrate_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Hydrate a mutable flow context and restore its state pointer."""
    context = hydrate_value(payload)
    state = context.get("state") if isinstance(context, dict) else None
    if hasattr(state, "sync_from_context"):
        state.sync_from_context(context)
    return context


def serialize_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """Serialize FlowExecutionStep values for DB storage."""
    serialized: list[dict[str, Any]] = []
    for step in steps or []:
        if isinstance(step, FlowExecutionStep):
            serialized.append(step.as_dict(len(serialized)))
        elif isinstance(step, dict):
            serialized.append(dict(step))
    return serialized


def hydrate_steps(payload: list[dict[str, Any]] | None) -> list[FlowExecutionStep]:
    """Hydrate DB step payload into FlowExecutionStep values."""
    steps: list[FlowExecutionStep] = []
    for item in payload or []:
        data = dict(item)
        data.pop("step_index", None)
        steps.append(FlowExecutionStep(**data))
    return steps


def _resolve_pydantic_model(type_name: str) -> type[BaseModel] | None:
    """Resolve a content_gen Pydantic model from a stored type name."""
    module_name, _, qualname = type_name.partition(":")
    if not module_name.startswith("content_gen."):
        return None
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return None

    obj: Any = module
    for part in qualname.split("."):
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    if isinstance(obj, type) and issubclass(obj, BaseModel):
        return obj
    return None
