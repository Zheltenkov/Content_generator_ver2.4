"""Tests for shared didactics regex patterns."""

from content_gen.didactics.patterns import (
    compile_practice_task_parse_legacy,
    compile_practice_task_title,
    compile_theory_part_title,
)


def test_theory_title_pattern_supports_both_formats():
    rx = compile_theory_part_title()
    text = "### 2.1. Основы\n\nТекст\n\n### Часть 2. Практика\n\nТекст"
    matches = rx.findall(text)
    assert len(matches) == 2


def test_practice_title_strict_contract():
    strict_rx = compile_practice_task_title(strict=True)
    assert strict_rx.search("### Задание 1. Настройка среды")
    assert not strict_rx.search("### Задача 1. Настройка среды")


def test_practice_legacy_parse_supports_zadacha_and_zadanie():
    rx = compile_practice_task_parse_legacy()
    m1 = rx.search("### Задание 3. ETL пайплайн")
    m2 = rx.search("### Задача 4. ETL пайплайн")
    assert m1 and m1.group(1) == "3"
    assert m2 and m2.group(1) == "4"
