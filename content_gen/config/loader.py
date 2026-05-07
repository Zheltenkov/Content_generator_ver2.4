"""
content_gen/config/loader.py

Загрузчик конфигов агентов.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

CONTENT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = Path(__file__).resolve().parent
REPO_ROOT = CONFIG_ROOT.parents[1]


_prompt_cache: dict[Path, str] = {}
_agent_config_cache: dict[str, AgentConfig] = {}
_agent_versions: dict[str, str] = {}


class PromptSource(BaseModel):
    """Описывает источник промпта (inline текст или путь к файлу)."""

    type: Literal["inline", "file"] = "inline"
    value: str | None = None
    path: str | None = None

    def load(self) -> str:
        if self.type == "inline":
            if self.value is None:
                raise ValueError("Для inline промпта требуется поле 'value'")
            return self.value

        if self.type == "file":
            if not self.path:
                raise ValueError("Для file промпта требуется поле 'path'")
            prompt_path = (REPO_ROOT / self.path).resolve()
            if prompt_path not in _prompt_cache:
                _prompt_cache[prompt_path] = prompt_path.read_text(encoding="utf-8")
            return _prompt_cache[prompt_path]

        raise ValueError(f"Неизвестный тип промпта: {self.type}")


class LLMConfig(BaseModel):
    """Параметры LLM вызова."""

    temperature: float | None = None
    max_tokens: int | None = Field(default=None, alias="max_tokens")
    top_p: float | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None

    def to_kwargs(self, **overrides: Any) -> dict[str, Any]:
        data = {
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "presence_penalty": self.presence_penalty,
            "frequency_penalty": self.frequency_penalty,
        }
        data.update({k: v for k, v in overrides.items() if v is not None})
        return {k: v for k, v in data.items() if v is not None}


class AgentConfig(BaseModel):
    """Конфиг агента."""

    name: str
    version: str
    updated_at: str | None = None
    llm: LLMConfig | None = None
    prompts: dict[str, PromptSource] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)

    def get_prompt(self, key: str) -> str:
        if key not in self.prompts:
            raise KeyError(f"Промпт '{key}' не найден в конфиге агента {self.name}")
        return self.prompts[key].load()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def get_agent_config(agent_name: str) -> AgentConfig:
    """Возвращает конфиг агента."""
    if agent_name not in _agent_config_cache:
        cfg_path = CONFIG_ROOT / "agents" / f"{agent_name}.yaml"
        data = _load_yaml(cfg_path)
        data["name"] = agent_name
        config = AgentConfig(**data)
        _agent_config_cache[agent_name] = config
        _agent_versions[agent_name] = config.version
    return _agent_config_cache[agent_name]


def get_loaded_agent_versions() -> dict[str, str]:
    """Возвращает версии уже загруженных агентских конфигов."""
    return dict(_agent_versions)
