"""Базовые перечисления для проекта."""

from typing import Literal

Language = Literal["ru", "en", "kg", "uz"]
ProjectType = Literal["individual", "group"]
LLMProvider = Literal["gpt", "gigachat", "deepseek"]

