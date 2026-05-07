"""Endpoint для генерации контента."""

import asyncio
import copy
import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from api.db.generation_results_db import save_generation_result
from api.db.logging_db import write_log_async
from api.db.paused_generation_db import (
    load_paused_generation_session,
    mark_paused_generation_diff_approved,
    mark_paused_generation_approved,
    mark_paused_generation_completed,
    mark_paused_generation_rejected,
    record_paused_generation_change_request,
    record_paused_generation_preview,
    save_paused_generation_session,
)
from api.dependencies import get_current_user
from api.schemas import GenerateStartResponse, GenerationStatusResponse
from api.utils.logger import get_logger
from api.utils.logging_context import set_request_id, set_user_id
from api.utils.result_cache import (
    cancel_generation_task,
    get_generation_error,
    get_generation_methodology,
    get_generation_status,
    get_result,
    register_generation_task,
    set_generation_methodology,
    set_generation_status,
    store_generation_error,
    store_result,
    unregister_generation_task,
)

logger = get_logger("generation")
from content_gen.didactics import compose_didactics_context, get_didactics_trace
from content_gen.exceptions import (
    ContentGenerationError,
    LLMAPIError,
    LLMRateLimitError,
    LLMTimeoutError,
    ValidationError,
)
from content_gen.llm.cached_client import CachedLLMClient
from content_gen.methodology import (
    MethodologistChangeRequest,
    ScopedRevisionExecutor,
    build_requirement_matrix,
    build_section_target_registry,
    has_hard_conflicts,
    validate_methodologist_change_request,
)
from content_gen.orchestrator import Orchestrator
from content_gen.utils.latex_validator import build_latex_agent_hint, collect_latex_issues
from content_gen.utils.markdown_display_normalizer import normalize_markdown_display_blocks

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)
_stepwise_generation_sessions: dict[str, dict[str, Any]] = {}


class StepwiseGenerationStartRequest(BaseModel):
    """Совместимый запрос для legacy stepwise API."""
    seed: dict[str, Any] = Field(default_factory=dict)
    stepwise: bool = False


def _methodology_human_review_enabled(
    project_seed_payload: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> bool:
    """Return whether the request should pause for human methodologist approval."""
    raw_value = project_seed_payload.get("methodology_human_review")
    if raw_value is not None:
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            return raw_value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(raw_value)

    # Resume old paused sessions that were already created by a human checkpoint,
    # even if their persisted seed predates the explicit UI flag.
    if context:
        if context.get("methodology_human_review_enabled") is True:
            return True
        if context.get("human_approval_checkpoint") or context.get("human_approval_checkpoints"):
            return True
    return False


class MethodologyReviewActionRequest(BaseModel):
    """Решение методолога для paused generation."""

    comment: str | None = None


def _preview_hash(revision_results: list[dict[str, Any]]) -> str:
    payload = json.dumps(revision_results or [], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _annotation_text_from_context(context: dict[str, Any]) -> str:
    annotation = context.get("annotation")
    if isinstance(annotation, dict):
        return str(annotation.get("text") or "")
    if hasattr(annotation, "text"):
        return str(annotation.text or "")
    return ""


def _context_preview_markdown(context: dict[str, Any]) -> str:
    """Build the most useful README preview from a paused flow context."""
    markdown = normalize_markdown_display_blocks(str(context.get("markdown") or "")).strip()
    if markdown:
        return markdown

    title = str(context.get("title") or "").strip()
    annotation = _annotation_text_from_context(context).strip()
    blocks: list[str] = []
    if title:
        blocks.append(f"# {title}")
    if annotation:
        blocks.append(annotation)
    return "\n\n".join(blocks).strip()


def _markdown_outline(markdown: str) -> list[dict[str, Any]]:
    return [
        {"level": len(match.group(1)), "title": match.group(2).strip()}
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown or "", flags=re.MULTILINE)
    ]


def _markdown_section(markdown: str, marker: str) -> str:
    if not markdown:
        return ""
    lines = markdown.splitlines()
    normalized_marker = marker.lower()
    start_index: int | None = None
    start_level = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip().lower()
        if normalized_marker in title:
            start_index = index
            start_level = len(stripped) - len(stripped.lstrip("#"))
            break
    if start_index is None:
        return ""
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        stripped = lines[index].strip()
        if not stripped.startswith("#"):
            continue
        level = len(stripped) - len(stripped.lstrip("#"))
        if level <= start_level:
            end_index = index
            break
    return "\n".join(lines[start_index:end_index]).strip()


def _markdown_subsections(markdown: str, *, min_level: int = 3) -> list[dict[str, str]]:
    matches = [
        match
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown or "", flags=re.MULTILINE)
        if len(match.group(1)) >= min_level
    ]
    sections: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        end = len(markdown or "")
        for next_match in matches[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        sections.append(
            {
                "title": title,
                "markdown": (markdown or "")[match.start() : end].strip(),
            }
        )
    return sections


def _checkpoint_payload_hash(checkpoint: dict[str, Any]) -> str:
    payload = {key: value for key, value in checkpoint.items() if key != "artifact_hash"}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _is_final_checkpoint_payload(checkpoint: Any) -> bool:
    if not isinstance(checkpoint, dict):
        return False
    stage = str(checkpoint.get("stage") or "").lower()
    checkpoint_id = str(checkpoint.get("id") or "").lower()
    node_id = str(checkpoint.get("node_id") or "").lower()
    return (
        stage == "final"
        or checkpoint_id in {"quality", "evaluation"}
        or node_id in {"global_quality", "evaluation"}
    )


def _refresh_checkpoint_artifact(context: dict[str, Any]) -> None:
    """Keep the visible human-review artifact aligned with an accepted scoped preview."""
    checkpoint = context.get("human_approval_checkpoint")
    if not isinstance(checkpoint, dict):
        return

    markdown = _context_preview_markdown(context)
    artifact = dict(checkpoint.get("artifact") or {})
    stage = str(checkpoint.get("stage") or checkpoint.get("id") or "")
    title = str(context.get("title") or artifact.get("title") or "").strip()
    if title:
        artifact["title"] = title

    if stage in {"title", "annotation"}:
        artifact["annotation"] = _annotation_text_from_context(context)
    elif stage == "skeleton":
        artifact["markdown_excerpt"] = markdown
        artifact["structure_outline"] = _markdown_outline(markdown)
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = _markdown_subsections(markdown, min_level=2)
    elif stage == "theory":
        chapter = _markdown_section(markdown, "глава 2") or markdown
        artifact["markdown_excerpt"] = normalize_markdown_display_blocks(chapter)
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = _markdown_subsections(chapter)
    elif stage == "practice":
        chapter = _markdown_section(markdown, "глава 3") or markdown
        artifact["markdown_excerpt"] = normalize_markdown_display_blocks(chapter)
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = _markdown_subsections(chapter)
        artifact["dataset_files"] = [
            {"path": str(item.get("path") or ""), "bytes": len(item.get("data") or b"")}
            for item in context.get("dataset_files") or []
            if isinstance(item, dict)
        ]
    elif _is_final_checkpoint_payload(checkpoint):
        # Финальные review-паузы должны показывать методологу весь README:
        # именно этот artifact видит UI после preview/точечных правок.
        artifact["markdown_excerpt"] = markdown
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = _markdown_subsections(markdown, min_level=2)
    else:
        artifact["markdown_excerpt"] = markdown[:5000]

    checkpoint["artifact"] = artifact
    checkpoint["artifact_hash"] = _checkpoint_payload_hash(checkpoint)
    context["human_approval_checkpoint"] = checkpoint


def _current_review_action_slice(review_actions: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """Return the active pause cycle and its original action index offset."""
    start_index = 0
    for index, action in enumerate(review_actions or []):
        if isinstance(action, dict) and action.get("action") in {"approved", "rejected"}:
            start_index = index + 1
    return start_index, list(review_actions or [])[start_index:]


def _change_action_ids(review_actions: list[dict[str, Any]], *, start_index: int = 0) -> list[str]:
    ids: list[str] = []
    for offset, action in enumerate(review_actions or []):
        if not isinstance(action, dict) or action.get("action") != "changes_requested":
            continue
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        payload = details.get("change_request") if isinstance(details, dict) else None
        if not isinstance(payload, dict):
            continue
        try:
            request = MethodologistChangeRequest.model_validate(payload)
        except Exception:
            continue
        index = start_index + offset
        ids.append(ScopedRevisionExecutor.action_id_for_action(action, index, request))
    return ids


def _revision_results_for_action_ids(
    revision_results: list[dict[str, Any]],
    action_ids: list[str],
) -> list[dict[str, Any]]:
    action_id_set = {str(action_id) for action_id in action_ids if action_id}
    if not action_id_set:
        return [item for item in revision_results or [] if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for item in revision_results or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("action_id") or "") in action_id_set:
            filtered.append(item)
    return filtered


def _latest_review_action(
    review_actions: list[dict[str, Any]],
    action_name: str,
) -> dict[str, Any] | None:
    for action in reversed(review_actions or []):
        if isinstance(action, dict) and action.get("action") == action_name:
            return action
    return None


def _build_methodology_review_state(paused_session: dict[str, Any]) -> dict[str, Any]:
    """Derive review state from immutable audit actions stored in paused-session."""
    review_actions = list(paused_session.get("review_actions") or [])
    active_start_index, active_review_actions = _current_review_action_slice(review_actions)
    context = paused_session.get("context") or {}
    if _is_final_checkpoint_payload(context.get("human_approval_checkpoint")):
        _refresh_checkpoint_artifact(context)
    target_registry = build_section_target_registry(context).model_dump(mode="json")
    pending_change_ids = _change_action_ids(active_review_actions, start_index=active_start_index)

    latest_preview = _latest_review_action(active_review_actions, "preview_ready")
    latest_preview_details = latest_preview.get("details") if isinstance(latest_preview, dict) else {}
    if not isinstance(latest_preview_details, dict):
        latest_preview_details = {}
    preview_results = _revision_results_for_action_ids(
        latest_preview_details.get("revision_results") or context.get("methodology_revision_results") or [],
        pending_change_ids,
    )
    if isinstance(latest_preview_details.get("target_registry"), dict):
        target_registry = latest_preview_details["target_registry"]
    preview_markdown = str(latest_preview_details.get("preview_markdown") or "")
    preview_action_ids = [
        str(item.get("action_id"))
        for item in preview_results
        if isinstance(item, dict) and item.get("action_id")
    ]
    preview_hash = str(latest_preview_details.get("preview_hash") or _preview_hash(preview_results))
    preview_has_rejections = any(
        isinstance(item, dict) and item.get("status") == "rejected"
        for item in preview_results
    )

    approved_set: set[str] = set()
    for action in active_review_actions:
        if not isinstance(action, dict) or action.get("action") != "diff_approved":
            continue
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        approved_set.update(str(item) for item in details.get("approved_action_ids") or [] if item)
    approved_ids = [action_id for action_id in pending_change_ids if action_id in approved_set]

    pending_set = set(pending_change_ids)
    previewed_set = set(preview_action_ids)
    approved_set = set(approved_ids)
    unapproved_ids = [action_id for action_id in pending_change_ids if action_id not in approved_set]
    unapproved_set = set(unapproved_ids)
    diff_approvable_action_ids = [action_id for action_id in unapproved_ids if action_id in previewed_set]
    if not pending_set:
        review_state = "no_changes"
    elif not unapproved_set:
        review_state = "diff_approved"
    elif latest_preview and unapproved_set.issubset(previewed_set):
        review_state = "preview_ready"
    else:
        review_state = "changes_requested"

    return {
        "request_id": paused_session.get("request_id"),
        "status": paused_session.get("status", "needs_review"),
        "resume_from_index": paused_session.get("resume_from_index", 0),
        "review_state": review_state,
        "requires_diff_approval": bool(unapproved_set),
        "pending_change_ids": pending_change_ids,
        "preview_action_ids": preview_action_ids,
        "approved_action_ids": approved_ids,
        "diff_approvable_action_ids": diff_approvable_action_ids,
        "preview_hash": preview_hash,
        "preview_has_rejections": preview_has_rejections,
        "review_actions": review_actions,
        "revision_results": preview_results,
        "preview_markdown": preview_markdown or _context_preview_markdown(context),
        "target_registry": target_registry,
        "checkpoint": context.get("human_approval_checkpoint"),
        "methodology": paused_session.get("methodology"),
    }


async def _save_completed_generation(
    *,
    request_id: str,
    user_id: str,
    project_seed_payload: dict[str, Any],
    result: Any,
) -> bool:
    """Validate markdown, persist generation result and write completion logs."""
    markdown = normalize_markdown_display_blocks(result.report_json.get("markdown", ""))
    result.report_json["markdown"] = markdown
    latex_issues = collect_latex_issues(markdown)
    if latex_issues:
        issue_text = "; ".join(latex_issues[:3])
        agent_hint = build_latex_agent_hint(latex_issues)
        logger.error("❌ Ошибка валидации LaTeX: %s", issue_text)
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message="Найдены ошибки LaTeX в сгенерированном README",
            user_id=user_id,
            phase="validation",
            metadata={"issues": latex_issues[:5], "agent_hint": agent_hint},
        )
        error_msg = f"Найдены проблемы с LaTeX формулами: {issue_text}. Подсказка для агента: {agent_hint}"
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, error_msg)
        return False

    store_result(request_id, result, user_id=user_id)

    try:
        await asyncio.to_thread(
            save_generation_result,
            request_id,
            user_id,
            project_seed_payload,
            markdown,
            result.report_json.get("rubric"),
            result.report_json,
            result.report_json.get("text_stats"),
            result.report_json.get("task_plan"),
            result.report_json.get("issues"),
            result.practice_critic_issues,
            result.agent_config_versions,
            result.flow_trace,
        )
        logger.info("🗄️ Результат %s сохранён в БД", request_id)
    except Exception as db_err:
        logger.warning("⚠️ Не удалось сохранить результат в БД: %s", db_err)

    markdown_len = len(result.report_json.get("markdown", ""))
    logger.info(f"✅ Генерация завершена успешно: markdown={markdown_len} символов")
    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Генерация контента завершена успешно",
        user_id=user_id,
        phase="completion",
        metadata={
            "agent_config_versions": result.agent_config_versions,
            "practice_critic_issues": len(result.practice_critic_issues or []),
            "flow_trace": result.flow_trace,
        },
    )
    return True


async def _store_methodology_pause(
    *,
    request_id: str,
    user_id: str,
    project_seed_dict: dict[str, Any],
    track_paths: list[str],
    error: ContentGenerationError,
) -> bool:
    """Persist pause state from MethodologyGateInterrupt and expose needs_review status."""
    flow_context = getattr(error, "flow_context", None)
    flow_steps = getattr(error, "flow_steps", None)
    resume_from_index = getattr(error, "resume_from_index", None)
    if flow_context is None or resume_from_index is None:
        set_generation_status(request_id, "failed")
        store_generation_error(
            request_id,
            "Методологический gate остановил генерацию, но resume-state не был сохранен.",
        )
        return False

    flow_context["methodology_human_review_enabled"] = _methodology_human_review_enabled(
        project_seed_dict,
        flow_context,
    )
    await asyncio.to_thread(
        save_paused_generation_session,
        request_id,
        user_id=user_id,
        project_seed=project_seed_dict,
        track_paths=track_paths,
        context=flow_context,
        steps=flow_steps or [],
        resume_from_index=resume_from_index,
        methodology=get_generation_methodology(request_id),
    )
    if error.context.get("error_type") == "HumanApprovalCheckpoint":
        user_friendly_message = (
            "Генерация остановлена на контрольной точке: требуется подтверждение методолога."
        )
    else:
        user_friendly_message = (
            "Генерация остановлена методологическим gate: требуется ручная проверка перед продолжением."
        )
    await write_log_async(
        request_id=request_id,
        level="WARNING",
        message=user_friendly_message,
        user_id=user_id,
        phase=error.context.get("phase", "methodology_gate"),
        metadata={"context": error.context},
    )
    set_generation_status(request_id, "needs_review")
    store_generation_error(request_id, user_friendly_message)
    return True


async def _run_generation_background(
    request_id: str,
    user_id: str,
    project_seed_dict: dict,
    track_paths: list[str],
    temp_dir: str | None = None
) -> None:
    """
    Фоновая задача для выполнения генерации контента.
    
    Args:
        request_id: ID запроса
        user_id: ID пользователя
        project_seed_dict: Словарь с данными проекта
        track_paths: Список путей к файлам трека
        temp_dir: Временная директория для очистки
    """
    try:
        # Проверяем, не была ли задача отменена перед началом
        status = get_generation_status(request_id)
        if status == "cancelled":
            logger.info(f"🛑 Генерация отменена до начала: request_id={request_id}")
            return
        # Устанавливаем контекст для логирования
        set_request_id(request_id)
        set_user_id(user_id)

        # Устанавливаем статус in_progress
        set_generation_status(request_id, "in_progress")

        # ДИАГНОСТИКА: Логируем язык из project_seed_dict ДО создания ProjectSeed
        logger.info(f"🔍 _run_generation_background: язык из project_seed_dict: '{project_seed_dict.get('language')}'")

        # Валидируем через Pydantic
        from content_gen.models.schemas import ProjectSeed
        project_seed = ProjectSeed(**project_seed_dict)

        # ДИАГНОСТИКА: Логируем язык из project_seed ПОСЛЕ создания
        logger.info(f"🔍 _run_generation_background: язык из project_seed: '{project_seed.language}' (тип: {type(project_seed.language).__name__})")

        # Инициализируем оптимизированный LLM клиент и оркестратор
        llm_client = CachedLLMClient(
            provider="openai",
            enable_cache=True,
            enable_batching=True
        )
        human_review_enabled = bool(project_seed.methodology_human_review)
        methodology_callback = (
            (lambda payload: set_generation_methodology(request_id, payload))
            if human_review_enabled
            else None
        )
        orchestrator = Orchestrator(
            llm_client,
            methodology_progress_callback=methodology_callback,
            human_approval_enabled=human_review_enabled,
        )

        # Выполняем генерацию в отдельном потоке (синхронный код)
        raw_input = project_seed.model_dump()
        result = await asyncio.to_thread(
            orchestrator.run,
            raw_input=raw_input,
            track_files=track_paths
        )

        await _save_completed_generation(
            request_id=request_id,
            user_id=user_id,
            project_seed_payload=project_seed.model_dump(),
            result=result,
        )

    except ValidationError as e:
        logger.error(f"❌ Ошибка валидации: {str(e)}")
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка валидации: {str(e)}",
            user_id=user_id,
            phase="validation_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e), "context": e.context}
        )
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, f"Ошибка валидации: {str(e)}")

    except (LLMTimeoutError, LLMRateLimitError) as e:
        logger.error(f"⚠️ Ошибка LLM (таймаут/rate limit): {str(e)}")
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка LLM: {str(e)}",
            user_id=user_id,
            phase="llm_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e), "context": e.context}
        )
        set_generation_status(request_id, "failed")
        if isinstance(e, LLMTimeoutError):
            store_generation_error(
                request_id,
                "Генерация заняла слишком много времени (таймаут). Попробуйте снова или упростите объём проекта."
            )
        else:
            store_generation_error(request_id, f"Ошибка LLM сервиса: {str(e)}")

    except LLMAPIError as e:
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка LLM API: {str(e)}",
            user_id=user_id,
            phase="llm_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e), "context": e.context}
        )
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, f"Ошибка LLM API: {str(e)}")

    except ContentGenerationError as e:
        logger.error(f"❌ Ошибка генерации: {str(e)}", exc_info=True)

        # Улучшаем сообщение об ошибке для пользователя
        error_message = str(e)
        user_friendly_message = error_message
        error_type = e.context.get("error_type")

        if error_type in {"MethodologyGatePause", "HumanApprovalCheckpoint"}:
            await _store_methodology_pause(
                request_id=request_id,
                user_id=user_id,
                project_seed_dict=project_seed_dict,
                track_paths=track_paths,
                error=e,
            )
            return

        # Специальная обработка ошибок OpenAI API
        if "unsupported_country_region_territory" in error_message or "Country, region, or territory not supported" in error_message:
            user_friendly_message = (
                "Ошибка доступа к OpenAI API: ваш регион не поддерживается. "
                "Пожалуйста, используйте VPN или обратитесь к администратору системы."
            )
        elif "403" in error_message and "OpenAI" in error_message:
            user_friendly_message = (
                "Ошибка доступа к OpenAI API (403 Forbidden). "
                "Возможные причины: неподдерживаемый регион, проблемы с API ключом или ограничения доступа."
            )
        elif "PermissionDeniedError" in error_message or "Permission denied" in error_message.lower():
            user_friendly_message = (
                "Ошибка доступа к OpenAI API: доступ запрещен. "
                "Проверьте настройки API ключа и доступность сервиса в вашем регионе."
            )

        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка генерации: {error_message}",
            user_id=user_id,
            phase="generation_error",
            metadata={
                "error_type": type(e).__name__,
                "error_message": error_message,
                "user_friendly_message": user_friendly_message,
                "context": e.context
            }
        )
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, user_friendly_message)

    except Exception as e:
        logger.error(f"💥 Неожиданная ошибка: {str(e)}", exc_info=True)

        # Улучшаем сообщение об ошибке для пользователя
        error_message = str(e)
        user_friendly_message = f"Внутренняя ошибка сервера: {error_message}"

        # Специальная обработка ошибок OpenAI API в общем Exception
        error_str_lower = error_message.lower()
        if "unsupported_country_region_territory" in error_str_lower or "country, region, or territory not supported" in error_str_lower:
            user_friendly_message = (
                "Ошибка доступа к OpenAI API: ваш регион не поддерживается. "
                "Пожалуйста, используйте VPN или обратитесь к администратору системы."
            )
        elif "403" in error_message and ("openai" in error_str_lower or "permission" in error_str_lower):
            user_friendly_message = (
                "Ошибка доступа к OpenAI API (403 Forbidden). "
                "Возможные причины: неподдерживаемый регион, проблемы с API ключом или ограничения доступа."
            )
        elif "permissiondeniederror" in error_str_lower or "permission denied" in error_str_lower:
            user_friendly_message = (
                "Ошибка доступа к OpenAI API: доступ запрещен. "
                "Проверьте настройки API ключа и доступность сервиса в вашем регионе."
            )

        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Неожиданная ошибка: {error_message}",
            user_id=user_id,
            phase="unexpected_error",
            metadata={
                "error_type": type(e).__name__,
                "error_message": error_message,
                "user_friendly_message": user_friendly_message
            }
        )
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, user_friendly_message)

    finally:
        # Удаляем задачу из реестра
        unregister_generation_task(request_id)

        # Очищаем временные файлы
        if temp_dir:
            from api.utils.file_handler import cleanup_temp_files
            await cleanup_temp_files(temp_dir)


async def _resume_generation_background(
    request_id: str,
    user_id: str,
    paused_session: dict[str, Any],
    review_comment: str | None = None,
) -> None:
    """Resume generation after a methodologist approval from the saved flow context."""
    try:
        status = get_generation_status(request_id)
        if status == "cancelled":
            logger.info(f"🛑 Resume отменен до старта: request_id={request_id}")
            return

        set_request_id(request_id)
        set_user_id(user_id)
        set_generation_status(request_id, "in_progress")

        context = paused_session["context"]
        stored_review_actions = paused_session.get("review_actions") or []
        if stored_review_actions:
            context["methodology_review_actions"] = list(stored_review_actions)
        elif review_comment:
            context.setdefault("methodology_review_actions", []).append(
                {
                    "action": "approved",
                    "comment": review_comment,
                    "user_id": user_id,
                }
            )

        llm_client = CachedLLMClient(
            provider="openai",
            enable_cache=True,
            enable_batching=True,
        )
        human_review_enabled = _methodology_human_review_enabled(
            paused_session.get("project_seed") or {},
            context,
        )
        methodology_callback = (
            (lambda payload: set_generation_methodology(request_id, payload))
            if human_review_enabled
            else None
        )
        orchestrator = Orchestrator(
            llm_client,
            methodology_progress_callback=methodology_callback,
            human_approval_enabled=human_review_enabled,
        )

        result = await asyncio.to_thread(
            orchestrator.resume_from_pause,
            context=context,
            resume_from_index=int(paused_session.get("resume_from_index", 0)),
            previous_steps=paused_session.get("steps") or [],
        )

        saved = await _save_completed_generation(
            request_id=request_id,
            user_id=user_id,
            project_seed_payload=paused_session.get("project_seed") or {},
            result=result,
        )
        if saved:
            await asyncio.to_thread(mark_paused_generation_completed, request_id)

    except ContentGenerationError as e:
        logger.error(f"❌ Ошибка resume генерации: {str(e)}", exc_info=True)
        if e.context.get("error_type") in {"MethodologyGatePause", "HumanApprovalCheckpoint"}:
            await _store_methodology_pause(
                request_id=request_id,
                user_id=user_id,
                project_seed_dict=paused_session.get("project_seed") or {},
                track_paths=paused_session.get("track_paths") or [],
                error=e,
            )
            return

        set_generation_status(request_id, "failed")
        store_generation_error(request_id, str(e))
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка продолжения генерации: {str(e)}",
            user_id=user_id,
            phase="resume_error",
            metadata={"error_type": type(e).__name__, "context": e.context},
        )
    except Exception as e:
        logger.error(f"💥 Неожиданная ошибка resume: {str(e)}", exc_info=True)
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, f"Ошибка продолжения генерации: {str(e)}")
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Неожиданная ошибка продолжения генерации: {str(e)}",
            user_id=user_id,
            phase="resume_unexpected_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e)},
        )
    finally:
        unregister_generation_task(request_id)


@router.post("/generate", response_model=GenerateStartResponse)
@limiter.limit("10/minute")
async def generate(
    request: Request,
    track_files: list[UploadFile] | None = File(None),
    user: dict = Depends(get_current_user)
):
    """
    Запускает асинхронную генерацию контента учебного проекта.
    
    Args:
        request: FastAPI Request объект (для rate limiting и получения данных)
        track_files: Legacy список файлов трека; runtime использует curriculum_context
        user: Данные пользователя из аутентификации
        
    Returns:
        request_id и статус pending
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")

    # Устанавливаем контекст для логирования
    set_request_id(request_id)
    set_user_id(user_id)

    # Устанавливаем начальный статус
    set_generation_status(request_id, "pending")

    # Логируем начало генерации
    logger.info(f"📝 Начало генерации контента для пользователя {user_id}")

    # Логируем метаданные запроса (до парсинга seed_data)
    # Обрабатываем track_files: может быть списком или async_generator
    track_files_list = []
    if track_files:
        # Если это async_generator, преобразуем в список
        if hasattr(track_files, '__aiter__'):
            track_files_list = [f async for f in track_files]
        elif isinstance(track_files, list):
            track_files_list = track_files
        else:
            # Пытаемся преобразовать в список
            try:
                track_files_list = list(track_files)
            except (TypeError, ValueError):
                track_files_list = []

    file_count = len(track_files_list)

    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Начало генерации контента",
        user_id=user_id,
        phase="initialization",
        metadata={
            "file_count": file_count,
            "legacy_track_files_ignored": file_count > 0,
        }
    )

    try:
        # Парсим seed из FormData или JSON
        import json
        content_type = request.headers.get("content-type", "")

        if "multipart/form-data" in content_type:
            # FormData - получаем seed как строку
            form = await request.form()
            seed_str = form.get("seed")
            if not seed_str:
                raise HTTPException(status_code=400, detail="Не указаны данные проекта (seed)")
            try:
                seed_data = json.loads(seed_str)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="Ошибка парсинга JSON из FormData")
        else:
            # JSON body
            try:
                body = await request.json()
                seed_data = body.get("seed", {})
                if not seed_data:
                    raise HTTPException(status_code=400, detail="Не указаны данные проекта (seed)")
            except:
                raise HTTPException(status_code=400, detail="Не указаны данные проекта (seed)")

        # Подготавливаем метаданные для логирования (после получения seed_data)
        seed_metadata = {}
        if seed_data:
            # Логируем только метаданные, без чувствительных данных
            from api.utils.data_masking import mask_dict
            seed_metadata = mask_dict({
                "language": seed_data.get("language"),
                "track": seed_data.get("track"),
                "project_type": seed_data.get("project_type"),
                "learning_outcomes_count": len(seed_data.get("learning_outcomes", [])),
                "thematic_blocks_count": len(seed_data.get("thematic_blocks", [])),
                "methodology_human_review": seed_data.get("methodology_human_review", False),
            })

        # Логируем метаданные seed
        await write_log_async(
            request_id=request_id,
            level="INFO",
            message="Данные проекта получены",
            user_id=user_id,
            phase="initialization",
            metadata={
                "seed_metadata": seed_metadata,
            }
        )

        # Логируем размер данных
        seed_size = len(str(seed_data))
        # ДИАГНОСТИКА: Логируем язык из seed_data ДО создания ProjectSeed
        logger.info(f"🔍 generate endpoint: язык из seed_data: '{seed_data.get('language')}'")

        # Валидируем через Pydantic
        from content_gen.models.schemas import ProjectSeed
        try:
            project_seed = ProjectSeed(**seed_data)

            # ДИАГНОСТИКА: Логируем язык из project_seed ПОСЛЕ создания
            logger.info(f"🔍 generate endpoint: язык из project_seed: '{project_seed.language}' (тип: {type(project_seed.language).__name__})")
        except Exception as e:
            # Логируем ошибку валидации
            await write_log_async(
                request_id=request_id,
                level="ERROR",
                message=f"Ошибка валидации seed данных: {str(e)}",
                user_id=user_id,
                phase="validation",
                metadata={
                    "error": str(e),
                    "seed_size": seed_size,
                }
            )
            raise HTTPException(status_code=400, detail=f"Ошибка валидации данных: {str(e)}")

        # Legacy track files больше не участвуют в runtime-контексте.
        track_paths = []
        temp_dir = None

        # Запускаем генерацию в фоне
        project_seed_dict = project_seed.model_dump()
        # Создаем задачу и регистрируем её для возможности отмены
        generation_task = asyncio.create_task(
            _run_generation_background(
                request_id=request_id,
                user_id=user_id,
                project_seed_dict=project_seed_dict,
                track_paths=track_paths,
                temp_dir=temp_dir
            )
        )
        register_generation_task(request_id, generation_task)

        # Сразу возвращаем request_id
        return GenerateStartResponse(
                request_id=request_id,
            status="pending"
        )

    except ValidationError as e:
        # Ошибка валидации - 400
        logger.error(f"❌ Ошибка валидации: {str(e)}")
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, f"Ошибка валидации: {str(e)}")
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка валидации: {str(e)}",
            user_id=user_id,
            phase="validation_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e), "context": e.context}
        )
        raise HTTPException(status_code=400, detail=f"Ошибка валидации: {str(e)}")

    except Exception as e:
        # Неожиданная ошибка при подготовке данных
        logger.error(f"💥 Неожиданная ошибка при подготовке: {str(e)}", exc_info=True)
        set_generation_status(request_id, "failed")
        store_generation_error(request_id, f"Ошибка при подготовке данных: {str(e)}")
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Неожиданная ошибка при подготовке: {str(e)}",
            user_id=user_id,
            phase="unexpected_error",
            metadata={"error_type": type(e).__name__, "error_message": str(e)}
        )
        raise HTTPException(status_code=500, detail="Внутренняя ошибка сервера")


@router.post("/generation/start")
async def start_generation_stepwise(
    request: StepwiseGenerationStartRequest,
    user: dict = Depends(get_current_user),
):
    """Совместимый stepwise-start endpoint для legacy UI/tests."""
    request_id = str(uuid.uuid4())
    didactics_context, agent_trace = compose_didactics_context("intro_rules")
    _stepwise_generation_sessions[request_id] = {
        "user_id": user.get("id", "anonymous"),
        "seed": request.seed,
        "stepwise": request.stepwise,
        "didactics_context": didactics_context,
        "agent_trace": agent_trace,
    }
    return {"request_id": request_id, "status": "pending"}


@router.post("/generation/{request_id}/continue")
async def continue_generation_stepwise(
    request_id: str,
    user: dict = Depends(get_current_user),
):
    """Совместимый stepwise-continue endpoint с didactics metadata."""
    session = _stepwise_generation_sessions.get(request_id)
    if not session:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден")
    if session.get("user_id") != user.get("id", "anonymous"):
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    trace = get_didactics_trace()
    return {
        "request_id": request_id,
        "status": "completed",
        "metadata": {
            "didactics": {
                "trace": trace,
                "agent_trace": session.get("agent_trace", {}),
                "has_context": bool(session.get("didactics_context")),
            }
        },
    }


@router.get("/generate/status/{request_id}", response_model=GenerationStatusResponse)
async def get_generation_status_endpoint(
    request_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Получает статус генерации контента.
    
    Args:
        request_id: ID запроса генерации
        user: Данные пользователя
        
    Returns:
        Статус генерации и результат (если завершена)
    """
    status = get_generation_status(request_id)

    if status is None:
        paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
        if paused_session:
            status = "needs_review"
            set_generation_status(request_id, status)
            if paused_session.get("methodology"):
                set_generation_methodology(request_id, paused_session["methodology"])
        else:
            raise HTTPException(status_code=404, detail="Запрос генерации не найден")

    if status == "completed":
        # Получаем результат из кэша
        cached = get_result(request_id)
        if cached:
            report_json = cached.get("report_json")
            if report_json is None:
                logger.warning(f"⚠️ report_json отсутствует в кэше для request_id={request_id}")
                return GenerationStatusResponse(
                    request_id=request_id,
                    status="failed",
                    error="Результат генерации поврежден"
                )
            if isinstance(report_json, dict):
                report_json = dict(report_json)
                if report_json.get("markdown"):
                    report_json["markdown"] = normalize_markdown_display_blocks(report_json["markdown"])
                if report_json.get("translated_markdown"):
                    report_json["translated_markdown"] = normalize_markdown_display_blocks(report_json["translated_markdown"])
            logger.debug(f"✅ Возвращаем результат для request_id={request_id}, report_json keys: {list(report_json.keys()) if isinstance(report_json, dict) else 'not a dict'}")
            return GenerationStatusResponse(
                request_id=request_id,
                status=status,
                result=report_json,
                warnings=cached.get("warnings", []),
                methodology=(
                    report_json.get("methodology_gate") or cached.get("methodology") or get_generation_methodology(request_id)
                    if isinstance(report_json, dict)
                    else cached.get("methodology")
                ),
            )
        else:
            # Результат не найден, но статус completed - возможно истек срок
            logger.warning(f"⚠️ Результат не найден в кэше для request_id={request_id}, хотя статус completed")
            return GenerationStatusResponse(
                request_id=request_id,
                status="failed",
                error="Результат генерации истек или был удален"
            )
    elif status == "failed":
        error = get_generation_error(request_id)
        return GenerationStatusResponse(
            request_id=request_id,
            status=status,
            error=error or "Неизвестная ошибка",
            methodology=get_generation_methodology(request_id),
        )
    elif status == "needs_review":
        error = get_generation_error(request_id)
        return GenerationStatusResponse(
            request_id=request_id,
            status=status,
            error=error or "Требуется ручная методологическая проверка",
            methodology=get_generation_methodology(request_id),
        )
    elif status == "cancelled":
        error = get_generation_error(request_id)
        return GenerationStatusResponse(
            request_id=request_id,
            status=status,
            error=error or "Генерация была остановлена пользователем",
            methodology=get_generation_methodology(request_id),
        )
    else:
        # pending или in_progress
        return GenerationStatusResponse(
            request_id=request_id,
            status=status,
            methodology=get_generation_methodology(request_id),
        )


@router.post("/generate/review/{request_id}/approve", response_model=GenerateStartResponse)
async def approve_methodology_review(
    request_id: str,
    request: MethodologyReviewActionRequest,
    user: dict = Depends(get_current_user),
):
    """Approve a paused methodology gate and continue generation from the saved node."""
    status = get_generation_status(request_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден")
    if status != "needs_review":
        raise HTTPException(status_code=400, detail=f"Генерация не ожидает методолога: статус {status}")

    paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
    if not paused_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")

    user_id = user.get("id", "anonymous")
    if paused_session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    review_state = _build_methodology_review_state(paused_session)
    if review_state["requires_diff_approval"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Перед продолжением нужно выполнить preview и подтвердить diff правок методолога",
                "review_state": review_state["review_state"],
                "pending_change_ids": review_state["pending_change_ids"],
            },
        )

    approved_session = await asyncio.to_thread(
        mark_paused_generation_approved,
        request_id,
        user_id=user_id,
        comment=request.comment,
    )
    if not approved_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")

    generation_task = asyncio.create_task(
        _resume_generation_background(
            request_id=request_id,
            user_id=user_id,
            paused_session=approved_session,
            review_comment=request.comment,
        )
    )
    register_generation_task(request_id, generation_task)
    set_generation_status(request_id, "in_progress")
    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Методолог подтвердил продолжение генерации",
        user_id=user_id,
        phase="methodology_review",
        metadata={"comment": request.comment or ""},
    )
    return GenerateStartResponse(request_id=request_id, status="in_progress")


@router.post("/generate/review/{request_id}/reject")
async def reject_methodology_review(
    request_id: str,
    request: MethodologyReviewActionRequest,
    user: dict = Depends(get_current_user),
):
    """Reject a paused methodology gate and stop the generation job."""
    status = get_generation_status(request_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден")
    if status != "needs_review":
        raise HTTPException(status_code=400, detail=f"Генерация не ожидает методолога: статус {status}")

    paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
    if not paused_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")

    user_id = user.get("id", "anonymous")
    if paused_session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    rejected = await asyncio.to_thread(
        mark_paused_generation_rejected,
        request_id,
        user_id=user_id,
        comment=request.comment,
    )
    if not rejected:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")
    message = "Генерация отклонена методологом"
    if request.comment:
        message = f"{message}: {request.comment}"
    set_generation_status(request_id, "failed")
    store_generation_error(request_id, message)
    await write_log_async(
        request_id=request_id,
        level="WARNING",
        message=message,
        user_id=user_id,
        phase="methodology_review",
        metadata={"comment": request.comment or ""},
    )
    return {"success": True, "status": "failed", "message": message}


@router.get("/generate/review/{request_id}")
async def get_methodology_review_state(
    request_id: str,
    user: dict = Depends(get_current_user),
):
    """Return durable methodology review state for UI history and target selection."""
    paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
    if not paused_session:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден или не ожидает методолога")

    user_id = user.get("id", "anonymous")
    if paused_session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    return _build_methodology_review_state(paused_session)


@router.post("/generate/review/{request_id}/preview-changes")
async def preview_methodology_changes(
    request_id: str,
    user: dict = Depends(get_current_user),
):
    """Run pending scoped revisions on a copied paused context and return diff previews."""
    status = get_generation_status(request_id)
    if status is not None and status != "needs_review":
        raise HTTPException(status_code=400, detail=f"Генерация не ожидает методолога: статус {status}")

    paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
    if not paused_session:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден или не ожидает методолога")

    user_id = user.get("id", "anonymous")
    if paused_session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    active_start_index, active_review_actions = _current_review_action_slice(paused_session.get("review_actions") or [])
    active_change_ids = _change_action_ids(active_review_actions, start_index=active_start_index)
    preview_context = copy.deepcopy(paused_session.get("context") or {})
    preview_context["methodology_review_actions"] = list(paused_session.get("review_actions") or [])
    llm_client = CachedLLMClient(provider="openai", enable_cache=True, enable_batching=True)
    executor = ScopedRevisionExecutor(llm_client)
    results = await asyncio.to_thread(
        executor.apply_pending_change_requests,
        preview_context,
        raise_on_rejected=False,
    )
    _refresh_checkpoint_artifact(preview_context)
    all_revision_results = preview_context.get("methodology_revision_results") or [
        result.model_dump(mode="json") for result in results
    ]
    payload = _revision_results_for_action_ids(all_revision_results, active_change_ids)
    target_registry = build_section_target_registry(preview_context).model_dump(mode="json")
    preview_markdown = _context_preview_markdown(preview_context)
    preview_hash = _preview_hash(payload)
    saved_session = await asyncio.to_thread(
        record_paused_generation_preview,
        request_id,
        user_id=user_id,
        revision_results=payload,
        target_registry=target_registry,
        preview_hash=preview_hash,
        preview_context=preview_context,
        preview_markdown=preview_markdown,
    )
    if not saved_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")
    review_state = _build_methodology_review_state(saved_session)
    review_state["checkpoint"] = preview_context.get("human_approval_checkpoint")
    review_state["preview_markdown"] = preview_markdown
    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Предпросмотр методологических правок выполнен",
        user_id=user_id,
        phase="methodology_review",
        metadata={"revision_results": payload, "preview_hash": preview_hash},
    )
    return {
        "success": True,
        **review_state,
        "status": "needs_review",
        "preview_hash": preview_hash,
        "revision_results": payload,
        "target_registry": target_registry,
        "preview_markdown": preview_markdown,
    }


@router.post("/generate/review/{request_id}/approve-diff")
async def approve_methodology_diff(
    request_id: str,
    request: MethodologyReviewActionRequest,
    user: dict = Depends(get_current_user),
):
    """Approve the latest persisted preview before generation resume."""
    status = get_generation_status(request_id)
    if status is not None and status != "needs_review":
        raise HTTPException(status_code=400, detail=f"Генерация не ожидает методолога: статус {status}")

    paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
    if not paused_session:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден или не ожидает методолога")

    user_id = user.get("id", "anonymous")
    if paused_session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    review_state = _build_methodology_review_state(paused_session)
    if review_state["review_state"] == "no_changes":
        return {
            "success": True,
            "status": "needs_review",
            "review_state": "no_changes",
            "message": "Нет pending правок для подтверждения.",
        }
    if review_state["review_state"] != "preview_ready":
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Перед подтверждением diff нужно выполнить актуальный preview",
                "review_state": review_state["review_state"],
                "pending_change_ids": review_state["pending_change_ids"],
            },
        )
    if review_state["preview_has_rejections"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Diff содержит отклоненные правки. Нельзя подтверждать до исправления запросов.",
                "revision_results": review_state["revision_results"],
            },
        )

    saved_session = await asyncio.to_thread(
        mark_paused_generation_diff_approved,
        request_id,
        user_id=user_id,
        approved_action_ids=review_state.get("diff_approvable_action_ids") or review_state["pending_change_ids"],
        preview_hash=review_state["preview_hash"],
        comment=request.comment,
    )
    if not saved_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")

    next_state = _build_methodology_review_state(saved_session)
    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Методолог подтвердил diff правок",
        user_id=user_id,
        phase="methodology_review",
        metadata={
            "approved_action_ids": next_state["approved_action_ids"],
            "preview_hash": next_state["preview_hash"],
            "comment": request.comment or "",
        },
    )
    return {
        "success": True,
        "status": "needs_review",
        "message": "Diff правок подтвержден. Теперь можно продолжить генерацию.",
        **next_state,
    }


@router.post("/generate/review/{request_id}/request-changes")
async def request_methodology_changes(
    request_id: str,
    request: MethodologistChangeRequest,
    user: dict = Depends(get_current_user),
):
    """Record a scoped change request while keeping the generation paused."""
    status = get_generation_status(request_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден")
    if status != "needs_review":
        raise HTTPException(status_code=400, detail=f"Генерация не ожидает методолога: статус {status}")

    paused_session = await asyncio.to_thread(load_paused_generation_session, request_id)
    if not paused_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")

    user_id = user.get("id", "anonymous")
    if paused_session.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Нет доступа к запросу генерации")

    conflicts = validate_methodologist_change_request(request)
    conflict_payload = [conflict.model_dump(mode="json") for conflict in conflicts]
    if has_hard_conflicts(conflicts):
        await write_log_async(
            request_id=request_id,
            level="WARNING",
            message="Запрос правок методолога отклонен hard guard",
            user_id=user_id,
            phase="methodology_review",
            metadata={
                "change_request": request.model_dump(mode="json"),
                "conflicts": conflict_payload,
            },
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Запрос правок конфликтует с hard rules генератора",
                "conflicts": conflict_payload,
            },
        )

    saved_session = await asyncio.to_thread(
        record_paused_generation_change_request,
        request_id,
        user_id=user_id,
        change_request=request.model_dump(mode="json"),
        conflicts=conflict_payload,
    )
    if not saved_session:
        raise HTTPException(status_code=410, detail="Состояние продолжения истекло или недоступно")

    review_state = _build_methodology_review_state(saved_session)
    message = "Методолог запросил правки. Генерация остается на паузе до подтверждения."
    set_generation_status(request_id, "needs_review")
    store_generation_error(request_id, message)
    await write_log_async(
        request_id=request_id,
        level="INFO",
        message=message,
        user_id=user_id,
        phase="methodology_review",
        metadata={
            "change_request": request.model_dump(mode="json"),
            "conflicts": conflict_payload,
            "review_actions_count": len(saved_session.get("review_actions") or []),
        },
    )
    return {
        "success": True,
        "status": "needs_review",
        "message": message,
        "change_request": request.model_dump(mode="json"),
        "conflicts": conflict_payload,
        **review_state,
    }


@router.post("/generate/cancel/{request_id}")
async def cancel_generation_endpoint(
    request_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Останавливает активную генерацию контента.
    
    Args:
        request_id: ID запроса генерации
        user: Данные пользователя
        
    Returns:
        Результат операции отмены
    """
    status = get_generation_status(request_id)

    if status is None:
        raise HTTPException(status_code=404, detail="Запрос генерации не найден")

    if status in ("completed", "failed", "cancelled"):
        raise HTTPException(
            status_code=400,
            detail=f"Невозможно остановить генерацию: статус уже {status}"
        )

    success = cancel_generation_task(request_id)

    if success:
        logger.info(f"🛑 Генерация остановлена пользователем {user.get('id')}: request_id={request_id}")
        await write_log_async(
            request_id=request_id,
            level="INFO",
            message="Генерация остановлена пользователем",
            user_id=user.get("id", "anonymous"),
            phase="cancelled",
            metadata={"cancelled_by": user.get("id", "anonymous")}
        )
        return {"success": True, "message": "Генерация успешно остановлена"}
    else:
        raise HTTPException(
            status_code=500,
            detail="Не удалось остановить генерацию"
        )
