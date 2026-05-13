"""Application service for README regeneration workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from api.db.generation_results_db import update_regeneration_result
from api.db.logging_db import write_log_async
from api.utils.logger import get_logger
from api.utils.result_cache import get_result
from content_gen.agents.content_editor import ContentEditorAgent
from content_gen.agents.regeneration import RegenerationAgent
from content_gen.agents.style_guard import StyleGuardAgent
from content_gen.llm.client import LLMClient
from content_gen.project_seed_provider import ProjectSeedProvider
from content_gen.utils.latex_validator import build_latex_agent_hint, collect_latex_issues
from content_gen.utils.rubric_export import convert_numpy_types, criteria_to_json
from content_gen.validators.rubric import RubricScorer
from utils.token_counter import count_tokens

logger = get_logger("regeneration")


@dataclass(frozen=True)
class RegenerationCommand:
    """Input contract for regeneration application workflow."""

    request_id: str
    user_id: str
    original_md: str
    comments: str
    language: str = "ru"
    original_request_id: str | None = None
    project_seed: dict[str, Any] | None = None
    curriculum_project: dict[str, Any] | None = None


@dataclass(frozen=True)
class RegenerationResultView:
    """Serializable regeneration result returned to the HTTP adapter."""

    request_id: str
    regenerated_md: str
    changes: list[str]
    rubric: dict[str, Any]
    text_stats: dict[str, Any]
    learning_outcomes: list[str]
    skills: list[str]
    seed_source: str
    learning_context_source: str


class RegenerationValidationError(Exception):
    """Raised when regenerated content fails deterministic validation."""

    def __init__(self, detail: str, *, status_code: int = 422) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def calculate_text_stats(text: str) -> dict[str, int]:
    """Compute deterministic text statistics for reporting."""
    chars = len(text)
    words = len(text.split())
    tokens = count_tokens(text)
    return {
        "chars": chars,
        "words": words,
        "tokens": tokens,
    }


def _unique_non_empty(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for item in items if isinstance(item, str) and item.strip()))


def _learning_context_from_cache(cached_result: dict[str, Any] | None) -> tuple[list[str], list[str], str | None]:
    """Read already structured LO/skills from cache without LLM extraction."""
    if not cached_result:
        return [], [], None

    candidates: list[tuple[str, Any]] = [
        ("cache.project_seed_payload", cached_result.get("project_seed_payload")),
        ("cache.project_seed", cached_result.get("project_seed")),
        ("cache.regenerated", cached_result.get("regenerated")),
        ("cache.report_json", cached_result.get("report_json")),
        ("cache.root", cached_result),
    ]

    result = cached_result.get("result")
    spec = getattr(result, "spec", None) if result is not None else None
    if spec is not None:
        candidates.append(("cache.result.spec", spec.model_dump() if hasattr(spec, "model_dump") else spec))

    for source, candidate in candidates:
        if isinstance(candidate, dict):
            learning_outcomes = _unique_non_empty(
                ProjectSeedProvider._as_list(candidate.get("learning_outcomes"))
            )
            skills = _unique_non_empty(ProjectSeedProvider._as_list(candidate.get("skills")))
        else:
            learning_outcomes = _unique_non_empty(
                ProjectSeedProvider._as_list(getattr(candidate, "learning_outcomes", None))
            )
            skills = _unique_non_empty(
                ProjectSeedProvider._as_list(getattr(candidate, "skills", None))
            )
        if learning_outcomes or skills:
            return learning_outcomes, skills, source

    return [], [], None


def _learning_context_from_seed_and_cache(
    seed: Any,
    cached_result: dict[str, Any] | None,
) -> tuple[list[str], list[str], str]:
    """Prefer current project metadata; use cache only to fill missing structured fields."""
    learning_outcomes = _unique_non_empty(list(getattr(seed, "learning_outcomes", []) or []))
    skills = _unique_non_empty(list(getattr(seed, "skills", []) or []))
    source = "seed" if learning_outcomes or skills else "unavailable"

    cached_learning_outcomes, cached_skills, cached_source = _learning_context_from_cache(cached_result)
    if not learning_outcomes and cached_learning_outcomes:
        learning_outcomes = cached_learning_outcomes
        source = cached_source or source
    if not skills and cached_skills:
        skills = cached_skills
        source = cached_source or source

    return learning_outcomes, skills, source


class RegenerationService:
    """Coordinate regeneration agents, validation, scoring and persistence."""

    def __init__(
        self,
        *,
        llm_factory: Callable[[], LLMClient] | None = None,
        cache_getter: Callable[[str], dict[str, Any] | None] = get_result,
        db_updater: Callable[..., Any] = update_regeneration_result,
        log_writer: Callable[..., Any] = write_log_async,
    ) -> None:
        self._llm_factory = llm_factory or LLMClient
        self._cache_getter = cache_getter
        self._db_updater = db_updater
        self._log_writer = log_writer

    async def regenerate(self, command: RegenerationCommand) -> RegenerationResultView:
        """Run the full regeneration application workflow."""
        await self._log_start(command)

        llm_client = self._llm_factory()
        regen_agent = RegenerationAgent(llm_client)

        original_cached = self._load_original_cached(command.original_request_id)
        seed_result = ProjectSeedProvider.build_for_regeneration(
            language=command.language,
            project_seed=command.project_seed,
            curriculum_project=command.curriculum_project,
            cached_result=original_cached,
        )
        seed = seed_result.seed
        if seed_result.warnings:
            logger.warning("⚠️ Предупреждения восстановления ProjectSeed: %s", "; ".join(seed_result.warnings[:3]))
        logger.info(
            "📌 ProjectSeed для перегенерации: source=%s, title='%s', LO=%s, skills=%s",
            seed_result.source,
            seed.title_seed,
            len(seed.learning_outcomes),
            len(seed.skills),
        )

        result = await asyncio.to_thread(
            regen_agent.regenerate,
            original_md=command.original_md,
            comments=command.comments,
            language=command.language,
        )
        regenerated_md = result.regenerated_md

        await self._validate_latex(command, regenerated_md)
        regenerated_md = await self._apply_quality_checks(
            llm_client=llm_client,
            markdown=regenerated_md,
            seed=seed,
            language=command.language,
        )
        learning_outcomes, skills, learning_context_source = await self._resolve_learning_context(
            seed=seed,
            cached_result=original_cached,
        )

        rubric_json = await self._score_rubric(
            llm_client=llm_client,
            markdown=regenerated_md,
            language=command.language,
            learning_outcomes=learning_outcomes,
        )
        text_stats = calculate_text_stats(regenerated_md)

        await self._persist_regeneration(
            command=command,
            cached_result=original_cached,
            regenerated_md=regenerated_md,
            changes=result.changes,
            rubric_json=rubric_json,
            text_stats=text_stats,
            learning_outcomes=learning_outcomes,
            skills=skills,
            seed_source=seed_result.source,
            learning_context_source=learning_context_source,
        )
        await self._log_success(
            command=command,
            regenerated_md=regenerated_md,
            changes_count=len(result.changes),
            learning_outcomes=learning_outcomes,
            skills=skills,
            seed_source=seed_result.source,
            learning_context_source=learning_context_source,
        )

        return RegenerationResultView(
            request_id=command.request_id,
            regenerated_md=regenerated_md,
            changes=result.changes,
            rubric=convert_numpy_types(rubric_json),
            text_stats=text_stats,
            learning_outcomes=learning_outcomes,
            skills=skills,
            seed_source=seed_result.source,
            learning_context_source=learning_context_source,
        )

    def _load_original_cached(self, original_request_id: str | None) -> dict[str, Any] | None:
        if not original_request_id:
            return None
        return self._cache_getter(original_request_id)

    async def _validate_latex(self, command: RegenerationCommand, markdown: str) -> None:
        latex_issues = collect_latex_issues(markdown)
        if not latex_issues:
            return

        issue_text = "; ".join(latex_issues[:3])
        agent_hint = build_latex_agent_hint(latex_issues)
        logger.error("❌ Ошибка LaTeX при перегенерации: %s", issue_text)
        await self._log_writer(
            request_id=command.request_id,
            level="ERROR",
            message="Перегенерация остановлена: найдены ошибки LaTeX",
            user_id=command.user_id,
            phase="regeneration_validation",
            metadata={"issues": latex_issues[:5], "agent_hint": agent_hint},
        )
        raise RegenerationValidationError(
            f"Найдены проблемы с LaTeX формулами: {issue_text}. "
            f"Подсказка для агента: {agent_hint}",
            status_code=422,
        )

    async def _apply_quality_checks(
        self,
        *,
        llm_client: LLMClient,
        markdown: str,
        seed: Any,
        language: str,
    ) -> str:
        logger.info("🔄 Применение проверок качества к перегенерированному контенту")

        try:
            content_editor = ContentEditorAgent(llm_client)
            markdown = await asyncio.to_thread(
                content_editor.ensure_global_coherence,
                markdown,
                seed,
            )
            logger.info("✅ ContentEditor.ensure_global_coherence применён")
        except Exception as exc:
            logger.warning("⚠️ Ошибка при применении ContentEditor: %s", exc)

        try:
            style_guard = StyleGuardAgent()
            issues_style = await asyncio.to_thread(style_guard.lint, markdown, language)
            if issues_style:
                logger.info("🔄 Найдено %s проблем стиля, применяем исправления", len(issues_style))
                markdown = await asyncio.to_thread(style_guard.rewrite, markdown, language)
                logger.info("✅ StyleGuardAgent применён")
            else:
                logger.info("✅ Проблем стиля не найдено")
        except Exception as exc:
            logger.warning("⚠️ Ошибка при применении StyleGuard: %s", exc)

        return markdown

    async def _resolve_learning_context(
        self,
        *,
        seed: Any,
        cached_result: dict[str, Any] | None,
    ) -> tuple[list[str], list[str], str]:
        learning_outcomes, skills, learning_context_source = _learning_context_from_seed_and_cache(seed, cached_result)
        logger.info(
            "📚 Контекст ЗУНов для перегенерации: source=%s, LO=%s, skills=%s",
            learning_context_source,
            len(learning_outcomes),
            len(skills),
        )

        if not learning_outcomes and not skills:
            logger.warning(
                "⚠️ Структурированный контекст ЗУНов для перегенерации отсутствует; "
                "рубрика будет рассчитана без LO/skills."
            )
        return learning_outcomes, skills, learning_context_source

    async def _score_rubric(
        self,
        *,
        llm_client: LLMClient,
        markdown: str,
        language: str,
        learning_outcomes: list[str],
    ) -> dict[str, Any]:
        rubric_scorer = RubricScorer(language=language, llm_client=llm_client)
        rubric_result = await asyncio.to_thread(
            rubric_scorer.score,
            markdown,
            learning_outcomes=learning_outcomes if learning_outcomes else None,
        )
        return criteria_to_json(rubric_result)

    async def _persist_regeneration(
        self,
        *,
        command: RegenerationCommand,
        cached_result: dict[str, Any] | None,
        regenerated_md: str,
        changes: list[str],
        rubric_json: dict[str, Any],
        text_stats: dict[str, Any],
        learning_outcomes: list[str],
        skills: list[str],
        seed_source: str,
        learning_context_source: str,
    ) -> None:
        if not command.original_request_id:
            return

        if cached_result is None:
            cached_result = self._cache_getter(command.original_request_id)
        if cached_result:
            cached_result["regenerated"] = {
                "regenerated_md": regenerated_md,
                "changes": changes,
                "rubric": rubric_json,
                "text_stats": text_stats,
                "learning_outcomes": learning_outcomes,
                "skills": skills,
                "seed_source": seed_source,
                "learning_context_source": learning_context_source,
                "comments": command.comments,
                "original_md": command.original_md,
            }

        try:
            await asyncio.to_thread(
                self._db_updater,
                command.original_request_id,
                regenerated_md,
                rubric_json,
                command.comments,
                changes,
                command.original_md,
            )
        except Exception as db_err:
            logger.warning("⚠️ Не удалось сохранить данные перегенерации в БД: %s", db_err)

    async def _log_start(self, command: RegenerationCommand) -> None:
        logger.info("🔄 Начало перегенерации контента для пользователя %s", command.user_id)
        await self._log_writer(
            request_id=command.request_id,
            level="INFO",
            message="Начало перегенерации контента",
            user_id=command.user_id,
            phase="regeneration",
            metadata={
                "comments_length": len(command.comments or ""),
                "original_md_length": len(command.original_md or ""),
            },
        )

    async def _log_success(
        self,
        *,
        command: RegenerationCommand,
        regenerated_md: str,
        changes_count: int,
        learning_outcomes: list[str],
        skills: list[str],
        seed_source: str,
        learning_context_source: str,
    ) -> None:
        logger.info(
            "✅ Перегенерация завершена успешно: markdown=%s символов, изменений=%s, LO=%s, Skills=%s",
            len(regenerated_md),
            changes_count,
            len(learning_outcomes),
            len(skills),
        )
        await self._log_writer(
            request_id=command.request_id,
            level="INFO",
            message="Перегенерация контента завершена успешно",
            user_id=command.user_id,
            phase="regeneration_complete",
            metadata={
                "markdown_length": len(regenerated_md),
                "changes_count": changes_count,
                "learning_outcomes_count": len(learning_outcomes),
                "skills_count": len(skills),
                "seed_source": seed_source,
                "learning_context_source": learning_context_source,
            },
        )
