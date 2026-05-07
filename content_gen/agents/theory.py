"""
content_gen/agents/theory.py

Агент генерации теоретического раздела.

Генерирует Главу 2 (Теория) с частями, примерами и вопросами к практике.
Интегрируется с TheoryEnhancementManager для добавления формул, таблиц и диаграмм.
"""

import logging
import re
import sys
from dataclasses import dataclass
from typing import Any

from ..config.loader import get_agent_config
from ..config.thresholds import THRESHOLDS
from ..didactics.composer import compose_didactics_context
from ..domain_contracts import SectionContextPolicy, render_narrative_contract_section
from ..models.schemas import ProjectContextMeta, ProjectSeed, TheoryPart
from ..project_planning import render_practice_plan_contract_section
from ..utils.markdown_display_normalizer import normalize_markdown_display_blocks
from ..utils.text_analysis import count_prose_words, count_words
from .base.agent import BaseAgent
from .base.llm_client import LLMClientProtocol
from .style_guard import StyleGuardAgent

SYSTEM = ""

USER_TMPL = ""


def _split_sentences(text: str) -> list[str]:
    """Split text into sentence-like units."""
    chunks = re.split(r"(?<=[\.\!\?])\s+", (text or "").strip())
    return [chunk.strip() for chunk in chunks if chunk and chunk.strip()]


def _compact_sentences(sentences: list[str]) -> str:
    """Build short paragraphs from a compact list of sentences."""
    if not sentences:
        return ""
    first = " ".join(sentences[:2]).strip()
    second = " ".join(sentences[2:4]).strip()
    if second:
        return f"{first}\n\n{second}".strip()
    return first


_FENCED_BLOCK_RX = re.compile(r"```[\s\S]*?```", re.M)
_TABLE_BLOCK_RX = re.compile(
    r"(^\|[^\n]+\|\s*\n\|[-:\s|]+\|\s*\n(?:\|[^\n]+\|\s*(?:\n|$))+)",
    re.M,
)


def _normalize_inline_markdown_tables(text: str) -> str:
    """Recover markdown tables that were flattened into a single line."""
    normalized_lines: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.rstrip()
        if stripped.count("|") < 6 or not re.search(r"\|\s+(?=\|)", stripped):
            normalized_lines.append(line)
            continue

        repaired = re.sub(r"\|\s+(?=\|)", "|\n", stripped)
        if "\n|" not in repaired:
            normalized_lines.append(line)
            continue

        first_pipe = repaired.find("|")
        prefix = repaired[:first_pipe].rstrip()
        table = repaired[first_pipe:].strip()
        if prefix:
            normalized_lines.append(prefix)
            normalized_lines.append("")
        normalized_lines.extend(table.splitlines())
    return "\n".join(normalized_lines)


def _protect_markdown_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Protect tables and fenced blocks from prose compaction."""
    protected: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        key = f"@@THEORY_BLOCK_{len(protected)}@@"
        protected[key] = match.group(0).strip("\n")
        return f"\n\n{key}\n\n"

    stage = _FENCED_BLOCK_RX.sub(repl, text or "")
    stage = _TABLE_BLOCK_RX.sub(repl, stage)
    return stage, protected


def _restore_markdown_blocks(text: str, blocks: dict[str, str]) -> str:
    """Restore protected markdown blocks with stable blank lines around them."""
    restored = text or ""
    for key, block in blocks.items():
        restored = restored.replace(key, block)
    restored = re.sub(r"\n{3,}", "\n\n", restored)
    return restored.strip()


def _sanitize_theory_prose_chunk(text: str, title: str, seed: ProjectSeed, anchors: list[str], hi: int) -> str:
    """Sanitize only prose fragments, without touching preserved markdown blocks."""
    compact_source = re.sub(r"[ \t]+", " ", (text or "").strip())
    compact_source = re.sub(r"\n{3,}", "\n\n", compact_source)
    if not compact_source:
        return ""

    generic_leads = [
        r"^теперь, когда\b",
        r"^исходя из\b",
        r"^вдобавок\b",
        r"^также стоит\b",
        r"^в конечном итоге\b",
        r"^облачные услуги связаны\b",
        r"^исходя из значимости\b",
        r"^выбор технологий\b.*\bявляется\b",
    ]
    generic_fillers = [
        r"\bстанет важным вкладом\b",
        r"\bзначительно расширит\b",
        r"\bв современном мире\b",
        r"\bв различных сферах it\b",
        r"\bкрайне важно\b",
    ]

    sentences = _split_sentences(compact_source)
    filtered: list[str] = []
    definition_count = 0

    for sentence in sentences:
        low = sentence.lower()
        if any(re.search(pattern, low, flags=re.I) for pattern in generic_leads):
            continue
        if any(re.search(pattern, low, flags=re.I) for pattern in generic_fillers):
            continue

        if "— это" in low or " - это" in low:
            definition_count += 1
            if definition_count > 1 and not any(anchor in low for anchor in anchors[:8]):
                continue

        filtered.append(sentence.strip())

    if len(filtered) < 2:
        filtered = sentences[:4]

    filtered = filtered[:4]
    compact = _compact_sentences(filtered)

    anchor_hit = any(anchor in compact.lower() for anchor in anchors[:10]) if anchors else False
    if not anchor_hit:
        project_hint = re.sub(r"\s+", " ", (seed.project_description or "").strip()).rstrip(".")
        if project_hint:
            compact = (
                compact.rstrip()
                + f" Для этого проекта важно понять {title.lower()}, потому что от этого зависит {project_hint[:140].lower()}."
            ).strip()

    words = count_words(compact, seed.language)
    if words > hi:
        kept: list[str] = []
        for sentence in _split_sentences(compact):
            candidate = _compact_sentences(kept + [sentence])
            if kept and count_words(candidate, seed.language) > hi:
                break
            kept.append(sentence)
        if kept:
            compact = _compact_sentences(kept)

    return compact.strip()


def _normalize_definition_bold(text: str) -> str:
    """Add bold markdown to terms in definitions when the term is still plain text."""
    body = text or ""
    if not body:
        return body

    term_expr = r"[A-ZА-ЯЁ][A-Za-zА-Яа-яЁё0-9]*(?:[ /-][A-Za-zА-Яа-яЁё0-9]+){0,8}"

    def _wrap_term(match: re.Match[str]) -> str:
        prefix = match.group("prefix") or ""
        term = (match.group("term") or "").strip()
        glue = match.group("glue") or ""
        if not term or term.startswith("**") or term.endswith("**"):
            return match.group(0)
        return f"{prefix}**{term}**{glue}"

    simple_patterns = [
        re.compile(
            rf"(?P<prefix>(?:^|[.!?\n]\s*))(?!\*\*)(?P<term>{term_expr})(?P<glue>\s*[—-]\s*это\b)",
            re.IGNORECASE,
        ),
        re.compile(
            rf"(?P<prefix>(?:^|[.!?\n]\s*))(?!\*\*)(?P<term>{term_expr})(?P<glue>\s+(?:представляет собой|является)\b)",
            re.IGNORECASE,
        ),
    ]

    normalized = body
    for pattern in simple_patterns:
        normalized = pattern.sub(_wrap_term, normalized)

    normalized = re.sub(
        rf"Под\s+(?!\*\*)({term_expr})\s+(понима(?:ют|ется|ются|ет)?|подразумевается)\b",
        lambda match: f"Под **{match.group(1).strip()}** {match.group(2)}",
        normalized,
        flags=re.IGNORECASE,
    )
    return normalized


def _build_theory_padding_sentences(title: str, seed: ProjectSeed, anchors: list[str]) -> list[str]:
    """Build short deterministic sentences to bring compact theory up to the minimal threshold."""
    title_low = (title or "этот блок").strip().lower()
    description = re.sub(r"\s+", " ", (seed.project_description or "").strip()).strip(". ")
    outcome = ""
    if seed.learning_outcomes:
        outcome = re.sub(r"\s+", " ", seed.learning_outcomes[0]).strip().strip(".")
    unique_anchors = list(dict.fromkeys([a for a in anchors if len(a) > 3]))
    anchor_text = ", ".join(unique_anchors[:3])

    sentences: list[str] = [
        f"В практике тебе важно не просто назвать {title_low}, а связать это решение с ограничениями проекта, доступными ресурсами и ожидаемым результатом.",
        "Сначала зафиксируй критерии выбора, затем проверь ограничения и последствия решения, и только после этого переходи к конкретным действиям или артефактам.",
    ]
    if outcome:
        sentences.append(f"Это напрямую помогает выйти на результат обучения: {outcome}.")
    if description:
        sentences.append(f"Ориентируйся на контекст проекта: {description[:180]}.")
    elif anchor_text:
        sentences.append(f"Держи в фокусе ключевые опоры этого проекта: {anchor_text}.")
    return sentences


def _sanitize_theory_body_text(body: str, title: str, seed: ProjectSeed, anchors: list[str], lo: int, hi: int) -> str:
    """Make theory less lecture-like and closer to didactics."""
    text = normalize_markdown_display_blocks((body or "").strip())
    text = _normalize_inline_markdown_tables(text)
    if not text:
        return text

    protected_text, blocks = _protect_markdown_blocks(text)
    parts = re.split(r"(@@THEORY_BLOCK_\d+@@)", protected_text)
    sanitized_parts: list[str] = []
    for chunk in parts:
        if not chunk:
            continue
        if chunk in blocks:
            sanitized_parts.append(chunk)
            continue
        sanitized = _sanitize_theory_prose_chunk(chunk, title, seed, anchors, hi)
        if sanitized:
            sanitized_parts.append(_normalize_definition_bold(sanitized))

    compact = "\n\n".join(part for part in sanitized_parts if part.strip()).strip()
    compact = _restore_markdown_blocks(compact, blocks)

    current_words = count_prose_words(compact, seed.language)
    if current_words < lo:
        additions: list[str] = []
        padding_pool = _build_theory_padding_sentences(title, seed, anchors)
        while padding_pool and count_prose_words((compact + " " + " ".join(additions)).strip(), seed.language) < lo:
            reached_target = False
            for sentence in padding_pool:
                candidate = (compact + " " + " ".join(additions + [sentence])).strip()
                if count_prose_words(candidate, seed.language) > hi:
                    reached_target = True
                    break
                additions.append(sentence)
                if count_prose_words(candidate, seed.language) >= lo:
                    reached_target = True
                    break
            if reached_target:
                break
        if additions:
            compact = (compact + "\n\n" + " ".join(additions)).strip()

    compact = _normalize_definition_bold(compact)
    compact = normalize_markdown_display_blocks(compact)

    return compact.strip()


def _sanitize_theory_example_text(example: str) -> str:
    """Keep examples concrete and concise."""
    sentences = _split_sentences(re.sub(r"\s+", " ", (example or "").strip()))
    return " ".join(sentences[:3]).strip()


@dataclass
class TheoryResult:
    """Результат генерации теории."""

    parts: list[TheoryPart]


class TheoryAgent(BaseAgent):
    """Генерирует теоретический раздел проекта."""

    CONFIG_NAME = "theory"

    def __init__(self, llm: LLMClientProtocol):
        super().__init__(llm)
        self.logger = logging.getLogger("content_gen.agents.theory")
        self.style = StyleGuardAgent()
        # Поддерживаем оба формата: "2.1. название" и "Часть 1. название" (для обратной совместимости)
        self.rx_part = re.compile(r"^###\s+(?:2\.(\d+)|Часть\s+(\d+))\.\s*(.+?)\s*$", re.M)
        self.rx_example = re.compile(r"\*\*Пример:\*\*\s*(.+)")
        self.rx_qs = re.compile(r"\*\*Вопросы к практике:\*\*([\s\S]+?)(?=\n###|\Z)", re.M)
        self.config = get_agent_config(self.CONFIG_NAME)
        self.llm_kwargs = self.config.llm.to_kwargs() if self.config.llm else {}
        try:
            self.didactics_context, self.didactics_trace = compose_didactics_context(self.CONFIG_NAME)
        except Exception:
            self.didactics_context, self.didactics_trace = "", {}

    def _pick_n_parts(self, desired: int) -> int:
        """Выбирает количество частей в допустимом диапазоне."""
        lo, hi = THRESHOLDS["theory_parts"]
        if desired < lo:
            return lo
        if desired > hi:
            return hi
        return desired


    def _semantic_cover(self, body: str, los: list[str]) -> list[str]:
        """Определяет покрытие LO по смыслу."""
        covered = []
        body_low = body.lower()
        for lo_txt in los:
            if any(tok in body_low for tok in re.findall(r"\w+", lo_txt.lower())):
                covered.append(lo_txt)
        return list(dict.fromkeys(covered))[:4]

    def _anchor_terms(self, seed: ProjectSeed) -> list[str]:
        """Собирает якорные термины из описания проекта и входных данных."""
        terms = set()
        for item in (seed.required_tools or []):
            if item:
                terms.add(item.lower())
        for item in (seed.skills or []):
            if item:
                terms.add(item.lower())
        for item in (seed.learning_outcomes or []):
            if item:
                terms.update(re.findall(r"\w+", item.lower()))
        if seed.project_description:
            terms.update(w for w in re.findall(r"\w+", seed.project_description.lower()) if len(w) > 4)
        # фильтруем короткие
        return [t for t in terms if len(t) >= 4]

    def polish_part(self, part: TheoryPart, seed: ProjectSeed) -> TheoryPart:
        """Локально выравнивает теорию под didactics после любой генерации/редактуры."""
        lo, hi = THRESHOLDS["theory_words_per_part"]
        anchors = self._anchor_terms(seed)
        part.body = _sanitize_theory_body_text(part.body, part.title, seed, anchors, lo, hi)
        part.example = _sanitize_theory_example_text(self.style.rewrite(part.example or "", seed.language))
        part.bridge_questions = [question.strip() for question in (part.bridge_questions or []) if question and question.strip()][:2]
        return part

    def _validate_questions(self, questions: list[str], seed: ProjectSeed) -> bool:
        """Проверяет качество вопросов: конкретность, связь с проектом, сложность."""
        if not questions:
            return False
        bad_starts = ("что такое", "перечисли", "объясни", "расскажи", "определи")
        anchors = self._anchor_terms(seed)
        has_anchor = False
        for q in questions:
            q_low = q.strip().lower()
            if len(q_low) < 25 or len(q_low) > 180:
                return False
            if q_low.startswith(bad_starts):
                return False
            if anchors and any(a in q_low for a in anchors):
                has_anchor = True
        if anchors and not has_anchor:
            return False
        return True

    def _build_questions_prompt(self, part_data: dict, seed: ProjectSeed) -> str:
        return f"""Для части теории нужно сгенерировать вопросы к практике.

Название части: {part_data['title']}
Основной текст части:
{part_data['main_body'][:600]}...

Контекст проекта:
- Описание: {seed.project_description}
- Инструменты: {', '.join(seed.required_tools) or '—'}
- Навыки: {', '.join(seed.skills) or '—'}
- Результаты обучения: {', '.join(seed.learning_outcomes) or '—'}

Сгенерируй 1-2 вопроса, которые:
- привязаны к проекту (упоминают инструмент/артефакт/результат)
- средней сложности (без долгого ресерча)
- не являются пересказом теории
- формулируются простым языком

Формат вывода (строго):
**Вопросы к практике:**
- <вопрос 1>
- <вопрос 2 (опционально)>
"""

    def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """
        Обрабатывает входные данные (реализация BaseAgent).
        
        Args:
            input_data: Словарь с ключами 'seed' (ProjectSeed), 'context' (ProjectContextMeta), 'desired_parts' (int, опционально)
            
        Returns:
            Словарь с результатами генерации
        """
        seed = input_data.get('seed')
        context_meta = input_data.get('context')
        desired_parts = input_data.get('desired_parts', 3)
        if not isinstance(seed, ProjectSeed):
            raise ValueError("input_data должен содержать 'seed' типа ProjectSeed")
        if not isinstance(context_meta, ProjectContextMeta):
            raise ValueError("input_data должен содержать 'context' типа ProjectContextMeta")
        kwargs: dict[str, Any] = {}
        for key in ("practice_plan_contract", "section_context"):
            if key in input_data:
                kwargs[key] = input_data[key]
        result = self.generate(seed, context_meta, desired_parts, **kwargs)
        return {
            'result': result,
            'parts': result.parts,
        }

    def _build_curriculum_context_section(
        self,
        seed: ProjectSeed,
        section_context: dict[str, Any] | None = None,
    ) -> str:
        """Строит секцию контекста из УП для промпта."""
        ctx = (section_context or {}).get("curriculum_context")
        if not isinstance(ctx, dict):
            ctx = getattr(seed, 'curriculum_context', None)
        if not ctx:
            return "Контекст из учебного плана не предоставлен."

        lines = []
        narrative_payload = (section_context or {}).get("narrative_contract") or ctx.get("narrative_contract")
        narrative_contract_section = render_narrative_contract_section(narrative_payload)
        if narrative_contract_section:
            lines.append(narrative_contract_section)
            lines.append("")

        # Информация о блоке
        if ctx.get('block_name'):
            lines.append(f"Тематический блок УП: {ctx['block_name']}")

        if ctx.get('block_goals'):
            goals = ctx['block_goals']
            if isinstance(goals, list):
                lines.append(f"Цели блока: {'; '.join(goals)}")

        if ctx.get('current_project_order'):
            lines.append(f"Номер проекта в блоке: {ctx['current_project_order']}")

        # Краткое описание текущего проекта (из УП) — ориентируй теорию на эту тематику
        if ctx.get('current_project_description'):
            lines.append(f"Краткое описание проекта (из УП): {ctx['current_project_description']}")

        # Список навыков текущего проекта — теория должна давать базу для этих навыков
        if ctx.get('current_project_skills'):
            skills = ctx['current_project_skills']
            if isinstance(skills, list):
                lines.append(f"Список навыков проекта: {'; '.join(skills)}")

        # Предыдущие проекты (что студент уже изучил)
        prev_projects = ctx.get('previous_projects', [])
        if prev_projects:
            lines.append("")
            lines.append("ПРЕДЫДУЩИЕ ПРОЕКТЫ В БЛОКЕ (что студент уже изучил):")
            for p in prev_projects[-3:]:  # Последние 3
                lo_str = '; '.join(p.get('learning_outcomes', [])[:3])
                lines.append(f"  - Проект {p.get('order')}: <<{p.get('title')}>>")
                if lo_str:
                    lines.append(f"    LO: {lo_str}")
            lines.append("НЕ ПОВТОРЯЙ материал из предыдущих проектов! Ссылайся на него как на уже известное.")

        # Следующие проекты (границы - НЕ ЗАБЕГАТЬ ВПЕРЁД!)
        next_projects = ctx.get('next_projects', [])
        if next_projects:
            lines.append("")
            lines.append("СЛЕДУЮЩИЕ ПРОЕКТЫ В БЛОКЕ (ГРАНИЦЫ - НЕ ТРОГАТЬ ЭТИ ТЕМЫ!):")
            for p in next_projects[:2]:  # Первые 2
                # Показываем только название, БЕЗ LO (чтобы не провоцировать утечку)
                lines.append(f"  - Проект {p.get('order')}: <<{p.get('title')}>>")
            lines.append("")
            lines.append("КРИТИЧЕСКИ ВАЖНО:")
            lines.append("НЕ вводи термины и концепции из следующих проектов!")
            lines.append("Теория ТОЛЬКО по темам ТЕКУЩЕГО проекта (см. LO и описание выше).")
            lines.append("Если концепция относится к следующему проекту — НЕ объясняй её!")

        # Кросс-блочные связи
        prev_block_projects = ctx.get('previous_block_projects', [])
        if prev_block_projects:
            lines.append("")
            lines.append("ПОСЛЕДНИЕ ПРОЕКТЫ ПРЕДЫДУЩЕГО БЛОКА (для связности):")
            for p in prev_block_projects[-2:]:
                lines.append(f"  - <<{p.get('title')}>> (блок: {p.get('block_name', 'предыдущий')})")

        return "\n".join(lines) if lines else "Контекст из учебного плана не предоставлен."

    def _build_sjm_section(
        self,
        seed: ProjectSeed,
        section_context: dict[str, Any] | None = None,
    ) -> str:
        """Строит секцию сторителлинга/кейса для промпта."""
        sjm = (section_context or {}).get("sjm_context") or getattr(seed, 'sjm', None)
        ctx = (section_context or {}).get("curriculum_context")
        if not isinstance(ctx, dict):
            ctx = getattr(seed, 'curriculum_context', None)

        # Пробуем взять SJM из контекста, если не задан напрямую
        if not sjm and ctx:
            sjm = ctx.get('sjm_context')

        if not sjm:
            return (
                "Сторителлинг/кейс не предоставлен. "
                "Сгенерируй минимальный рабочий контекст по описанию проекта (роль, ситуация, 2–4 предложения) и вплети его в основной текст. "
                "Избегай сухого перечисления «по полочкам» — тон живой, вовлекающий."
            )

        lines = [
            "Если в контексте передан SJM (кейс/история) — вплетай его в основной текст теории и вопросы к практике.",
            "Блок **Пример:** оставляй как внешний реальный кейс компаний/продуктов, не подменяй его SJM-сюжетом проекта.",
            "В каждом внешнем примере покажи не только проблему, но и решение/управленческое действие, которое связано с темой текущей части.",
            "После внешнего примера верни фокус к SJM: роли, заказчику, ограничениям, продукту или артефакту текущего проекта.",
            "",
            sjm,
            "",
            "Привязывай теорию и вопросы к практике к этому кейсу. Тон: живой, вовлекающий; избегай сухого перечисления без контекста."
        ]
        return "\n".join(lines)

    def _determine_content_type(self, seed: ProjectSeed) -> str:
        """
        Определяет тип контента на основе направления.
        
        Returns:
            'hard_code' | 'low_code' | 'no_code'
        """
        direction = (getattr(seed, 'direction', '') or seed.thematic_block or "").upper()

        # Hard code: Разработчик ПО, C/C++, Java, Python backend
        hard_code_directions = {
            'C', 'CPP', 'C++', 'JAVA', 'GO', 'RUST', 'BACKEND', 'MOBILE',
            'WEB', 'FRONTEND', 'FULLSTACK', 'DEV', 'SWE'
        }

        # Low code: DS, DevOps, QA, Биоинформатика
        low_code_directions = {
            'DS', 'DO', 'QA', 'BIO', 'BIOINF', 'DEVOPS', 'DATA',
            'ML', 'AI', 'TESTING', 'AUTOMATION'
        }

        # No code: Project Manager, UX, Кибербез, BSA
        no_code_directions = {
            'PJM', 'UX', 'CB', 'KB', 'BSA', 'BA', 'PM', 'CYBER',
            'SECURITY', 'PRODUCT', 'DESIGN', 'MANAGEMENT', 'ANALYST'
        }

        if direction in hard_code_directions:
            return 'hard_code'
        elif direction in low_code_directions:
            return 'low_code'
        elif direction in no_code_directions:
            return 'no_code'
        else:
            # По умолчанию - low_code (средний вариант)
            return 'low_code'

    def _build_content_type_section(self, content_type: str) -> str:
        """Строит секцию типа контента для промпта."""

        if content_type == 'hard_code':
            return """ТИП: ТЕХНИЧЕСКИЙ (hard code)
Это проект для РАЗРАБОТЧИКОВ. Разрешено:
- Примеры кода (с комментариями)
- Формулы (с пояснениями)
- Технические диаграммы
- Алгоритмы и структуры данных
Тон: профессиональный, технический, но понятный."""

        elif content_type == 'low_code':
            return """ТИП: ТЕХНИЧЕСКИЙ С ОГРАНИЧЕНИЯМИ (low code)
Это проект для технических специалистов (DS, DevOps, QA). Разрешено:
- Минимум кода (1-2 коротких примера на весь раздел)
- Максимум 1-2 ПРОСТЫЕ формулы (только если критически нужны)
- Диаграммы и схемы
- Таблицы сравнения
ЗАПРЕЩЕНО: сложные формулы, много кода, глубокие технические детали.
Тон: объясняющий, с практическими примерами из жизни."""

        else:  # no_code
            return """ТИП: ГУМАНИТАРНЫЙ (no code)
Это проект для МЕНЕДЖЕРОВ, АНАЛИТИКОВ, ДИЗАЙНЕРОВ (PjM, BSA, UX, КБ).

СТРОГО ЗАПРЕЩЕНО:
- Любой код (даже псевдокод!)
- Любые формулы (даже простые типа P = Q/T!)
- Технические диаграммы с кодом

РАЗРЕШЕНО:
- Таблицы (сравнения, чек-листы, матрицы решений)
- Блок-схемы процессов (flowchart в mermaid, БЕЗ кода)
- Примеры из бизнеса и реальной жизни

ТОН: разговорный, с историями и кейсами.
Объясняй всё так, будто рассказываешь коллеге за чашкой кофе.
Используй аналогии из повседневной жизни."""

    def _build_formulas_requirements(self, seed: ProjectSeed, content_type: str) -> str:
        """Строит требования к формулам и коду."""

        if content_type == 'no_code':
            return """ФОРМУЛЫ И КОД: ПОЛНОСТЬЮ ЗАПРЕЩЕНЫ!
Даже если методолог указал include_formulas=True — НЕ ДОБАВЛЯЙ ФОРМУЛЫ.
Для этого направления (менеджмент/аналитика) формулы неуместны.
Если нужно показать расчёт — опиши словами или покажи таблицу с числами.

ВМЕСТО ФОРМУЛЫ:
- Плохо: $$P_{db} = \\frac{Q}{T}$$
- Хорошо: <<Производительность = количество задач / время. Например, если команда закрыла 20 задач за 5 дней, производительность = 4 задачи в день.>>"""

        elif content_type == 'low_code':
            if not seed.include_formulas:
                return """ФОРМУЛЫ: ЗАПРЕЩЕНЫ методологом.
КОД: Максимум 1-2 коротких примера (до 10 строк) за весь раздел.
Код должен быть КРИТИЧЕСКИ необходим для понимания."""
            else:
                return """ФОРМУЛЫ: Разрешены, но МАКСИМУМ 1-2 на весь раздел.
Каждая формула ОБЯЗАТЕЛЬНО должна иметь:
1. Пояснение ПЕРЕД формулой (зачем она нужна)
2. Расшифровку ВСЕХ переменных
3. Пример с КОНКРЕТНЫМИ числами

КОД: Максимум 1-2 коротких примера (до 10 строк)."""

        else:  # hard_code
            if not seed.include_formulas:
                return """ФОРМУЛЫ: ЗАПРЕЩЕНЫ методологом.
КОД: Разрешён. Используй примеры кода там, где они помогают понять концепцию.
Код должен быть с комментариями."""
            else:
                return """ФОРМУЛЫ: Разрешены там, где они РЕАЛЬНО помогают.
Каждая формула должна иметь расшифровку параметров и пример.
КОД: Разрешён и приветствуется. Код должен быть с комментариями."""

    def generate(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
        desired_parts: int = 3,
        practice_plan_contract: Any | None = None,
        section_context: dict[str, Any] | None = None,
    ) -> TheoryResult:
        """
        Генерирует теоретический раздел.

        Args:
            seed: Входные данные проекта
            context_meta: Метаданные curriculum context
            desired_parts: Желаемое количество частей

        Returns:
            TheoryResult с частями теории
        """
        n_parts = self._pick_n_parts(desired_parts)
        system_prompt = self.config.get_prompt("system").format(language=seed.language)
        if self.didactics_context:
            system_prompt = f"{system_prompt}\n\n=== DIDACTICS CONTEXT ===\n{self.didactics_context}"
        # ЗУНы (если предоставлены) - дополнительная информация для генерации
        zun_info = seed.zun if hasattr(seed, 'zun') and seed.zun else "—"

        # Строим секции контекста из schema-filtered payload, чтобы не протащить статичную инструкцию в теорию.
        curriculum_context_section = self._build_curriculum_context_section(seed, section_context=section_context)
        sjm_section = self._build_sjm_section(seed, section_context=section_context)
        practice_plan_section = render_practice_plan_contract_section(
            practice_plan_contract or (section_context or {}).get("practice_plan_contract")
        )

        # Определяем тип контента (hard_code / low_code / no_code)
        content_type = self._determine_content_type(seed)
        content_type_section = self._build_content_type_section(content_type)
        formulas_code_requirements = self._build_formulas_requirements(seed, content_type)

        # Получаем direction для промпта
        direction = getattr(seed, 'direction', '') or seed.thematic_block or "—"

        self.logger.info(f"Тип контента: {content_type} (direction={direction})")

        # Логируем построенный контекст УП
        ctx = getattr(seed, 'curriculum_context', None)
        if ctx:
            self.logger.info("=" * 50)
            self.logger.info("THEORY AGENT - Контекст УП для промпта:")
            self.logger.info(f"  Блок: {ctx.get('block_name', 'N/A')}")
            self.logger.info(f"  Номер проекта: {ctx.get('current_project_order', 'N/A')}")
            prev_count = len(ctx.get('previous_projects', []))
            next_count = len(ctx.get('next_projects', []))
            self.logger.info(f"  Проектов ДО: {prev_count}, ПОСЛЕ: {next_count}")
            self.logger.info(f"  SJM: {'Да' if ctx.get('sjm_context') else 'Нет'}")
            self.logger.info("=" * 50)

        # Данные из УП
        platform_name = getattr(seed, 'platform_name', None) or "project"
        topic_text = " ".join([
            getattr(seed, "title_seed", "") or "",
            getattr(seed, "project_description", "") or "",
            " ".join(getattr(seed, "learning_outcomes", []) or []),
            " ".join(getattr(seed, "skills", []) or []),
        ])
        gitlab_link_raw = getattr(seed, 'gitlab_link', None) or "—"
        gitlab_link = "—" if section_context is not None else (
            SectionContextPolicy.for_theory().filter_context_value("gitlab_link", gitlab_link_raw, topic_text=topic_text)
            or "—"
        )
        workload_hours = getattr(seed, 'workload_hours', None) or "—"
        workload_days = getattr(seed, 'workload_days', None) or "—"
        filtered_learning_outcomes = (section_context or {}).get("learning_outcomes") or seed.learning_outcomes
        filtered_skills = (section_context or {}).get("skills") or seed.skills
        filtered_project_description = (section_context or {}).get("project_description") or seed.project_description
        filtered_context_summary = (section_context or {}).get("context_summary") or context_meta.context_summary or "—"
        filtered_narrative_anchor = (section_context or {}).get("narrative_anchor") or context_meta.narrative_anchor or "—"

        usr = self.config.get_prompt("user_template").format(
            n_parts=n_parts,
            learning_outcomes="; ".join(filtered_learning_outcomes),
            direction=direction,
            track=seed.thematic_block,
            project_description=filtered_project_description,
            skills="; ".join(filtered_skills),
            context_summary=filtered_context_summary,
            narrative_anchor=filtered_narrative_anchor,
            zun=zun_info,
            include_formulas=seed.include_formulas,
            include_tables=seed.include_tables,
            include_diagrams=seed.include_diagrams,
            curriculum_context_section=curriculum_context_section,
            sjm_section=sjm_section,
            content_type_section=content_type_section,
            formulas_code_requirements=formulas_code_requirements,
            platform_name=platform_name,
            gitlab_link=gitlab_link,
            workload_hours=workload_hours,
            workload_days=workload_days,
            i="{i}",
        )
        if practice_plan_section:
            usr = (
                f"{usr}\n\n=== ПЛАН УЧЕБНОЙ ДЕЯТЕЛЬНОСТИ ДО ТЕОРИИ ===\n"
                "Сгенерируй Главу 2 как поддержку этого плана. Не раскрывай готовые ответы практики.\n\n"
                f"{practice_plan_section}"
            )
        if seed.reference_project_hint and seed.reference_project_hint.strip():
            usr = (
                f"{usr}\n\n=== ЭТАЛОН ИДЕАЛЬНОГО ПРОЕКТА ===\n"
                "Ниже дан reference по качеству и глубине объяснения. Используй его как ориентир по структуре,"
                " но не копируй формулировки и не подменяй им темы текущего проекта из УП.\n\n"
                f"{seed.reference_project_hint.strip()}"
            )
        generation_kwargs = self.llm_kwargs.copy()
        generation_kwargs.setdefault("temperature", 0.2)
        md = self.llm.complete(system=system_prompt, user=usr, **generation_kwargs)

        # КРИТИЧЕСКИ ВАЖНО: Удаляем заголовок главы, если LLM случайно его добавил
        # Удаляем заголовки "## Глава 2", "### Глава 2" и жирные "**Глава 2. Теоретический блок**" в начале ответа
        md = re.sub(r'^##\s+Глава\s+2[^\n]*\n', '', md, flags=re.M)
        md = re.sub(r'^###\s+Глава\s+2[^\n]*\n', '', md, flags=re.M)
        md = re.sub(r'^\*\*Глава\s+2[^\*]+\*\*\s*\n?', '', md, flags=re.M)
        md = re.sub(r'^\s*\*\*Глава\s+2[^\*]+\*\*\s*\n?', '', md, flags=re.M)
        md = md.strip()

        if not md or len(md.strip()) < 50:
            self.logger.warning("LLM вернул пустой или очень короткий ответ (%s символов)", len(md) if md else 0)
        else:
            self.logger.debug("Получен ответ от LLM (%s символов)", len(md))

        parts: list[TheoryPart] = []
        indices = [m.start() for m in self.rx_part.finditer(md)] + [len(md)]
        h_matches = list(self.rx_part.finditer(md))

        # Проверяем ВСЕ сгенерированные части (может быть от 2 до 6 в зависимости от desired_parts и фактически сгенерированных)
        print(f"  📋 Найдено {len(h_matches)} частей теории. Выполняю проверку для ВСЕХ {len(h_matches)} частей...", file=sys.stderr, flush=True)

        if len(h_matches) == 0:
            print(f"  ⚠️ ВНИМАНИЕ: Регулярное выражение не нашло ни одной части! Паттерн: {self.rx_part.pattern}", file=sys.stderr, flush=True)
            print("  💡 Попробуем найти части вручную...", file=sys.stderr, flush=True)

        # Первый проход: парсим все части и собираем данные для батч-генерации
        parts_data = []
        examples_to_generate = []  # Индексы частей, которым нужны примеры
        questions_to_generate = []  # Индексы частей, которым нужны вопросы

        for idx, h in enumerate(h_matches):
            start = h.end()
            end = indices[idx + 1]
            body_block = md[start:end].strip()

            # Поддерживаем оба формата: "2.1. название" (group 1 и 3) и "Часть 1. название" (group 2 и 3)
            # Регулярное выражение: r"^###\s+(?:2\.(\d+)|Часть\s+(\d+))\.\s*(.+?)\s*$"
            # group(1) - номер для формата "2.1." (например, "1")
            # group(2) - номер для формата "Часть 1." (например, "1")
            # group(3) - название раздела
            if h.group(1):  # Формат "2.1. название"
                title = h.group(3).strip() if h.group(3) else ""
            elif h.group(2):  # Формат "Часть 1. название"
                title = h.group(3).strip() if h.group(3) else ""
            else:
                title = ""
            m_ex = self.rx_example.search(body_block)
            example = m_ex.group(1).strip() if m_ex else ""

            m_qs = self.rx_qs.search(body_block)
            qs = []
            if m_qs:
                qs_text = m_qs.group(1).strip()
                qs = [q.strip("- •\t ").rstrip() for q in qs_text.splitlines() if q.strip()][:2]

            # Основной текст — только до блока **Пример:**; убираем любые «Вопросы к практике» из тела (по стандарту они идут один раз — после Примера)
            main_body = body_block.split("**Пример:**", 1)[0].strip()
            if "**Вопросы к практике:**" in main_body:
                main_body = main_body.split("**Вопросы к практике:**", 1)[0].strip()
            main_body = self.style.rewrite(main_body, seed.language)
            lo, hi = THRESHOLDS["theory_words_per_part"]
            main_body = _sanitize_theory_body_text(main_body, title, seed, self._anchor_terms(seed), lo, hi)

            # Сохраняем данные части
            parts_data.append({
                'title': title,
                'body_block': body_block,
                'main_body': main_body,
                'example': example,
                'qs': qs,
            })

            # Отмечаем, что нужно сгенерировать
            if not example:
                examples_to_generate.append(idx)
            if not qs:
                questions_to_generate.append(idx)

        # Батч-генерация примеров (если нужно)
        if examples_to_generate:
            print(f"  ⚠️ Генерирую примеры для {len(examples_to_generate)} частей (батч)...", file=sys.stderr, flush=True)
            system_prompt = self.config.get_prompt("system").format(language=seed.language)

            # Проверяем, поддерживает ли LLM батчинг
            if hasattr(self.llm, 'complete_batch'):
                # Батч-генерация
                batch_requests = []
                for idx in examples_to_generate:
                    part_data = parts_data[idx]
                    user_prompt = f"""Для части теории нужно сгенерировать краткий пример (1-3 предложения).

Название части: {part_data['title']}
Основной текст части:
{part_data['body_block'][:300]}...

Сгенерируй краткий пример из реальной жизни, иллюстрирующий концепцию из этой части.

Формат вывода (строго):
**Пример:** <1-3 предложения, короткий кейс>"""
                    batch_requests.append((system_prompt, user_prompt, None, {"temperature": 0.3}))

                example_results = self.llm.complete_batch(batch_requests)

                for i, idx in enumerate(examples_to_generate):
                    example_md = example_results[i]
                    example_match = re.search(r"\*\*Пример:\*\*\s*(.+?)(?=\n\*\*|\Z)", example_md, re.S)
                    if example_match:
                        example = example_match.group(1).strip()
                        example = self.style.rewrite(example, seed.language)
                    else:
                        example = "Пример из практики, иллюстрирующий применение концепции."
                    parts_data[idx]['example'] = example
            else:
                # Последовательная генерация (fallback)
                for idx in examples_to_generate:
                    part_data = parts_data[idx]
                    user_prompt = f"""Для части теории нужно сгенерировать краткий пример (1-3 предложения).

Название части: {part_data['title']}
Основной текст части:
{part_data['body_block'][:300]}...

Сгенерируй краткий пример из реальной жизни, иллюстрирующий концепцию из этой части.

Формат вывода (строго):
**Пример:** <1-3 предложения, короткий кейс>"""
                    example_md = self.llm.complete(system=system_prompt, user=user_prompt, temperature=0.3)
                    example_match = re.search(r"\*\*Пример:\*\*\s*(.+?)(?=\n\*\*|\Z)", example_md, re.S)
                    if example_match:
                        example = example_match.group(1).strip()
                        example = self.style.rewrite(example, seed.language)
                    else:
                        example = "Пример из практики, иллюстрирующий применение концепции."
                    parts_data[idx]['example'] = example

            print(f"  ✅ Сгенерировано {len(examples_to_generate)} примеров", file=sys.stderr, flush=True)

        # Батч-генерация вопросов (если нужно)
        if questions_to_generate:
            print(f"  ⚠️ Генерирую вопросы для {len(questions_to_generate)} частей (батч)...", file=sys.stderr, flush=True)
            system_prompt = self.config.get_prompt("system").format(language=seed.language)

            # Проверяем, поддерживает ли LLM батчинг
            if hasattr(self.llm, 'complete_batch'):
                # Батч-генерация
                batch_requests = []
                for idx in questions_to_generate:
                    part_data = parts_data[idx]
                    user_prompt = self._build_questions_prompt(part_data, seed)
                    batch_requests.append((system_prompt, user_prompt, None, {"temperature": 0.3}))

                qs_results = self.llm.complete_batch(batch_requests)
                needs_regen = []

                for i, idx in enumerate(questions_to_generate):
                    qs_md = qs_results[i]
                    qs_match = re.search(r"\*\*Вопросы к практике:\*\*([\s\S]+?)(?=\n\*\*|\Z)", qs_md, re.M)
                    if qs_match:
                        qs_text = qs_match.group(1).strip()
                        qs = [q.strip("- •\t ").rstrip() for q in qs_text.splitlines() if q.strip()][:2]
                    else:
                        qs = []
                    parts_data[idx]['qs'] = qs
                    if not self._validate_questions(qs, seed):
                        needs_regen.append(idx)

                # Точечная регенерация проблемных вопросов (последовательно)
                for idx in needs_regen:
                    part_data = parts_data[idx]
                    fix_prompt = self._build_questions_prompt(part_data, seed) + "\nУточнение: вопросы должны содержать явную связь с проектом и инструментами."
                    qs_md = self.llm.complete(system=system_prompt, user=fix_prompt, temperature=0.1)
                    qs_match = re.search(r"\*\*Вопросы к практике:\*\*([\s\S]+?)(?=\n\*\*|\Z)", qs_md, re.M)
                    if qs_match:
                        qs_text = qs_match.group(1).strip()
                        qs = [q.strip("- •\t ").rstrip() for q in qs_text.splitlines() if q.strip()][:2]
                    else:
                        qs = []
                    if not self._validate_questions(qs, seed):
                        anchors = self._anchor_terms(seed)
                        anchor = anchors[0] if anchors else "инструменты проекта"
                        qs = [f"Как применишь {anchor} в практической задаче этого проекта?"]
                    parts_data[idx]['qs'] = qs
            else:
                # Последовательная генерация (fallback)
                for idx in questions_to_generate:
                    part_data = parts_data[idx]
                    user_prompt = self._build_questions_prompt(part_data, seed)
                    qs_md = self.llm.complete(system=system_prompt, user=user_prompt, temperature=0.3)
                    qs_match = re.search(r"\*\*Вопросы к практике:\*\*([\s\S]+?)(?=\n\*\*|\Z)", qs_md, re.M)
                    if qs_match:
                        qs_text = qs_match.group(1).strip()
                        qs = [q.strip("- •\t ").rstrip() for q in qs_text.splitlines() if q.strip()][:2]
                    else:
                        qs = []
                    if not self._validate_questions(qs, seed):
                        fix_prompt = self._build_questions_prompt(part_data, seed) + "\nУточнение: вопросы должны содержать явную связь с проектом и инструментами."
                        qs_md = self.llm.complete(system=system_prompt, user=fix_prompt, temperature=0.1)
                        qs_match = re.search(r"\*\*Вопросы к практике:\*\*([\s\S]+?)(?=\n\*\*|\Z)", qs_md, re.M)
                        if qs_match:
                            qs_text = qs_match.group(1).strip()
                            qs = [q.strip("- •\t ").rstrip() for q in qs_text.splitlines() if q.strip()][:2]
                    if not self._validate_questions(qs, seed):
                        anchors = self._anchor_terms(seed)
                        anchor = anchors[0] if anchors else "инструменты проекта"
                        qs = [f"Как применишь {anchor} в практической задаче этого проекта?"]
                    parts_data[idx]['qs'] = qs

            print(f"  ✅ Сгенерировано вопросов для {len(questions_to_generate)} частей", file=sys.stderr, flush=True)

        # Второй проход: создаем объекты TheoryPart
        for idx, part_data in enumerate(parts_data):
            example = _sanitize_theory_example_text(
                self.style.rewrite(part_data['example'], seed.language)
            ) if part_data['example'] else ""
            covers = self._semantic_cover(part_data['main_body'], seed.learning_outcomes)
            if not covers:
                if not part_data['main_body'].endswith("]"):
                    part_data['main_body'] = part_data['main_body'].rstrip() + " [LO: нет прямого покрытия]."

            part = TheoryPart(
                title=part_data['title'],
                body=part_data['main_body'],
                example=example,
                bridge_questions=part_data['qs'],
                covers_outcomes=covers,
            )

            part = self.polish_part(part, seed)
            parts.append(part)
            print(f"  ✅ Часть {idx+1}/{len(h_matches)} '{part.title}' проверена и обработана", file=sys.stderr, flush=True)

        print(f"  ✅ Все {len(parts)} частей теории проверены и обработаны (проверка выполнена для всех {len(parts)} частей)", file=sys.stderr, flush=True)
        return TheoryResult(parts=parts)
