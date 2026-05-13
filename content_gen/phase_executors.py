"""Phase executors backed by the generation runtime container."""

from __future__ import annotations

import logging
import re
from typing import Any

from .context_phase_executor import ContextPhaseExecutor
from .generation_runtime import GenerationRuntimeContainer
from .models.phase_results import EvaluationPhaseResult, QualityPhaseResult, TranslationPhaseResult
from .models.readme_document import ReadmeDocument
from .models.schemas import ProjectSeed
from .observability import FallbackTraceEvent, record_runtime_fallback_traces
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

    def execute(
        self,
        seed: ProjectSeed,
        markdown: str,
        readme_document: ReadmeDocument | None = None,
        story_map_contract: Any | None = None,
    ) -> QualityPhaseResult:
        """Run quality passes while carrying a typed README document between steps."""
        document = ReadmeDocument.from_value(readme_document, fallback_markdown=markdown)

        logger.info("🔄 Phase 4 | ContentEditor.ensure_global_coherence")
        document = self._run_content_editor(seed, document)
        document = self._ensure_final_section_document(seed, document, story_map_contract=story_map_contract)

        logger.info("🔄 Phase 4 | TOCAgent")
        document = self._run_toc(seed, document)

        md = clean_duplicate_chapter_headers(document.to_markdown(), seed.language)
        document = ReadmeDocument.from_markdown(md)

        logger.info("🔄 Phase 4 | StyleGuardAgent")
        document = self._run_style(seed, document)

        final_markdown = normalize_markdown_display_blocks(document.to_markdown())
        return QualityPhaseResult(
            markdown=final_markdown,
            readme_document=ReadmeDocument.from_markdown(final_markdown),
        )

    def _run_content_editor(
        self,
        seed: ProjectSeed,
        readme_document: ReadmeDocument,
    ) -> ReadmeDocument:
        """Run content editor through the typed contract when available."""
        editor = self.runtime.content_editor
        ensure_document = getattr(editor, "ensure_global_coherence_document", None)
        if callable(ensure_document):
            result = ensure_document(readme_document, seed)
            return ReadmeDocument.from_value(result, fallback_markdown=readme_document.to_markdown())

        md = normalize_markdown_display_blocks(
            editor.ensure_global_coherence(readme_document.to_markdown(), seed)
        )
        self._record_fallback(
            fallback_type="content_editor_markdown_boundary",
            reason="content editor does not expose ensure_global_coherence_document",
            quality_risk="low",
            inputs={"title": readme_document.title, "markdown_chars": len(readme_document.to_markdown())},
        )
        return ReadmeDocument.from_markdown(md, fallback_title=readme_document.title)

    def _run_toc(
        self,
        seed: ProjectSeed,
        readme_document: ReadmeDocument,
    ) -> ReadmeDocument:
        """Rebuild and inject TOC through typed TOC methods when available."""
        toc_agent = self.runtime.toc
        build_document = getattr(toc_agent, "build_document", None)
        inject_document = getattr(toc_agent, "inject_document", None)
        if callable(build_document) and callable(inject_document):
            toc_res = build_document(readme_document, language=seed.language)
            result = inject_document(readme_document, toc_res.toc_md, language=seed.language)
            return ReadmeDocument.from_value(result, fallback_markdown=readme_document.to_markdown())

        md = readme_document.to_markdown()
        toc_res = toc_agent.build(md, language=seed.language)
        md = normalize_markdown_display_blocks(toc_agent.inject(md, toc_res.toc_md))
        return ReadmeDocument.from_markdown(md, fallback_title=readme_document.title)

    def _run_style(
        self,
        seed: ProjectSeed,
        readme_document: ReadmeDocument,
    ) -> ReadmeDocument:
        """Run style guard through a typed document contract with legacy fallback."""
        style = self.runtime.style
        lint_document = getattr(style, "lint_document", None)
        issues_style = (
            lint_document(readme_document, seed.language)
            if callable(lint_document)
            else style.lint(readme_document.to_markdown(), seed.language)
        )
        if not issues_style:
            return readme_document

        rewrite_document = getattr(style, "rewrite_document", None)
        if callable(rewrite_document):
            result = rewrite_document(readme_document, seed.language)
            return ReadmeDocument.from_value(result, fallback_markdown=readme_document.to_markdown())

        md = normalize_markdown_display_blocks(style.rewrite(readme_document.to_markdown(), seed.language))
        self._record_fallback(
            fallback_type="style_guard_markdown_boundary",
            reason="style guard does not expose rewrite_document",
            quality_risk="low",
            inputs={"title": readme_document.title, "markdown_chars": len(readme_document.to_markdown())},
        )
        return ReadmeDocument.from_markdown(md, fallback_title=readme_document.title)

    def _record_fallback(
        self,
        *,
        fallback_type: str,
        reason: str,
        quality_risk: str,
        inputs: dict[str, Any],
    ) -> None:
        """Store quality-phase compatibility fallbacks in the runtime trace."""
        record_runtime_fallback_traces(
            self.runtime,
            [
                FallbackTraceEvent.from_fallback(
                    node="quality",
                    fallback_type=fallback_type,
                    reason=reason,
                    quality_risk=quality_risk,
                    inputs=inputs,
                )
            ],
        )

    def _ensure_final_section_document(
        self,
        seed: ProjectSeed,
        readme_document: ReadmeDocument,
        story_map_contract: Any | None = None,
    ) -> ReadmeDocument:
        """Append a source-compliant closing section to the typed README."""
        for section in readme_document.sections:
            if re.search(r"^(?:Заключение|Итог проекта|Финал проекта|Завершение проекта)\b", section.title, flags=re.I):
                return readme_document
        return readme_document.with_upserted_section_by_title_fragment(
            "Заключение",
            f"## Заключение\n\n{self._final_section_body(seed, story_map_contract=story_map_contract)}",
            fallback_level=2,
        )

    def _final_section_body(self, seed: ProjectSeed, story_map_contract: Any | None = None) -> str:
        """Build the final project conclusion body."""
        title = (getattr(seed, "title_seed", "") or getattr(seed, "project_description", "") or "проект").strip()
        completion = ""
        story_map = story_map_contract or getattr(self.runtime, "story_map_contract", None)
        if story_map is not None:
            completion = str(getattr(story_map, "completion", "") or "")
        if not completion:
            completion = (
                "Собери итоговый артефакт, проверь его по критериям заданий и убедись, "
                "что peer-review может принять работу без дополнительных пояснений."
            )

        return (
            f"В финале у тебя должен остаться проверяемый результат текущего проекта «{title}». "
            f"{completion.rstrip('.')}.\n\n"
            "Проверь, что ключевые решения опираются на материалы проекта, артефакты лежат по указанным путям, "
            "а каждый важный вывод можно показать на p2p-ревью."
        )


class EvaluationPhaseExecutor:
    """Execute Phase 5/6 final evaluation and rubric scoring."""

    def __init__(self, runtime: GenerationRuntimeContainer) -> None:
        self.runtime = runtime

    def execute(
        self,
        seed: ProjectSeed,
        markdown: str,
        readme_document: ReadmeDocument | None = None,
    ) -> EvaluationPhaseResult:
        readme_document = ReadmeDocument.from_value(readme_document, fallback_markdown=markdown)
        logger.info("🔄 Phase 5 | Validators")
        issues_intro = self._validate_intro(markdown, readme_document)
        issues_theory = self._validate_theory(markdown, readme_document)
        issues_practice = self._validate_practice(markdown, readme_document, seed)

        logger.info("🔄 Phase 5 | RubricScorer")
        llm_client = (
            self.runtime.llm_for("evaluation", "RubricScorer", "rubric")
            if hasattr(self.runtime, "llm_for")
            else self.runtime.llm
        )
        self.runtime.rubric = RubricScorer(language=seed.language, llm_client=llm_client)
        criteria_report = self._score_rubric(markdown, readme_document, seed)
        rubric_json = criteria_to_json(criteria_report)

        all_issues = (
            [issue.__dict__ for issue in issues_intro]
            + [issue.__dict__ for issue in issues_theory]
            + [issue.__dict__ for issue in issues_practice]
        )
        return EvaluationPhaseResult(
            rubric_json=rubric_json,
            issues=all_issues,
            readme_document=readme_document,
        )

    def _validate_intro(self, markdown: str, readme_document: ReadmeDocument) -> list[Any]:
        """Run the typed intro validator with Markdown-boundary fallback."""
        validator = self.runtime.intro_validator
        validate_document = getattr(validator, "validate_document", None)
        if callable(validate_document):
            return validate_document(readme_document)
        return validator.validate_markdown(markdown)

    def _validate_theory(self, markdown: str, readme_document: ReadmeDocument) -> list[Any]:
        """Run the typed theory validator with Markdown-boundary fallback."""
        validator = self.runtime.theory_validator
        validate_document = getattr(validator, "validate_document", None)
        if callable(validate_document):
            return validate_document(readme_document)
        return validator.validate_markdown(markdown)

    def _validate_practice(self, markdown: str, readme_document: ReadmeDocument, seed: ProjectSeed) -> list[Any]:
        """Run the typed practice validator with Markdown-boundary fallback."""
        validator = self.runtime.practice_validator
        validate_document = getattr(validator, "validate_document", None)
        if callable(validate_document):
            return validate_document(
                readme_document,
                language=seed.language,
                tasks_count_expected=seed.tasks_count,
            )
        return validator.validate_markdown(markdown, seed.language, seed.tasks_count)

    def _score_rubric(self, markdown: str, readme_document: ReadmeDocument, seed: ProjectSeed) -> Any:
        """Run typed rubric scoring when available while keeping scorer doubles compatible."""
        score_document = getattr(self.runtime.rubric, "score_document", None)
        if callable(score_document):
            return score_document(readme_document, learning_outcomes=seed.learning_outcomes)
        return self.runtime.rubric.score(markdown, learning_outcomes=seed.learning_outcomes)


class TranslationPhaseExecutor:
    """Execute final translation when the target language differs from Russian."""

    def __init__(self, runtime: GenerationRuntimeContainer) -> None:
        self.runtime = runtime

    def execute(
        self,
        seed: ProjectSeed,
        markdown: str,
        target_language: str,
        readme_document: ReadmeDocument | None = None,
    ) -> TranslationPhaseResult:
        readme_document = ReadmeDocument.from_value(readme_document, fallback_markdown=markdown)
        original_md = markdown
        logger.info(
            "🔄 Phase 6 | Входные параметры: target_language='%s', размер md=%s символов",
            target_language,
            len(original_md),
        )

        if target_language != "ru":
            logger.info("🔄 Phase 6 | TranslatorAgent (перевод на %s)", target_language)
            translated_md = self.runtime.translator.translate(original_md, target_language, seed)
            if original_md == translated_md:
                logger.warning(
                    "⚠️ Phase 6 | Переводчик вернул исходный текст без изменений для языка %s!",
                    target_language,
                )
                logger.warning("⚠️ Phase 6 | Первые 200 символов оригинала: %s", original_md[:200])
                logger.warning("⚠️ Phase 6 | Первые 200 символов перевода: %s", translated_md[:200])
            else:
                logger.info(
                    "✅ Phase 6 | Перевод применен (до: %s символов, после: %s символов)",
                    len(original_md),
                    len(translated_md),
                )
                logger.info("✅ Phase 6 | Первые 200 символов перевода: %s", translated_md[:200])
        else:
            logger.info("🔄 Phase 6 | TranslatorAgent пропущен (язык уже русский)")
            translated_md = original_md

        translated_document = None
        if translated_md:
            translated_document = ReadmeDocument.from_markdown(translated_md, fallback_title=readme_document.title)
        return TranslationPhaseResult(
            markdown=original_md,
            translated_markdown=translated_md,
            readme_document=readme_document,
            translated_readme_document=translated_document,
        )
