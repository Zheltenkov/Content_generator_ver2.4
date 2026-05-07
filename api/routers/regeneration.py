"""Endpoint для перегенерации контента."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db.generation_results_db import update_regeneration_result
from api.db.logging_db import write_log_async
from api.dependencies import get_current_user
from api.utils.logger import get_logger
from api.utils.logging_context import set_request_id, set_user_id
from api.utils.result_cache import get_result
from content_gen.agents.content_editor import ContentEditorAgent
from content_gen.agents.regeneration import RegenerationAgent
from content_gen.agents.style_guard import StyleGuardAgent
from content_gen.llm.client import LLMClient
from content_gen.models.schemas import ProjectSeed
from content_gen.extraction.lo_skills import LOAndSkills, extract_lo_and_skills_with_llm
from content_gen.utils.latex_validator import build_latex_agent_hint, collect_latex_issues
from content_gen.utils.rubric_export import convert_numpy_types, criteria_to_json
from content_gen.validators.rubric import RubricScorer
from utils.token_counter import count_tokens

logger = get_logger("regeneration")

def calculate_text_stats(text: str) -> dict:
    """Вычисляет статистику текста."""
    chars = len(text)
    words = len(text.split())
    tokens = count_tokens(text)
    return {
        "chars": chars,
        "words": words,
        "tokens": tokens
    }

router = APIRouter()


class RegenerateRequest(BaseModel):
    """Запрос на перегенерацию контента."""
    original_request_id: str | None = None  # ID оригинального запроса (для сохранения в кэш)
    original_md: str
    comments: str
    language: str = "ru"


class RegenerateResponse(BaseModel):
    """Ответ с результатом перегенерации."""
    request_id: str
    regenerated_md: str
    changes: list[str]
    rubric: dict[str, Any]
    text_stats: dict[str, Any]
    learning_outcomes: list[str] = Field(default_factory=list, description="Извлеченные образовательные результаты")
    skills: list[str] = Field(default_factory=list, description="Извлеченные навыки")


@router.post("/regenerate", response_model=RegenerateResponse)
async def regenerate(
    request: RegenerateRequest,
    user: dict = Depends(get_current_user)
):
    """
    Перегенерирует контент на основе комментариев.
    
    Args:
        request: Запрос с оригинальным markdown и комментариями
        user: Данные пользователя из аутентификации
        
    Returns:
        Результат перегенерации
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")

    # Устанавливаем контекст для логирования
    set_request_id(request_id)
    set_user_id(user_id)

    # Логируем начало перегенерации
    logger.info(f"🔄 Начало перегенерации контента для пользователя {user_id}")
    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Начало перегенерации контента",
        user_id=user_id,
        phase="regeneration",
        metadata={
            "comments_length": len(request.comments or ""),
            "original_md_length": len(request.original_md or ""),
        },
    )

    try:
        # Инициализируем LLM клиент и агенты
        llm_client = LLMClient(provider="openai")
        regen_agent = RegenerationAgent(llm_client)

        # Пытаемся извлечь ProjectSeed из кэша для проверок качества
        seed = None
        original_cached = None
        if request.original_request_id:
            original_cached = get_result(request.original_request_id)
            if original_cached and "result" in original_cached:
                # Восстанавливаем seed из spec или report_json
                spec = original_cached["result"].spec if hasattr(original_cached["result"], "spec") else None
                report_json = original_cached.get("report_json", {})

                if spec:
                    # Создаём минимальный ProjectSeed из spec
                    try:
                        seed = ProjectSeed(
                            language=getattr(spec, "language", request.language),
                            project_type=getattr(spec, "project_type", "individual"),
                            thematic_block=getattr(spec, "thematic_block", ""),
                            project_description=getattr(spec, "project_description", "Перегенерированный контент"),
                            learning_outcomes=list(getattr(spec, "learning_outcomes", []) or []),
                            skills=list(getattr(spec, "skills", []) or []),
                            tasks_count=getattr(spec, "tasks_count", 3)
                        )
                    except Exception as e:
                        logger.warning(f"Не удалось восстановить seed из кэша: {e}")

        # Если seed не восстановлен, создаём минимальный для проверок качества
        if not seed:
            try:
                seed = ProjectSeed(
                    language=request.language,
                    project_type="individual",  # Значение по умолчанию
                    thematic_block="",
                    project_description="Перегенерированный контент",
                    learning_outcomes=[],
                    skills=[],
                    tasks_count=3
                )
            except Exception:
                seed = None

        # Выполняем перегенерацию в отдельном потоке
        result = await asyncio.to_thread(
            regen_agent.regenerate,
            original_md=request.original_md,
            comments=request.comments,
            language=request.language
        )

        regenerated_md = result.regenerated_md

        latex_issues = collect_latex_issues(regenerated_md)
        if latex_issues:
            issue_text = "; ".join(latex_issues[:3])
            agent_hint = build_latex_agent_hint(latex_issues)
            logger.error("❌ Ошибка LaTeX при перегенерации: %s", issue_text)
            await write_log_async(
                request_id=request_id,
                level="ERROR",
                message="Перегенерация остановлена: найдены ошибки LaTeX",
                user_id=user_id,
                phase="regeneration_validation",
                metadata={"issues": latex_issues[:5], "agent_hint": agent_hint},
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Найдены проблемы с LaTeX формулами: {issue_text}. "
                    f"Подсказка для агента: {agent_hint}"
                ),
            )

        # Проверки качества перед критериями (аналогично Phase 4 основной генерации)
        if seed:
            logger.info("🔄 Применение проверок качества к перегенерированному контенту")

            # ContentEditor: глобальная когерентность
            try:
                content_editor = ContentEditorAgent(llm_client)
                regenerated_md = await asyncio.to_thread(
                    content_editor.ensure_global_coherence,
                    regenerated_md,
                    seed
                )
                logger.info("✅ ContentEditor.ensure_global_coherence применён")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при применении ContentEditor: {e}")

            # StyleGuard: проверка и исправление стиля
            try:
                style_guard = StyleGuardAgent()
                issues_style = await asyncio.to_thread(
                    style_guard.lint,
                    regenerated_md,
                    request.language
                )
                if issues_style:
                    logger.info(f"🔄 Найдено {len(issues_style)} проблем стиля, применяем исправления")
                    regenerated_md = await asyncio.to_thread(
                        style_guard.rewrite,
                        regenerated_md,
                        request.language
                    )
                    logger.info("✅ StyleGuardAgent применён")
                else:
                    logger.info("✅ Проблем стиля не найдено")
            except Exception as e:
                logger.warning(f"⚠️ Ошибка при применении StyleGuard: {e}")

        # Извлекаем ЗУНы (learning_outcomes и skills) из перегенерированного контента
        logger.info("🔄 Извлечение ЗУНов из перегенерированного контента")
        lo_and_skills = LOAndSkills()
        try:
            lo_and_skills = await asyncio.to_thread(
                extract_lo_and_skills_with_llm,
                regenerated_md,
                llm_client,
                request.language,
                use_preprocessing=True
            )
            logger.info(
                f"✅ ЗУНы извлечены: LO={len(lo_and_skills.learning_outcomes)}, "
                f"Skills={len(lo_and_skills.skills)}"
            )
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при извлечении ЗУНов: {e}")

        # Если не удалось извлечь ЗУНы, пробуем взять из оригинального запроса
        if not lo_and_skills.learning_outcomes:
            if not original_cached and request.original_request_id:
                original_cached = get_result(request.original_request_id)
            if original_cached:
                # Пробуем взять из кэша перегенерированных данных
                if original_cached.get("regenerated") and original_cached["regenerated"].get("learning_outcomes"):
                    lo_and_skills.learning_outcomes = original_cached["regenerated"]["learning_outcomes"]
                    logger.info(f"✅ Использованы ЗУНы из перегенерированного кэша: LO={len(lo_and_skills.learning_outcomes)}")
                # Или из оригинального результата (spec)
                elif original_cached.get("result") and hasattr(original_cached["result"], "spec"):
                    spec_cached = original_cached["result"].spec
                    if hasattr(spec_cached, "learning_outcomes") and spec_cached.learning_outcomes:
                        lo_and_skills.learning_outcomes = list(spec_cached.learning_outcomes)
                        logger.info(f"✅ Использованы ЗУНы из оригинального spec: LO={len(lo_and_skills.learning_outcomes)}")
                # Или из report_json
                elif original_cached.get("report_json", {}).get("learning_outcomes"):
                    lo_and_skills.learning_outcomes = original_cached["report_json"]["learning_outcomes"]
                    logger.info(f"✅ Использованы ЗУНы из report_json: LO={len(lo_and_skills.learning_outcomes)}")
                # Или напрямую из кэша
                elif original_cached.get("learning_outcomes"):
                    lo_and_skills.learning_outcomes = original_cached["learning_outcomes"]
                    logger.info(f"✅ Использованы ЗУНы из оригинального кэша: LO={len(lo_and_skills.learning_outcomes)}")

        # Если до сих пор пусто, используем данные seed
        if not lo_and_skills.learning_outcomes and seed and seed.learning_outcomes:
            lo_and_skills.learning_outcomes = list(seed.learning_outcomes)
            logger.info(f"✅ Использованы ЗУНы из ProjectSeed: LO={len(lo_and_skills.learning_outcomes)}")

        if not lo_and_skills.skills and seed and seed.skills:
            lo_and_skills.skills = list(seed.skills)

        # Вычисляем rubric и статистику (после проверок качества)
        # ВАЖНО: передаем learning_outcomes в score() для проверки критерия 2.4.5
        rubric_scorer = RubricScorer(language=request.language, llm_client=llm_client)
        rubric_result = await asyncio.to_thread(
            rubric_scorer.score,
            regenerated_md,
            learning_outcomes=lo_and_skills.learning_outcomes if lo_and_skills.learning_outcomes else None
        )
        rubric_json = criteria_to_json(rubric_result)

        text_stats = calculate_text_stats(regenerated_md)

        # Сохраняем перегенерированные данные в кэш оригинального запроса
        if request.original_request_id:
            original_cached = get_result(request.original_request_id)
            if original_cached:
                original_cached["regenerated"] = {
                    "regenerated_md": regenerated_md,
                    "changes": result.changes,
                    "rubric": rubric_json,
                    "text_stats": text_stats,
                    "learning_outcomes": lo_and_skills.learning_outcomes,
                    "skills": lo_and_skills.skills,
                    "comments": request.comments,
                    "original_md": request.original_md,
                }

            try:
                await asyncio.to_thread(
                    update_regeneration_result,
                    request.original_request_id,
                    regenerated_md,
                    rubric_json,
                    request.comments,
                    result.changes,
                    request.original_md,
                )
            except Exception as db_err:
                logger.warning(
                    "⚠️ Не удалось сохранить данные перегенерации в БД: %s",
                    db_err,
                )

        # Логируем успешное завершение
        logger.info(
            f"✅ Перегенерация завершена успешно: markdown={len(regenerated_md)} символов, "
            f"изменений={len(result.changes)}, LO={len(lo_and_skills.learning_outcomes)}, "
            f"Skills={len(lo_and_skills.skills)}"
        )
        await write_log_async(
            request_id=request_id,
            level="INFO",
            message="Перегенерация контента завершена успешно",
            user_id=user_id,
            phase="regeneration_complete",
            metadata={
                "markdown_length": len(regenerated_md),
                "changes_count": len(result.changes),
                "learning_outcomes_count": len(lo_and_skills.learning_outcomes),
                "skills_count": len(lo_and_skills.skills),
            }
        )

        # Конвертируем numpy типы в стандартные Python типы для JSON сериализации
        rubric_json_clean = convert_numpy_types(rubric_json)

        return RegenerateResponse(
            request_id=request_id,
            regenerated_md=regenerated_md,
            changes=result.changes,
            rubric=rubric_json_clean,
            text_stats=text_stats,
            learning_outcomes=lo_and_skills.learning_outcomes,
            skills=lo_and_skills.skills
        )

    except Exception as e:
        # Логируем ошибку
        logger.error(f"❌ Ошибка перегенерации: {str(e)}", exc_info=True)
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка перегенерации: {str(e)}",
            user_id=user_id,
            phase="regeneration_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Ошибка перегенерации: {str(e)}")
