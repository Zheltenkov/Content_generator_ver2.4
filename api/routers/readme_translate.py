"""Endpoints для перевода произвольного README/Markdown и видео (субтитры).

Модуль реализует сервисы «Перевод README» и «Перевод субтитров по видео».
POST /translate/readme или POST /translate/video возвращают request_id;
клиент опрашивает GET /translate/status/{request_id} до status=completed или failed.
"""

import asyncio
import os
import tempfile
import time
import uuid
import threading

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from api.db.logging_db import write_log_async
from api.dependencies import get_current_user
from api.utils.file_validation import MAX_VIDEO_SIZE, validate_video_file
from api.utils.logger import get_logger
from api.utils.logging_context import set_request_id, set_user_id
from api.utils.result_cache import (
    get_translation_job,
    set_translation_job,
    set_translation_phase,
)
from content_gen.agents.translator import TranslatorAgent
from content_gen.llm.cached_client import CachedLLMClient
from content_gen.models.schemas import ProjectSeed
from content_gen.subtitles import run_video_to_subtitles_pipeline
from content_gen.subtitles.burned_pipeline import run_burned_subs_pipeline

logger = get_logger("readme-translate")
router = APIRouter()

SUPPORTED_LANGUAGES = {"ru", "en", "kg", "uz", "tg"}
STORAGE_DIR = os.getenv("STORAGE_DIR", os.path.join(tempfile.gettempdir(), "content_generator_translations"))

STAGE_PROGRESS = {
    "queued": 0,
    "extract_audio": 10,
    "chunk_audio": 15,
    "transcribe": 35,
    "correct_asr": 45,
    "translate": 60,
    "build_subtitles": 75,
    "render_video": 90,
    "done": 100,
}

# Ограничиваем количество одновременно обрабатываемых видео-задач, чтобы
# избежать конкурирующей загрузки ASR/ffmpeg и OOM на маленьких серверах.
VIDEO_MAX_CONCURRENT_JOBS = int(os.getenv("VIDEO_MAX_CONCURRENT_JOBS", "1"))
_video_jobs_semaphore = threading.Semaphore(max(1, VIDEO_MAX_CONCURRENT_JOBS))


class TranslateReadmeRequest(BaseModel):
    """Запрос на перевод произвольного README/Markdown-документа."""

    markdown: str
    target_language: str
    translation_mode: str | None = "literal"  # "literal" | "combined"
    thematic_block: str | None = None
    title_seed: str | None = None


class TranslateReadmeStartResponse(BaseModel):
    """Ответ при старте перевода (асинхронный режим)."""

    request_id: str


class TranslateReadmeStatusResponse(BaseModel):
    """Ответ при опросе статуса перевода."""

    request_id: str
    status: str  # pending | in_progress | completed | failed
    phase: str | None = None
    original_markdown: str | None = None
    translated_markdown: str | None = None
    target_language: str | None = None
    error: str | None = None
    job_type: str | None = None
    translated_subtitles: str | None = None
    original_transcript: str | None = None
    progress: float | None = None
    error_code: str | None = None
    result_links: dict[str, str] | None = None


def _run_translation(
    request_id: str,
    user_id: str,
    markdown: str,
    target_language: str,
    translation_mode: str,
    seed: ProjectSeed,
) -> None:
    """Синхронный запуск перевода в отдельном потоке; обновляет кэш по завершении."""
    def progress_callback(phase: str) -> None:
        set_translation_phase(request_id, phase)

    llm_client = CachedLLMClient(
        provider="openai",
        enable_cache=True,
        enable_batching=True,
    )
    translator = TranslatorAgent(llm_client)
    try:
        translated_md = translator.translate(
            markdown,
            target_language,
            seed,
            translation_mode=translation_mode,
            progress_callback=progress_callback,
            strict=True,
        )
        set_translation_job(
            request_id=request_id,
            status="completed",
            phase="combine" if translation_mode == "combined" else "translate",
            original_markdown=markdown,
            translated_markdown=translated_md,
            target_language=target_language,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Ошибка при переводе README: %s", e, exc_info=True)
        set_translation_job(
            request_id=request_id,
            status="failed",
            original_markdown=markdown,
            target_language=target_language,
            error=str(e),
        )


def _run_video_translation(
    request_id: str,
    user_id: str,
    video_path: str,
    target_language: str,
    source_language: str | None,
    subtitle_format: str,
) -> None:
    """Синхронный запуск пайплайна видео -> субтитры в отдельном потоке."""
    def progress_callback(phase: str) -> None:
        set_translation_phase(request_id, phase)

    llm_client = CachedLLMClient(
        provider="openai",
        enable_cache=True,
        enable_batching=True,
    )
    translator = TranslatorAgent(llm_client)
    seed = ProjectSeed(
        language="ru",
        project_type="individual",
        thematic_block="GEN",
        audience_level="base",
        required_tools=[],
        title_seed="",
        project_description="Субтитры к видео",
        learning_outcomes=[],
        skills=[],
        tasks_count=None,
        task_complexity=None,
        bonus_wish=None,
        context_track_dir=None,
        last_known_order=None,
        group_size=None,
        repo_base_url=None,
        repo_path_template=None,
        is_programming_project=None,
        target_languages=None,
        zun=None,
    )
    try:
        translated_srt, original_srt = run_video_to_subtitles_pipeline(
            video_path=video_path,
            target_language=target_language,
            source_language=source_language,
            subtitle_format=subtitle_format,
            progress_callback=progress_callback,
            translator=translator,
            seed=seed,
        )
        set_translation_job(
            request_id=request_id,
            status="completed",
            phase="build_srt",
            target_language=target_language,
            job_type="video",
            translated_subtitles=translated_srt,
            original_transcript=original_srt,
            subtitle_format=subtitle_format,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Ошибка при переводе видео/субтитров: %s", e, exc_info=True)
        set_translation_job(
            request_id=request_id,
            status="failed",
            target_language=target_language,
            job_type="video",
            error=str(e),
        )
    finally:
        if os.path.exists(video_path):
            try:
                os.unlink(video_path)
            except OSError:
                pass


def _run_burned_video_translation(
    request_id: str,
    user_id: str,
    video_path: str,
    target_language: str,
    output_mode: str,
    subtitle_style: str,
) -> None:
    """Запуск пайплайна с транскрипцией RU, переводом по id и опционально рендером видео с субтитрами."""
    output_dir = os.path.join(STORAGE_DIR, "translations", request_id)
    os.makedirs(output_dir, exist_ok=True)

    start_ts = time.monotonic()
    last_phase = "queued"
    last_ts = start_ts

    def progress_callback(phase: str) -> None:
        nonlocal last_phase, last_ts
        now = time.monotonic()
        elapsed = now - start_ts
        delta = now - last_ts
        logger.info(
            "Video translation progress: request_id=%s user_id=%s phase=%s prev_phase=%s elapsed=%.2fs delta=%.2fs",
            request_id,
            user_id,
            phase,
            last_phase,
            elapsed,
            delta,
        )
        last_phase = phase
        last_ts = now
        progress = STAGE_PROGRESS.get(phase)
        set_translation_phase(request_id, phase, progress)

    llm_client = CachedLLMClient(
        provider="openai",
        enable_cache=True,
        enable_batching=True,
    )
    # Ограничиваем количество одновременных тяжёлых задач перевода видео.
    with _video_jobs_semaphore:
        try:
            result = run_burned_subs_pipeline(
                video_path=video_path,
                target_lang=target_language,
                output_mode=output_mode,
                subtitle_style=subtitle_style,
                output_dir=output_dir,
                progress_callback=progress_callback,
                llm_client=llm_client,
            )
            result_links = {}
            if result.get("vtt_path") and os.path.exists(result["vtt_path"]):
                result_links["vtt"] = "subtitles.vtt"
            if result.get("srt_path") and os.path.exists(result["srt_path"]):
                result_links["srt"] = "subtitles.srt"
            if result.get("ass_path") and os.path.exists(result["ass_path"]):
                result_links["ass"] = "subtitles.ass"
            if result.get("transcript_path") and os.path.exists(result["transcript_path"]):
                result_links["transcript"] = "transcript_ru.json"
            if result.get("video_path") and os.path.exists(result["video_path"]):
                result_links["video"] = "output_with_subs.mp4"

            total_elapsed = time.monotonic() - start_ts
            segments_count = len(result.get("segments") or [])
            logger.info(
                "Video translation done: request_id=%s user_id=%s target_language=%s output_mode=%s segments=%d elapsed=%.2fs",
                request_id,
                user_id,
                target_language,
                output_mode,
                segments_count,
                total_elapsed,
            )

            set_translation_job(
                request_id=request_id,
                status="completed",
                phase="done",
                target_language=target_language,
                job_type="video",
                progress=100.0,
                result_links=result_links,
            )
        except Exception as e:  # noqa: BLE001
            elapsed = time.monotonic() - start_ts
            logger.error(
                "Ошибка пайплайна перевода видео с субтитрами (request_id=%s, user_id=%s, target_language=%s, output_mode=%s, elapsed=%.2fs): %s",
                request_id,
                user_id,
                target_language,
                output_mode,
                elapsed,
                e,
                exc_info=True,
            )
            set_translation_job(
                request_id=request_id,
                status="failed",
                target_language=target_language,
                job_type="video",
                error=str(e),
                error_code="pipeline_error",
            )
        finally:
            if os.path.exists(video_path):
                try:
                    os.unlink(video_path)
                except OSError:
                    pass


@router.post("/translate/readme", response_model=TranslateReadmeStartResponse)
async def translate_readme_start(
    payload: TranslateReadmeRequest,
    user: dict = Depends(get_current_user),
) -> TranslateReadmeStartResponse:
    """Запускает перевод в фоне и сразу возвращает request_id. Статус опрашивать через GET /translate/status/{request_id}."""
    markdown = (payload.markdown or "").strip()
    if not markdown:
        raise HTTPException(status_code=400, detail="Исходный документ пуст")

    target_language = (payload.target_language or "").lower().strip()
    if target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый язык перевода: {target_language!r}",
        )

    translation_mode = (payload.translation_mode or "literal").lower().strip()
    if translation_mode not in ("literal", "combined"):
        translation_mode = "literal"

    detected_lang = TranslatorAgent._detect_source_language(markdown)
    if detected_lang and detected_lang == target_language:
        language_names = {"en": "английский", "kg": "киргизский", "uz": "узбекский", "tg": "таджикский"}
        lang_name = language_names.get(target_language, target_language)
        raise HTTPException(
            status_code=400,
            detail=(
                f"Документ уже на целевом языке ({lang_name}). "
                f"Подайте оригинальный документ на русском языке."
            ),
        )

    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")

    set_request_id(request_id)
    set_user_id(user_id)

    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Старт перевода README (асинхронный режим)",
        user_id=user_id,
        phase="translate_readme_start",
        metadata={
            "target_language": target_language,
            "translation_mode": translation_mode,
            "markdown_chars": len(markdown),
        },
    )

    try:
        seed = ProjectSeed(
            language="ru",
            project_type="individual",
            thematic_block=payload.thematic_block or "GEN",
            audience_level="base",
            required_tools=[],
            title_seed=payload.title_seed or "",
            project_description=markdown[:1000],
            learning_outcomes=[],
            skills=[],
            tasks_count=None,
            task_complexity=None,
            bonus_wish=None,
        context_track_dir=None,
            last_known_order=None,
            group_size=None,
            repo_base_url=None,
            repo_path_template=None,
            is_programming_project=None,
            target_languages=None,
            zun=None,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Ошибка валидации ProjectSeed для перевода: %s", e, exc_info=True)
        raise HTTPException(
            status_code=400,
            detail=f"Ошибка подготовки контекста для перевода: {e}",
        )

    set_translation_job(
        request_id=request_id,
        status="in_progress",
        phase="translate",
        original_markdown=markdown,
        target_language=target_language,
    )

    asyncio.create_task(
        asyncio.to_thread(
            _run_translation,
            request_id,
            user_id,
            markdown,
            target_language,
            translation_mode,
            seed,
        )
    )

    logger.info(
        "🌐 Перевод README запущен в фоне (request_id=%s, target_language=%s)",
        request_id,
        target_language,
    )
    return TranslateReadmeStartResponse(request_id=request_id)


@router.post("/translate/video", response_model=TranslateReadmeStartResponse)
async def translate_video_start(
    file: UploadFile = File(...),
    target_language: str = Form(...),
    output_mode: str = Form("burned_video"),  # burned_video | subtitles_only | both
    subtitle_style: str = Form("boxed"),  # boxed | outline
    user: dict = Depends(get_current_user),
) -> TranslateReadmeStartResponse:
    """Загружает видео, транскрибирует RU (gpt-4o-transcribe), переводит, выдаёт VTT/SRT/ASS и опционально MP4 с вожёнными субтитрами."""
    validate_video_file(file)
    target_language = (target_language or "").lower().strip()
    if target_language not in SUPPORTED_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемый язык перевода: {target_language!r}",
        )
    mode = (output_mode or "burned_video").lower().strip()
    if mode not in ("burned_video", "subtitles_only", "both"):
        mode = "burned_video"
    style = (subtitle_style or "boxed").lower().strip()
    if style not in ("boxed", "outline"):
        style = "boxed"

    content = await file.read()
    if len(content) > MAX_VIDEO_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Видео слишком большое. Максимум: {MAX_VIDEO_SIZE // (1024 * 1024)} MB",
        )
    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    if suffix.lower() not in {".mp4", ".webm", ".mov", ".avi", ".mkv", ".m4v"}:
        suffix = ".mp4"
    fd, video_path = None, None
    try:
        fd, video_path = tempfile.mkstemp(suffix=suffix)
        os.write(fd, content)
        os.close(fd)
        fd = None
    except Exception as e:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        raise HTTPException(status_code=500, detail=f"Не удалось сохранить видео: {e}")

    request_id = str(uuid.uuid4())
    user_id = user.get("id", "anonymous")
    set_request_id(request_id)
    set_user_id(user_id)

    await write_log_async(
        request_id=request_id,
        level="INFO",
        message="Старт перевода видео (транскрипция RU, субтитры/видео)",
        user_id=user_id,
        phase="translate_video_start",
        metadata={
            "target_language": target_language,
            "output_mode": mode,
            "subtitle_style": style,
        },
    )

    set_translation_job(
        request_id=request_id,
        status="in_progress",
        phase="queued",
        target_language=target_language,
        job_type="video",
        progress=0.0,
    )

    asyncio.create_task(
        asyncio.to_thread(
            _run_burned_video_translation,
            request_id,
            user_id,
            video_path,
            target_language,
            mode,
            style,
        )
    )

    logger.info(
        "Video translation started (request_id=%s, target_language=%s, output_mode=%s)",
        request_id,
        target_language,
        mode,
    )
    return TranslateReadmeStartResponse(request_id=request_id)


@router.get("/translate/subtitles/{request_id}")
async def download_translated_subtitles(
    request_id: str,
    user: dict = Depends(get_current_user),
) -> Response:
    """Скачивает файл переведённых субтитров (SRT или VTT) по request_id. Обратная совместимость для старых задач без result_links."""
    job = get_translation_job(request_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Запрос перевода не найден или истёк")
    if job.get("job_type") != "video":
        raise HTTPException(status_code=400, detail="Запрос не является задачей перевода видео")
    result_links = job.get("result_links") or {}
    if result_links:
        ext = "vtt" if "vtt" in result_links else "srt"
        return await _stream_download(request_id, ext, job)
    content = job.get("translated_subtitles")
    if not content:
        raise HTTPException(status_code=404, detail="Субтитры не найдены (задача ещё не завершена или завершилась с ошибкой)")
    ext = job.get("subtitle_format") or "srt"
    if ext not in ("srt", "vtt"):
        ext = "srt"
    media_type = "text/vtt" if ext == "vtt" else "text/plain"
    lang = job.get("target_language") or "ru"
    filename = f"subtitles_{lang}.{ext}"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _stream_download(request_id: str, file_type: str, job: dict):
    """Отдаёт файл из STORAGE_DIR/translations/{request_id}/ по type (video|vtt|srt|ass|transcript)."""
    result_links = job.get("result_links") or {}
    filename = result_links.get(file_type)
    if not filename:
        raise HTTPException(status_code=404, detail=f"Файл типа {file_type!r} недоступен для этой задачи")
    dir_path = os.path.join(STORAGE_DIR, "translations", request_id)
    file_path = os.path.join(dir_path, filename)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден или удалён")
    media_map = {
        "video": "video/mp4",
        "vtt": "text/vtt",
        "srt": "text/plain",
        "ass": "text/x-ssa",
        "transcript": "application/json",
    }
    return FileResponse(
        path=file_path,
        media_type=media_map.get(file_type, "application/octet-stream"),
        filename=filename,
    )


@router.get("/translate/download/{request_id}")
async def download_translation_artifact(
    request_id: str,
    type: str = Query(..., alias="type"),  # video | vtt | srt | ass | transcript
    user: dict = Depends(get_current_user),
):
    """Скачивает артефакт перевода видео: video, vtt, srt, ass, transcript."""
    job = get_translation_job(request_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Запрос перевода не найден или истёк")
    if job.get("job_type") != "video":
        raise HTTPException(status_code=400, detail="Запрос не является задачей перевода видео")
    kind = (type or "").lower().strip()
    if kind not in ("video", "vtt", "srt", "ass", "transcript"):
        raise HTTPException(status_code=400, detail="type должен быть: video, vtt, srt, ass, transcript")
    return await _stream_download(request_id, kind, job)


@router.get("/translate/status/{request_id}", response_model=TranslateReadmeStatusResponse)
async def translate_readme_status(
    request_id: str,
    user: dict = Depends(get_current_user),
) -> TranslateReadmeStatusResponse:
    """Возвращает текущий статус и результат перевода (при status=completed). stage=phase, progress, error_code, result_links для видео."""
    job = get_translation_job(request_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Запрос перевода не найден или истёк")
    return TranslateReadmeStatusResponse(
        request_id=request_id,
        status=job.get("status", "pending"),
        phase=job.get("phase"),
        original_markdown=job.get("original_markdown"),
        translated_markdown=job.get("translated_markdown"),
        target_language=job.get("target_language"),
        error=job.get("error"),
        job_type=job.get("job_type"),
        translated_subtitles=job.get("translated_subtitles"),
        original_transcript=job.get("original_transcript"),
        progress=job.get("progress"),
        error_code=job.get("error_code"),
        result_links=job.get("result_links"),
    )
