"""Phase executors backed by the generation runtime container."""

from __future__ import annotations

import logging
import re
from typing import Any

from .context_phase_executor import ContextPhaseExecutor
from .generation_runtime import GenerationRuntimeContainer
from .models.schemas import ProjectSeed
from .practice_phase_executor import PracticePhaseExecutor
from .structure_phase_executor import StructurePhaseExecutor
from .theory_phase_executor import TheoryPhaseExecutor
from .utils.markdown_display_normalizer import normalize_markdown_display_blocks
from .utils.markdown_helpers import clean_duplicate_chapter_headers
from .utils.rubric_export import criteria_to_json
from .validators.rubric import RubricScorer

logger = logging.getLogger("content_gen.phase_executors")


class QualityPhaseExecutor:
    """Execute Phase 4 global quality pass."""

    def __init__(self, runtime: GenerationRuntimeContainer) -> None:
        self.runtime = runtime

    def execute(self, seed: ProjectSeed, markdown: str) -> str:
        logger.info("🔄 Phase 4 | ContentEditor.ensure_global_coherence")
        md = normalize_markdown_display_blocks(self.runtime.content_editor.ensure_global_coherence(markdown, seed))
        md = normalize_markdown_display_blocks(self._ensure_final_section(seed, md))

        logger.info("🔄 Phase 4 | TOCAgent")
        toc_res = self.runtime.toc.build(md, language=seed.language)
        md = normalize_markdown_display_blocks(self.runtime.toc.inject(md, toc_res.toc_md))

        md = clean_duplicate_chapter_headers(md, seed.language)

        logger.info("🔄 Phase 4 | StyleGuardAgent")
        issues_style = self.runtime.style.lint(md, seed.language)
        if issues_style:
            md = normalize_markdown_display_blocks(self.runtime.style.rewrite(md, seed.language))

        return normalize_markdown_display_blocks(md)

    def _ensure_final_section(self, seed: ProjectSeed, markdown: str) -> str:
        """Append a source-compliant closing section for the current project."""
        if re.search(r"^##\s+(?:Заключение|Итог проекта|Финал проекта|Завершение проекта)\b", markdown, flags=re.M | re.I):
            return markdown

        title = (getattr(seed, "title_seed", "") or getattr(seed, "project_description", "") or "проект").strip()
        completion = ""
        story_map = self.runtime.story_map_contract
        if story_map is not None:
            completion = str(getattr(story_map, "completion", "") or "")
        if not completion:
            completion = (
                "Собери итоговый артефакт, проверь его по критериям заданий и убедись, "
                "что peer-review может принять работу без дополнительных пояснений."
            )

        final_section = (
            "## Заключение\n\n"
            f"В финале у тебя должен остаться проверяемый результат текущего проекта «{title}». "
            f"{completion.rstrip('.')}.\n\n"
            "Проверь, что ключевые решения опираются на материалы проекта, артефакты лежат по указанным путям, "
            "а каждый важный вывод можно показать на p2p-ревью."
        )
        return f"{markdown.rstrip()}\n\n{final_section}\n"


class EvaluationPhaseExecutor:
    """Execute Phase 5/6 final evaluation and rubric scoring."""

    def __init__(self, runtime: GenerationRuntimeContainer) -> None:
        self.runtime = runtime

    def execute(self, seed: ProjectSeed, markdown: str) -> tuple[dict[str, Any], list[Any]]:
        logger.info("🔄 Phase 5 | Validators")
        issues_intro = self.runtime.intro_validator.validate_markdown(markdown)
        issues_theory = self.runtime.theory_validator.validate_markdown(markdown)
        issues_practice = self.runtime.practice_validator.validate_markdown(markdown, seed.language, seed.tasks_count)

        logger.info("🔄 Phase 5 | RubricScorer")
        self.runtime.rubric = RubricScorer(language=seed.language, llm_client=self.runtime.llm)
        criteria_report = self.runtime.rubric.score(markdown, learning_outcomes=seed.learning_outcomes)
        rubric_json = criteria_to_json(criteria_report)

        all_issues = (
            [issue.__dict__ for issue in issues_intro]
            + [issue.__dict__ for issue in issues_theory]
            + [issue.__dict__ for issue in issues_practice]
        )
        return rubric_json, all_issues


class TranslationPhaseExecutor:
    """Execute final translation when the target language differs from Russian."""

    def __init__(self, runtime: GenerationRuntimeContainer) -> None:
        self.runtime = runtime

    def execute(self, seed: ProjectSeed, markdown: str, target_language: str) -> tuple[str, str]:
        original_md = markdown
        logger.info(
            "🔄 Phase 6 | Входные параметры: target_language='%s', размер md=%s символов",
            target_language,
            len(markdown),
        )

        if target_language != "ru":
            logger.info("🔄 Phase 6 | TranslatorAgent (перевод на %s)", target_language)
            translated_md = self.runtime.translator.translate(markdown, target_language, seed)
            if markdown == translated_md:
                logger.warning(
                    "⚠️ Phase 6 | Переводчик вернул исходный текст без изменений для языка %s!",
                    target_language,
                )
                logger.warning("⚠️ Phase 6 | Первые 200 символов оригинала: %s", markdown[:200])
                logger.warning("⚠️ Phase 6 | Первые 200 символов перевода: %s", translated_md[:200])
            else:
                logger.info(
                    "✅ Phase 6 | Перевод применен (до: %s символов, после: %s символов)",
                    len(markdown),
                    len(translated_md),
                )
                logger.info("✅ Phase 6 | Первые 200 символов перевода: %s", translated_md[:200])
        else:
            logger.info("🔄 Phase 6 | TranslatorAgent пропущен (язык уже русский)")
            translated_md = markdown

        return original_md, translated_md
