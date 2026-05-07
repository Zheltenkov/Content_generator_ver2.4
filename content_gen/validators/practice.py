"""Валидатор практических задач."""

import re
from dataclasses import dataclass

from ..config.banned_phrases import BAD_GOAL_PATTERNS
from ..config.thresholds import THRESHOLDS
from ..didactics.patterns import PRACTICE_TASK_TITLE_PATTERN_LEGACY
from ..utils.text_analysis import count_words


@dataclass
class Issue:
    """Проблема валидации."""

    path: str
    level: str
    message: str


class PracticeValidator:
    """Валидатор Главы 3 (Практика)."""

    def __init__(self):
        pass

    def validate_markdown(self, md: str, language: str, tasks_count_expected: int | None) -> list[Issue]:
        """
        Валидирует структуру Главы 3.

        Args:
            md: Markdown документ
            language: Язык проекта
            tasks_count_expected: Ожидаемое количество задач

        Returns:
            Список найденных проблем
        """
        issues: list[Issue] = []

        n_tasks = len(re.findall(PRACTICE_TASK_TITLE_PATTERN_LEGACY, md, flags=re.M))
        lo_all, hi_all = THRESHOLDS["practice_tasks_range"]
        if tasks_count_expected is not None and n_tasks != tasks_count_expected:
            issues.append(
                Issue("practice.tasks", "warn", f"Сгенерировано {n_tasks} задач(и), ожидалось {tasks_count_expected}.")
            )
        if not (lo_all <= n_tasks <= hi_all):
            issues.append(
                Issue("practice.tasks", "error", f"Количество задач {n_tasks} вне допустимого диапазона {lo_all}–{hi_all}.")
            )

        task_blocks = re.split(r"(?=^###\s+(?:Задание|Задача)\s+\d+\.)", md, flags=re.M)
        for i, blk in enumerate([b for b in task_blocks if b.strip()]):
            canonical = _has_label(blk, "Что нужно сделать") and _has_label(blk, "Что должно получиться") and _has_label(blk, "Формат сдачи")
            legacy = all(_has_label(blk, label) for label in ["Входные данные", "Цель", "Подход", "Ожидаемый результат"])
            if not (canonical or legacy):
                for label in ["Что нужно сделать", "Что должно получиться", "Формат сдачи"]:
                    if not _has_label(blk, label):
                        issues.append(Issue(f"practice.tasks[{i}].{label}", "error", f"Отсутствует блок «{label}»."))

            m_ap = _extract_label_block(blk, "Подход") or _extract_label_block(blk, "Что нужно сделать")
            if m_ap:
                # Используем универсальную функцию подсчета слов
                words = count_words(m_ap, language)
                if words > THRESHOLDS["approach_words_max"]:
                    issues.append(
                        Issue(
                            f"practice.tasks[{i}].approach_bullets",
                            "error",
                            f"«Подход» содержит {words} слов (> {THRESHOLDS['approach_words_max']}).",
                        )
                    )

            goal = _extract_label_block(blk, "Цель") or _extract_goal_from_canonical(blk)
            if goal:
                for pat in BAD_GOAL_PATTERNS.get(language, []):
                    if re.search(pat, goal, flags=re.I):
                        issues.append(
                            Issue(
                                f"practice.tasks[{i}].goal",
                                "error",
                                "Цель сформулирована как «изучить/ознакомиться/посмотреть» — нужно действие+результат.",
                            )
                        )

            result = _extract_label_block(blk, "Ожидаемый результат") or _extract_label_block(blk, "Что должно получиться")
            if result:
                if "где найти" not in result.lower() and "repo/" not in result and "/" not in result:
                    issues.append(
                        Issue(
                            f"practice.tasks[{i}].expected_artifact",
                            "warn",
                            "Укажи, где найти артефакт (скобками или repo/… путь).",
                        )
                    )
        return issues


def _has_label(text: str, label: str) -> bool:
    return bool(re.search(rf"\*\*{re.escape(label)}:?\*\*", text, flags=re.I))


def _extract_label_block(text: str, label: str) -> str:
    match = re.search(rf"\*\*{re.escape(label)}:?\*\*\s*(.+?)(?=\n\*\*|\n###|\Z)", text, flags=re.S | re.I)
    return match.group(1).strip() if match else ""


def _extract_goal_from_canonical(text: str) -> str:
    action = _extract_label_block(text, "Что нужно сделать")
    match = re.search(r"(?:^|\n)\s*Цель:\s*(.+?)(?=\n\s*(?:Подход:|Исходные данные:)|\Z)", action, flags=re.S | re.I)
    return match.group(1).strip() if match else action[:300]
