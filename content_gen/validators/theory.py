"""Валидатор теоретического раздела."""

import re
from dataclasses import dataclass

from ..config.thresholds import THRESHOLDS
from ..didactics.patterns import THEORY_PART_SPLIT_PATTERN, THEORY_PART_TITLE_PATTERN
from ..utils.text_analysis import count_words


@dataclass
class Issue:
    """Проблема валидации."""

    path: str
    level: str
    message: str


class TheoryValidator:
    """Валидатор Главы 2 (Теория)."""

    def __init__(self):
        pass

    def validate_markdown(self, md: str) -> list[Issue]:
        """
        Валидирует структуру Главы 2.

        Args:
            md: Markdown документ

        Returns:
            Список найденных проблем
        """
        issues: list[Issue] = []
        n_parts = len(re.findall(THEORY_PART_TITLE_PATTERN, md, flags=re.M))
        lo, hi = THRESHOLDS["theory_parts"]
        if n_parts < lo or n_parts > hi:
            issues.append(Issue("theory", "error", f"Количество частей теории {n_parts} вне диапазона {lo}–{hi}."))

        part_blocks = re.split(THEORY_PART_SPLIT_PATTERN, md, flags=re.M)
        for i, blk in enumerate([b for b in part_blocks if b.strip()]):
            main = blk.split("**Пример:**", 1)[0]
            # Используем универсальную функцию подсчета слов (по умолчанию русский)
            words = count_words(main, "ru")
            plo, phi = THRESHOLDS["theory_words_per_part"]
            if words < plo or words > phi:
                issues.append(
                    Issue(
                        f"theory.parts[{i}].body",
                        "error",
                        f"Длина части {i+1} = {words} слов (ожидалось {plo}–{phi}).",
                    )
                )
            if "**Пример:**" not in blk:
                issues.append(Issue(f"theory.parts[{i}].example", "error", "Нет блока **Пример:**"))
            if "**Вопросы к практике:**" not in blk:
                issues.append(
                    Issue(f"theory.parts[{i}].bridge_questions", "error", "Нет блока **Вопросы к практике:**")
                )
            if "[LO: нет прямого покрытия]" in blk:
                issues.append(
                    Issue(f"theory.parts[{i}].covers_outcomes", "warn", "Часть не покрывает ни один LO по смыслу.")
                )
        return issues
