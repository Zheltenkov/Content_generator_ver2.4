"""Coordinator for generation background run and resume execution."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from api.db.generation_results_db import save_generation_result
from api.db.logging_db import write_log_async
from api.db.paused_generation_db import mark_paused_generation_completed, save_paused_generation_session
from api.utils.file_handler import cleanup_temp_files
from api.utils.logger import get_logger
from api.utils.logging_context import set_request_id, set_user_id
from api.utils.result_cache import (
    get_generation_methodology,
    get_generation_status,
    set_generation_methodology,
    set_generation_status,
    store_generation_error,
    store_result,
    unregister_generation_task,
)
from content_gen.exceptions import (
    ContentGenerationError,
    LLMAPIError,
    LLMRateLimitError,
    LLMTimeoutError,
    ValidationError,
)
from content_gen.llm.cached_client import CachedLLMClient
from content_gen.models.schemas import ProjectSeed
from content_gen.orchestrator import Orchestrator

from .generation_failure_handler import GenerationFailureHandler
from .generation_pause_persistence import MethodologyPausePersister
from .generation_result_persistence import GenerationResultPersister
from .methodology_review_artifacts import methodology_human_review_enabled

logger = get_logger("generation")


class GenerationResumeService:
    """Run generation and resume jobs; delegate persistence and failure policy."""

    def __init__(
        self,
        *,
        status_getter: Callable[[str], str | None] = get_generation_status,
        status_setter: Callable[[str, str], Any] = set_generation_status,
        methodology_getter: Callable[[str], dict[str, Any] | None] = get_generation_methodology,
        methodology_setter: Callable[[str, dict[str, Any]], Any] = set_generation_methodology,
        error_store: Callable[[str, str], Any] = store_generation_error,
        result_store: Callable[..., Any] = store_result,
        task_unregister: Callable[[str], Any] = unregister_generation_task,
        result_saver: Callable[..., Any] = save_generation_result,
        paused_saver: Callable[..., Any] = save_paused_generation_session,
        paused_completed_marker: Callable[[str], Any] = mark_paused_generation_completed,
        log_writer: Callable[..., Awaitable[Any]] = write_log_async,
        llm_factory: Callable[[], Any] | None = None,
        orchestrator_cls: type[Orchestrator] = Orchestrator,
        temp_cleanup: Callable[[str], Awaitable[Any]] = cleanup_temp_files,
        completed_saver: Callable[..., Awaitable[bool]] | None = None,
        result_persister: GenerationResultPersister | None = None,
        pause_persister: MethodologyPausePersister | None = None,
        failure_handler: GenerationFailureHandler | None = None,
    ) -> None:
        self._status_getter = status_getter
        self._status_setter = status_setter
        self._methodology_setter = methodology_setter
        self._task_unregister = task_unregister
        self._paused_completed_marker = paused_completed_marker
        self._llm_factory = llm_factory or (
            lambda: CachedLLMClient(enable_cache=True, enable_batching=True)
        )
        self._orchestrator_cls = orchestrator_cls
        self._temp_cleanup = temp_cleanup
        self._completed_saver = completed_saver
        self._result_persister = result_persister or GenerationResultPersister(
            status_setter=status_setter,
            error_store=error_store,
            result_store=result_store,
            result_saver=result_saver,
            log_writer=log_writer,
        )
        self._pause_persister = pause_persister or MethodologyPausePersister(
            status_setter=status_setter,
            error_store=error_store,
            methodology_getter=methodology_getter,
            paused_saver=paused_saver,
            log_writer=log_writer,
        )
        self._failure_handler = failure_handler or GenerationFailureHandler(
            status_setter=status_setter,
            error_store=error_store,
            log_writer=log_writer,
            pause_persister=self._pause_persister,
        )

    async def save_completed_generation(
        self,
        *,
        request_id: str,
        user_id: str,
        project_seed_payload: dict[str, Any],
        result: Any,
    ) -> bool:
        """Compatibility entrypoint for completed result persistence."""
        return await self._result_persister.save_completed_generation(
            request_id=request_id,
            user_id=user_id,
            project_seed_payload=project_seed_payload,
            result=result,
        )

    async def store_methodology_pause(
        self,
        *,
        request_id: str,
        user_id: str,
        project_seed_dict: dict[str, Any],
        track_paths: list[str],
        error: ContentGenerationError,
    ) -> bool:
        """Compatibility entrypoint for methodology pause persistence."""
        return await self._pause_persister.store_methodology_pause(
            request_id=request_id,
            user_id=user_id,
            project_seed_dict=project_seed_dict,
            track_paths=track_paths,
            error=error,
        )

    async def run_generation_background(
        self,
        request_id: str,
        user_id: str,
        project_seed_dict: dict[str, Any],
        track_paths: list[str],
        temp_dir: str | None = None,
    ) -> None:
        """Run full generation in the background."""
        try:
            status = self._status_getter(request_id)
            if status == "cancelled":
                logger.info("🛑 Генерация отменена до начала: request_id=%s", request_id)
                return
            set_request_id(request_id)
            set_user_id(user_id)
            self._status_setter(request_id, "in_progress")

            logger.info("🔍 _run_generation_background: язык из project_seed_dict: %r", project_seed_dict.get("language"))
            project_seed = ProjectSeed(**project_seed_dict)
            logger.info(
                "🔍 _run_generation_background: язык из project_seed: %r (тип: %s)",
                project_seed.language,
                type(project_seed.language).__name__,
            )

            result = await asyncio.to_thread(
                self._build_orchestrator(
                    human_review_enabled=bool(project_seed.methodology_human_review),
                    request_id=request_id,
                ).run,
                raw_input=project_seed.model_dump(),
                track_files=track_paths,
            )

            await self._save_completed_result(
                request_id=request_id,
                user_id=user_id,
                project_seed_payload=project_seed.model_dump(),
                result=result,
            )
        except ValidationError as exc:
            await self._failure_handler.handle_validation_error(request_id, user_id, exc)
        except (LLMTimeoutError, LLMRateLimitError) as exc:
            await self._failure_handler.handle_llm_timeout_or_rate_limit(request_id, user_id, exc)
        except LLMAPIError as exc:
            await self._failure_handler.handle_llm_api_error(request_id, user_id, exc)
        except ContentGenerationError as exc:
            await self._failure_handler.handle_content_generation_error(
                request_id=request_id,
                user_id=user_id,
                project_seed_dict=project_seed_dict,
                track_paths=track_paths,
                error=exc,
            )
        except Exception as exc:  # noqa: BLE001
            await self._failure_handler.handle_unexpected_error(request_id, user_id, exc)
        finally:
            self._task_unregister(request_id)
            if temp_dir:
                await self._temp_cleanup(temp_dir)

    async def resume_generation_background(
        self,
        request_id: str,
        user_id: str,
        paused_session: dict[str, Any],
        review_comment: str | None = None,
    ) -> None:
        """Resume generation after methodologist approval from saved flow context."""
        try:
            status = self._status_getter(request_id)
            if status == "cancelled":
                logger.info("🛑 Resume отменен до старта: request_id=%s", request_id)
                return

            set_request_id(request_id)
            set_user_id(user_id)
            self._status_setter(request_id, "in_progress")

            context = paused_session["context"]
            self._attach_review_actions(context, paused_session, review_comment, user_id)
            human_review_enabled = methodology_human_review_enabled(
                paused_session.get("project_seed") or {},
                context,
            )
            result = await asyncio.to_thread(
                self._build_orchestrator(
                    human_review_enabled=human_review_enabled,
                    request_id=request_id,
                ).resume_from_pause,
                context=context,
                resume_from_index=int(paused_session.get("resume_from_index", 0)),
                previous_steps=paused_session.get("steps") or [],
            )

            saved = await self._save_completed_result(
                request_id=request_id,
                user_id=user_id,
                project_seed_payload=paused_session.get("project_seed") or {},
                result=result,
            )
            if saved:
                await asyncio.to_thread(self._paused_completed_marker, request_id)
        except ContentGenerationError as exc:
            await self._failure_handler.handle_resume_content_error(
                request_id=request_id,
                user_id=user_id,
                paused_session=paused_session,
                error=exc,
            )
        except Exception as exc:  # noqa: BLE001
            await self._failure_handler.handle_unexpected_error(
                request_id,
                user_id,
                exc,
                phase="resume_unexpected_error",
                message_prefix="Неожиданная ошибка продолжения генерации",
                error_prefix="Ошибка продолжения генерации",
            )
        finally:
            self._task_unregister(request_id)

    async def _save_completed_result(
        self,
        *,
        request_id: str,
        user_id: str,
        project_seed_payload: dict[str, Any],
        result: Any,
    ) -> bool:
        """Use injected compatibility saver when a router-level test monkeypatches it."""
        if self._completed_saver is not None:
            return await self._completed_saver(
                request_id=request_id,
                user_id=user_id,
                project_seed_payload=project_seed_payload,
                result=result,
            )
        return await self.save_completed_generation(
            request_id=request_id,
            user_id=user_id,
            project_seed_payload=project_seed_payload,
            result=result,
        )

    def _build_orchestrator(self, *, human_review_enabled: bool, request_id: str) -> Orchestrator:
        """Create an orchestrator with optional methodology progress callback."""
        llm_client = self._llm_factory()
        methodology_callback = (
            (lambda payload: self._methodology_setter(request_id, payload))
            if human_review_enabled
            else None
        )
        return self._orchestrator_cls(
            llm_client,
            methodology_progress_callback=methodology_callback,
            human_approval_enabled=human_review_enabled,
        )

    @staticmethod
    def _attach_review_actions(
        context: dict[str, Any],
        paused_session: dict[str, Any],
        review_comment: str | None,
        user_id: str,
    ) -> None:
        """Attach durable review audit actions to resumed flow context."""
        stored_review_actions = paused_session.get("review_actions") or []
        if stored_review_actions:
            context["methodology_review_actions"] = list(stored_review_actions)
        elif review_comment:
            context.setdefault("methodology_review_actions", []).append(
                {"action": "approved", "comment": review_comment, "user_id": user_id}
            )
