"""Базовые перечисления для проекта."""

from typing import Literal

Language = Literal["ru", "en", "kg", "uz"]
ProjectType = Literal["individual", "group"]
LLMProvider = Literal["openrouter", "openai", "gpt", "azure", "deepseek", "gigachat"]

