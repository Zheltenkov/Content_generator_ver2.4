"""Endpoints для улучшения README после проверки."""

import asyncio
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.db.logging_db import write_log_async
from api.dependencies import get_current_user
from api.services.archive_builder import (
    add_assets_to_zip,
    build_readme_filename,
    merge_assets,
    transliterate_filename,
)
from api.utils.improvement_cache import (
    generate_diff,
    get_extract_request_id,
    get_generation_request_id,
    get_improved_readme,
    get_original_readme,
    link_generation_request,
    store_extracted_data,
    store_improved_readme,
    store_original_readme,
)
from api.utils.logger import get_logger
from api.utils.logging_context import set_request_id, set_user_id
from api.utils.result_cache import get_generation_error, get_generation_status, set_generation_status
from content_gen.didactics import compose_didactics_context
from content_gen.llm.client import LLMClient
from content_gen.models.schemas import ProjectSeed
from content_gen.reverse_extraction.orchestrator import ReverseExtractionOrchestrator

router = APIRouter()
logger = get_logger("readme_improvement")


class ExtractForImprovementRequest(BaseModel):
    """Запрос на извлечение данных для улучшения README."""
    readme_text: str = Field(..., description="Текст исходного README")
    learning_outcomes: list[str] | None = Field(
        default=None,
        description="Образовательные результаты (опционально, для контекста)"
    )
    curriculum_project: dict[str, Any] | None = Field(
        default=None,
        description="Если передан УП и выбран проект: данные проекта из УП (block + project). Тогда извлечение из README не вызывается, входные данные берутся из УП."
    )
    curriculum_context: dict[str, Any] | None = Field(
        default=None,
        description="Контекст УП для генерации (previous_projects, next_projects, sjm_context и т.д.). Передаётся вместе с curriculum_project."
    )


class ExtractForImprovementResponse(BaseModel):
    """Ответ с извлеченными данными для редактирования."""
    request_id: str
    status: str
    partial_seed: dict[str, Any]
    classification: dict[str, Any]
    metadata: dict[str, Any]


class GenerateImprovedRequest(BaseModel):
    """Запрос на генерацию улучшенного README."""
    request_id: str = Field(..., description="ID запроса извлечения")
    seed: ProjectSeed = Field(..., description="Отредактированный ProjectSeed")


class GenerateImprovedResponse(BaseModel):
    """Ответ на запрос генерации улучшенного README."""
    request_id: str
    status: str
    generation_request_id: str | None = None


class RewriteReadmeRequest(BaseModel):
    """Совместимый запрос для legacy rewrite endpoint."""
    markdown: str
    instruction: str
    seed_optional: dict[str, Any] | None = None


@router.post("/readme/rewrite")
async def rewrite_readme(
    request: RewriteReadmeRequest,
    user: dict = Depends(get_current_user)
):
    """Легковесный rewrite endpoint для совместимости с legacy UI/tests."""
    del user
    llm = LLMClient()
    didactics_context, _trace = compose_didactics_context("rewrite_style")
    system = "Ты редактор README и сохраняешь смысл исходного документа."
    if didactics_context:
        system = f"{system}\n\n{didactics_context}"
    user_prompt = (
        f"Исходный markdown:\n{request.markdown}\n\n"
        f"Инструкция по редактированию:\n{request.instruction}\n"
    )
    rewritten = llm.complete(system=system, user=user_prompt)
    return {"markdown": rewritten}


@router.post("/readme/improve/extract", response_model=ExtractForImprovementResponse)
async def extract_data_for_improvement(
    request: ExtractForImprovementRequest,
    user: dict = Depends(get_current_user)
):
    """
    Извлекает данные из README для последующего улучшения.
    
    Сохраняет исходный README и извлеченные данные в кэш.
    """
    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")

    set_request_id(request_id)
    set_user_id(user_id)

    logger.info(f"📄 Начало извлечения данных для улучшения README (request_id={request_id})")

    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Начало извлечения данных для улучшения README",
        user_id=user_id,
        phase="improvement_extract",
        metadata={
            "readme_length": len(request.readme_text),
            "has_learning_outcomes": bool(request.learning_outcomes)
        }
    )

    try:
        # Сохраняем исходный README
        store_original_readme(request_id, request.readme_text)

        if request.curriculum_project and isinstance(request.curriculum_project, dict):
            # Входные данные из УП (как в Генераторе): не вызываем LLM
            from content_gen.reverse_extraction.models import ClassificationResult, PartialProjectSeed
            block = request.curriculum_project.get("block") or {}
            project = request.curriculum_project.get("project") or {}
            block_code = block.get("code") or block.get("name") or ""
            project_title = project.get("title") or ""
            project_description = project.get("description") or ""
            project_lo = project.get("learning_outcomes") or []
            project_skills = project.get("skills") or []
            project_sjm = project.get("sjm")
            project_format = (project.get("format") or "individual").lower()
            required_software = project.get("required_software")
            required_tools = [required_software] if isinstance(required_software, str) and required_software else []
            partial_seed = PartialProjectSeed(
                title_seed=project_title,
                project_description=project_description or project_title,
                learning_outcomes=project_lo,
                skills=project_skills,
                required_tools=required_tools,
                tasks_count=project.get("tasks_count"),
                sjm=project_sjm,
            )
            classification = ClassificationResult(
                language="ru",
                thematic_block=block_code or None,
                thematic_block_suggested=block_code or None,
                thematic_block_name=block.get("name"),
                audience_level=request.curriculum_project.get("audience_level") or "base",
                project_type="group" if project_format == "group" else "individual",
            )
            store_extracted_data(request_id, partial_seed, classification)
            logger.info(
                f"✅ Данные для улучшения взяты из УП: title='{project_title}', block={block_code}"
            )
            return ExtractForImprovementResponse(
                request_id=request_id,
                status="completed",
                partial_seed=partial_seed.model_dump(),
                classification=classification.model_dump(),
                metadata={"source": "curriculum"}
            )

        # Инициализируем оркестратор обратного извлечения
        llm_client = LLMClient()
        orchestrator = ReverseExtractionOrchestrator(llm_client)

        # Извлекаем данные (без создания Excel)
        partial_seed, classification, normalized_readme, metadata = await asyncio.to_thread(
            orchestrator.extract_data_only,
            request.readme_text
        )

        # Сохраняем извлеченные данные в кэш
        store_extracted_data(request_id, partial_seed, classification)

        logger.info(
            f"✅ Извлечение данных завершено: "
            f"title='{partial_seed.title_seed}', "
            f"thematic_block={classification.thematic_block or classification.thematic_block_suggested}"
        )

        await write_log_async(
            request_id=request_id,
            level="INFO",
            message="Извлечение данных для улучшения завершено успешно",
            user_id=user_id,
            phase="improvement_extract_complete",
            metadata={
                "title_seed": partial_seed.title_seed,
                "tasks_count": partial_seed.tasks_count,
                "skills_count": len(partial_seed.skills),
                "learning_outcomes_count": len(partial_seed.learning_outcomes),
                "thematic_block": classification.thematic_block or classification.thematic_block_suggested
            }
        )

        return ExtractForImprovementResponse(
            request_id=request_id,
            status="completed",
            partial_seed=partial_seed.model_dump(),
            classification=classification.model_dump(),
            metadata=metadata
        )

    except Exception as e:
        logger.error(f"❌ Ошибка при извлечении данных: {e}", exc_info=True)
        await write_log_async(
            request_id=request_id,
            level="ERROR",
            message=f"Ошибка при извлечении данных: {e}",
            user_id=user_id,
            phase="improvement_extract_error",
            metadata={"error": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Ошибка при извлечении данных: {str(e)}")


@router.post("/readme/improve/generate", response_model=GenerateImprovedResponse)
async def generate_improved_readme(
    request: GenerateImprovedRequest,
    user: dict = Depends(get_current_user)
):
    """
    Генерирует улучшенный README на основе извлеченных и отредактированных данных.
    
    Использует существующий пайплайн генерации контента.
    """
    user_id = user.get("id", "anonymous")
    generation_request_id = str(uuid.uuid4())

    set_request_id(generation_request_id)
    set_user_id(user_id)

    logger.info(
        f"🚀 Начало генерации улучшенного README "
        f"(extract_request_id={request.request_id}, generation_request_id={generation_request_id})"
    )

    # Проверяем, что исходный README существует в кэше
    original_readme = get_original_readme(request.request_id)
    if not original_readme:
        raise HTTPException(
            status_code=404,
            detail=f"Исходный README не найден для request_id={request.request_id}. Возможно, данные устарели."
        )

    await write_log_async(
        request_id=generation_request_id,
        level="INFO",
        message="Начало генерации улучшенного README",
        user_id=user_id,
        phase="improvement_generate",
        metadata={
            "extract_request_id": request.request_id,
            "thematic_block": request.seed.thematic_block,
            "tasks_count": request.seed.tasks_count
        }
    )

    try:
        # Валидируем ProjectSeed
        project_seed = request.seed

        # Устанавливаем статус
        set_generation_status(generation_request_id, "pending")

        # Связываем extract_request_id с generation_request_id
        link_generation_request(request.request_id, generation_request_id)

        # Запускаем генерацию в фоне (используем существующий механизм)
        from api.routers.generation import _run_generation_background

        asyncio.create_task(
            _run_generation_background(
                request_id=generation_request_id,
                user_id=user_id,
                project_seed_dict=project_seed.model_dump(),
                track_paths=[],  # Не используем track files для улучшения
                temp_dir=None
            )
        )

        logger.info(f"✅ Генерация улучшенного README запущена (request_id={generation_request_id})")

        return GenerateImprovedResponse(
            request_id=request.request_id,
            status="pending",
            generation_request_id=generation_request_id
        )

    except Exception as e:
        logger.error(f"❌ Ошибка при запуске генерации: {e}", exc_info=True)
        set_generation_status(generation_request_id, "failed")
        await write_log_async(
            request_id=generation_request_id,
            level="ERROR",
            message=f"Ошибка при запуске генерации: {e}",
            user_id=user_id,
            phase="improvement_generate_error",
            metadata={"error": str(e)}
        )
        raise HTTPException(status_code=500, detail=f"Ошибка при запуске генерации: {str(e)}")


@router.get("/readme/improve/diff/{request_id}")
async def get_readme_diff(
    request_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Получает diff между исходным и улучшенным README.
    
    Args:
        request_id: ID запроса извлечения (extract request_id)
    """
    user_id = user.get("id", "anonymous")

    # Получаем исходный README
    original = get_original_readme(request_id)
    if not original:
        raise HTTPException(
            status_code=404,
            detail=f"Исходный README не найден для request_id={request_id}"
        )

    # Получаем generation_request_id
    generation_request_id = get_generation_request_id(request_id)
    if not generation_request_id:
        raise HTTPException(
            status_code=404,
            detail=f"Генерация не найдена для extract_request_id={request_id}"
        )

    # Получаем улучшенный README по generation_request_id
    improved = get_improved_readme(generation_request_id)
    if not improved:
        raise HTTPException(
            status_code=404,
            detail="Улучшенный README еще не готов или не найден"
        )

    # Сохраняем улучшенный README также по extract_request_id для удобства
    store_improved_readme(request_id, improved)

    # Генерируем diff
    diff_data = generate_diff(request_id)

    if not diff_data:
        raise HTTPException(
            status_code=404,
            detail="Не удалось сгенерировать diff"
        )

    return diff_data


@router.get("/readme/improve/status/{generation_request_id}")
async def get_generation_status_endpoint(
    generation_request_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Получает статус генерации улучшенного README.
    
    Использует существующий механизм проверки статуса генерации.
    """
    from api.utils.result_cache import get_result

    status = get_generation_status(generation_request_id)

    if not status:
        raise HTTPException(
            status_code=404,
            detail=f"Генерация с request_id={generation_request_id} не найдена"
        )

    result_data = None
    if status == "completed":
        result = get_result(generation_request_id)
        if result:
            # Сохраняем улучшенный README в кэш
            # result - это словарь, поэтому используем .get() вместо .report_json
            report_json = result.get("report_json", {})
            markdown = report_json.get("markdown", "")
            if markdown:
                # Сохраняем по generation_request_id
                store_improved_readme(generation_request_id, markdown)

                # Также сохраняем по extract_request_id, если есть связь
                extract_request_id = get_extract_request_id(generation_request_id)
                if extract_request_id:
                    store_improved_readme(extract_request_id, markdown)

            # Получаем rubric - проверяем оба места, как в metrics.py
            # rubric может быть как в report_json, так и отдельно в result (из кэша)
            rubric = result.get("rubric") or report_json.get("rubric")

            logger.debug(
                f"🔍 Проверка rubric для generation_request_id={generation_request_id}: "
                f"result.rubric={result.get('rubric') is not None}, "
                f"report_json.rubric={report_json.get('rubric') is not None}, "
                f"final_rubric={rubric is not None}"
            )

            # Получаем assets ТОЛЬКО из report_json (base64) - как в основном генераторе
            # result.assets содержит bytes и не должен использоваться в JSON ответе
            assets = report_json.get("assets") or {}

            # Если assets нет в report_json, но есть в result (bytes), конвертируем в base64
            if not assets and result.get("assets"):
                import base64
                assets_binary = result.get("assets")
                assets = {}
                if assets_binary.get("images"):
                    assets["images"] = [
                        {
                            "name": img.get("name"),
                            "data": base64.b64encode(img["data"]).decode("utf-8")
                            if isinstance(img.get("data"), bytes) else img.get("data")
                        }
                        for img in assets_binary["images"]
                        if img.get("name") and img.get("data")
                    ]
                if assets_binary.get("files"):
                    assets["files"] = [
                        {
                            "path": f.get("path"),
                            "data": base64.b64encode(f["data"]).decode("utf-8")
                            if isinstance(f.get("data"), bytes) else f.get("data")
                        }
                        for f in assets_binary["files"]
                        if f.get("path") and f.get("data")
                    ]

            result_data = {
                "markdown": markdown,
                "rubric": rubric,  # Используем rubric из обоих источников
                "text_stats": report_json.get("text_stats"),
                "assets": assets  # Только base64 строки для JSON сериализации
            }

    response = {
        "status": status,
        "result": result_data
    }

    # Если генерация завершилась с ошибкой, добавляем информацию об ошибке
    if status == "failed":
        error = get_generation_error(generation_request_id)
        if error:
            response["error"] = error

    return response


@router.get("/readme/improve/download/{generation_request_id}")
async def download_improved_readme_archive(
    generation_request_id: str,
    user: dict = Depends(get_current_user)
):
    """
    Скачивает ZIP архив с улучшенным README и дочерними файлами.
    
    Args:
        generation_request_id: ID запроса генерации улучшенного README
        user: Данные пользователя
        
    Returns:
        ZIP архив с улучшенным README (regen_<имя>.md) и дочерними файлами
    """
    import io
    import zipfile

    from fastapi.responses import StreamingResponse

    from api.db.generation_results_db import get_generation_result, get_report_by_request_id
    from api.utils.result_cache import get_result

    user_id = user.get("id", "anonymous")
    set_user_id(user_id)
    set_request_id(generation_request_id)

    # Получаем результат генерации
    cached = get_result(generation_request_id)
    db_result = get_generation_result(generation_request_id)

    if not cached and not db_result:
        raise HTTPException(
            status_code=404,
            detail="Результат генерации улучшенного README не найден"
        )

    # Получаем улучшенный README
    report_json = get_report_by_request_id(generation_request_id) or (cached or {}).get("report_json", {})
    improved_markdown = (cached or {}).get("markdown") or (db_result.markdown if db_result else "")

    if not improved_markdown:
        raise HTTPException(
            status_code=404,
            detail="Улучшенный README не найден в результатах"
        )

    logger.info(f"📥 Скачивание улучшенного README: generation_request_id={generation_request_id}")

    # Формируем имя файла для улучшенного README с префиксом regen_
    original_name = build_readme_filename(report_json)
    improved_name = f"regen_{original_name}"

    # Создаем ZIP архив
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # Добавляем улучшенный README
        z.writestr(improved_name, improved_markdown)
        logger.info(f"✅ Улучшенный README добавлен в архив: {improved_name}")

        assets = merge_assets((report_json or {}).get("assets"), (cached or {}).get("assets"))
        image_count, file_count = add_assets_to_zip(z, assets, logger)
        logger.info("📦 В архив улучшенного README добавлены assets: images=%s, files=%s", image_count, file_count)

    # Получаем данные архива после закрытия ZIP
    zip_data = buf.getvalue()
    buf.close()

    zip_size = len(zip_data)
    logger.info(f"✅ ZIP архив с улучшенным README создан: размер={zip_size} байт")

    # Название архива как у README (без расширения .md) + .zip
    zip_filename = improved_name.replace('.md', '.zip')

    zip_filename_ascii = transliterate_filename(zip_filename)

    return StreamingResponse(
        io.BytesIO(zip_data),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename_ascii}"'}
    )
