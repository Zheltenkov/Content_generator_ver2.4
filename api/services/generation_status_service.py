"""Application service for generation status/result state."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from api.schemas import GenerationStatusResponse
from content_gen.utils.markdown_display_normalizer import normalize_markdown_display_blocks

from .generation_errors import GenerationServiceError


class GenerationStatusService:
    """Resolve generation status from volatile cache, paused sessions and results."""

    def __init__(
        self,
        *,
        status_getter: Callable[[str], str | None],
        status_setter: Callable[[str, str], Any],
        result_getter: Callable[[str], dict[str, Any] | None],
        error_getter: Callable[[str], str | None],
        task_canceller: Callable[[str], bool],
        methodology_getter: Callable[[str], dict[str, Any] | None],
        methodology_setter: Callable[[str, dict[str, Any]], Any],
        paused_loader: Callable[[str], dict[str, Any] | None],
        log_writer: Callable[..., Awaitable[Any]],
        logger: Any,
    ) -> None:
        self._status_getter = status_getter
        self._status_setter = status_setter
        self._result_getter = result_getter
        self._error_getter = error_getter
        self._task_canceller = task_canceller
        self._methodology_getter = methodology_getter
        self._methodology_setter = methodology_setter
        self._paused_loader = paused_loader
        self._log_writer = log_writer
        self._logger = logger

    async def get_status(self, request_id: str) -> GenerationStatusResponse:
        """Return current status and result payload when generation is complete."""
        status = self._status_getter(request_id)

        if status is None:
            paused_session = await asyncio.to_thread(self._paused_loader, request_id)
            if paused_session:
                status = "needs_review"
                self._status_setter(request_id, status)
                if paused_session.get("methodology"):
                    self._methodology_setter(request_id, paused_session["methodology"])
            else:
                raise GenerationServiceError(404, "Запрос генерации не найден")

        if status == "completed":
            return self._completed_response(request_id, status)
        if status == "failed":
            return GenerationStatusResponse(
                request_id=request_id,
                status=status,
                error=self._error_getter(request_id) or "Неизвестная ошибка",
                methodology=self._methodology_getter(request_id),
            )
        if status == "needs_review":
            return GenerationStatusResponse(
                request_id=request_id,
                status=status,
                error=self._error_getter(request_id) or "Требуется ручная методологическая проверка",
                methodology=self._methodology_getter(request_id),
            )
        if status == "cancelled":
            return GenerationStatusResponse(
                request_id=request_id,
                status=status,
                error=self._error_getter(request_id) or "Генерация была остановлена пользователем",
                methodology=self._methodology_getter(request_id),
            )
        return GenerationStatusResponse(
            request_id=request_id,
            status=status,
            methodology=self._methodology_getter(request_id),
        )

    async def cancel(self, request_id: str, user_id: str) -> dict[str, Any]:
        """Cancel active generation task and record the user action."""
        status = self._status_getter(request_id)
        if status is None:
            raise GenerationServiceError(404, "Запрос генерации не найден")
        if status in ("completed", "failed", "cancelled"):
            raise GenerationServiceError(400, f"Невозможно остановить генерацию: статус уже {status}")
        if not self._task_canceller(request_id):
            raise GenerationServiceError(500, "Не удалось остановить генерацию")

        self._logger.info("🛑 Генерация остановлена пользователем %s: request_id=%s", user_id, request_id)
        await self._log_writer(
            request_id=request_id,
            level="INFO",
            message="Генерация остановлена пользователем",
            user_id=user_id,
            phase="cancelled",
            metadata={"cancelled_by": user_id},
        )
        return {"success": True, "message": "Генерация успешно остановлена"}

    def _completed_response(self, request_id: str, status: str) -> GenerationStatusResponse:
        cached = self._result_getter(request_id)
        if not cached:
            self._logger.warning(
                "⚠️ Результат не найден в кэше для request_id=%s, хотя статус completed",
                request_id,
            )
            return GenerationStatusResponse(
                request_id=request_id,
                status="failed",
                error="Результат генерации истек или был удален",
            )

        report_json = cached.get("report_json")
        if report_json is None:
            self._logger.warning("⚠️ report_json отсутствует в кэше для request_id=%s", request_id)
            return GenerationStatusResponse(
                request_id=request_id,
                status="failed",
                error="Результат генерации поврежден",
            )
        if isinstance(report_json, dict):
            report_json = dict(report_json)
            if report_json.get("markdown"):
                report_json["markdown"] = normalize_markdown_display_blocks(report_json["markdown"])
            if report_json.get("translated_markdown"):
                report_json["translated_markdown"] = normalize_markdown_display_blocks(
                    report_json["translated_markdown"]
                )
        self._logger.debug(
            "✅ Возвращаем результат для request_id=%s, report_json keys: %s",
            request_id,
            list(report_json.keys()) if isinstance(report_json, dict) else "not a dict",
        )
        return GenerationStatusResponse(
            request_id=request_id,
            status=status,
            result=report_json,
            warnings=cached.get("warnings", []),
            methodology=(
                report_json.get("methodology_gate") or cached.get("methodology") or self._methodology_getter(request_id)
                if isinstance(report_json, dict)
                else cached.get("methodology")
            ),
        )
