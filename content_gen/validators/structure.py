"""Валидатор структуры документа."""

import re
from dataclasses import dataclass

from ..config.thresholds import THRESHOLDS
from ..utils.text_analysis import count_words


@dataclass
class Issue:
    """Проблема валидации."""

    path: str
    level: str
    message: str


class IntroValidator:
    """Валидатор Главы 1 (Введение и инструкция)."""

    def __init__(self):
        self.rx_intro = re.compile(r"^###\s+Введение\s*(.+?)(?=^###\s+Инструкция|\Z)", re.S | re.M)
        self.rx_instr = re.compile(r"^###\s+Инструкция\s*(.+)$", re.S | re.M)

    def validate_markdown(self, md: str) -> list[Issue]:
        """
        Валидирует структуру Главы 1.

        Args:
            md: Markdown документ

        Returns:
            Список найденных проблем
        """
        issues: list[Issue] = []
        m_intro = self.rx_intro.search(md)
        m_instr = self.rx_instr.search(md)
        if not m_intro:
            issues.append(Issue("intro", "error", "Отсутствует секция «Введение»."))
            return issues
        if not m_instr:
            issues.append(Issue("instruction", "error", "Отсутствует секция «Инструкция»."))
            return issues

        intro = m_intro.group(1).strip()
        instr = m_instr.group(1).strip()

        lo, hi = THRESHOLDS["intro_words"]
        # Используем универсальную функцию подсчета слов (по умолчанию русский)
        words_intro = count_words(intro, "ru")
        if words_intro < lo or words_intro > hi:
            issues.append(
                Issue("intro.intro_text", "error", f"Длина введения {words_intro} слов вне диапазона {lo}–{hi}.")
            )

        intro_low = intro.lower()
        markers = ["используется для", "в реальной задаче", "применяется", "основная идея", "что решает", "зачем"]
        if not any(k in intro_low for k in markers):
            issues.append(
                Issue(
                    "intro.intro_text",
                    "warn",
                    "Во «Введении» нет маркеров контекста (зачем/что решает/применение).",
                )
            )

        instr_low = instr.lower()
        for req in ["допускается", "запрещено", "обязательно"]:
            if req not in instr_low:
                issues.append(Issue("intro.instruction_text", "error", f"В «Инструкции» отсутствует слово «{req}»."))

        return issues

