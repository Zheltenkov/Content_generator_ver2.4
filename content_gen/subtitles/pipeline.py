"""
Пайплайн: видео -> извлечение аудио (ffmpeg) -> транскрипция (Whisper) -> батчевый перевод -> SRT/VTT.

Исходный язык можно задать для улучшения качества Whisper.
Перевод сегментов выполняется батчами через TranslatorAgent.
"""

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from content_gen.agents.translator import TranslatorAgent
from content_gen.models.schemas import ProjectSeed

# Максимум символов в одном батче для перевода (чтобы не превышать лимит контекста)
SUBTITLE_BATCH_CHARS = 2500
# Максимум реплик в одном батче
SUBTITLE_BATCH_SIZE = 25

# Коды языков для Whisper (ISO 639-1)
WHISPER_LANGUAGE_MAP = {
    "ru": "ru",
    "en": "en",
    "kg": "ky",  # киргизский
    "uz": "uz",
    "tg": "tg",  # таджикский может не быть, fallback на auto
}


def _seg_field(seg, key: str, default=None):
    """
    Безопасно достаёт поле сегмента из OpenAI Whisper ответа.
    Поддерживает как dict, так и объекты TranscriptionSegment (атрибуты).
    """
    if isinstance(seg, dict):
        return seg.get(key, default)
    return getattr(seg, key, default)


def _get_openai_client():
    """Возвращает клиент OpenAI для Whisper (тот же api_key/base_url что и LLM)."""
    from openai import OpenAI
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key:
        raise ValueError("OPENAI_API_KEY не задан")
    return OpenAI(api_key=api_key, base_url=base_url or None)


def _format_timestamp_srt(seconds: float) -> str:
    """Форматирует секунды в SRT-таймкод 00:00:00,000."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _format_timestamp_vtt(seconds: float) -> str:
    """Форматирует секунды в VTT-таймкод 00:00:00.000."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def build_srt(segments: list[dict]) -> str:
    """Собирает строку SRT из списка сегментов {start, end, text}."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(str(i))
        lines.append(f"{_format_timestamp_srt(start)} --> {_format_timestamp_srt(end)}")
        lines.append(text.replace("\n", " "))
        lines.append("")
    return "\n".join(lines).strip()


def build_vtt(segments: list[dict]) -> str:
    """Собирает строку WebVTT из списка сегментов {start, end, text}."""
    lines = ["WEBVTT", ""]
    for seg in segments:
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"{_format_timestamp_vtt(start)} --> {_format_timestamp_vtt(end)}")
        lines.append(text.replace("\n", " "))
        lines.append("")
    return "\n".join(lines).strip()


def extract_audio(video_path: str | Path, progress_callback: Callable[[str], None] | None = None) -> str:
    """
    Извлекает аудиодорожку из видео в временный mp3 через ffmpeg.

    Returns:
        Путь к созданному аудиофайлу.
    """
    if progress_callback:
        progress_callback("extract_audio")
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video_path}")
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg не найден. Установите ffmpeg (например: apt install ffmpeg) для обработки видео."
        )
    suffix = ".mp3"
    fd, out_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        cmd = [
            ffmpeg,
            "-y",
            "-i", str(video_path),
            "-vn",
            "-acodec", "libmp3lame",
            "-q:a", "4",
            "-ar", "16000",
            out_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "")[-1000:]
            raise RuntimeError(f"ffmpeg завершился с ошибкой: {stderr}")
        return out_path
    except Exception:
        if os.path.exists(out_path):
            try:
                os.unlink(out_path)
            except OSError:
                pass
        raise


def transcribe(
    audio_path: str,
    source_language: str | None = None,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict]:
    """
    Транскрибирует аудио через OpenAI Whisper API.

    Args:
        audio_path: путь к аудиофайлу
        source_language: код языка речи (ru, en, kg, uz, tg) или None для авто
        progress_callback: вызывается с фазой "transcribe"

    Returns:
        Список сегментов [{"start": float, "end": float, "text": str}, ...]
    """
    if progress_callback:
        progress_callback("transcribe")
    client = _get_openai_client()
    lang = None
    if source_language:
        lang = WHISPER_LANGUAGE_MAP.get(source_language.lower(), source_language.lower())
        if lang == "tg":
            lang = None
    with open(audio_path, "rb") as f:
        create_kwargs = {
            "model": "whisper-1",
            "file": f,
            "response_format": "verbose_json",
        }
        if lang:
            create_kwargs["language"] = lang
        response = client.audio.transcriptions.create(**create_kwargs)
    segments: list[dict] = []
    for seg in getattr(response, "segments", []):
        start = float(_seg_field(seg, "start", 0.0) or 0.0)
        end = float(_seg_field(seg, "end", 0.0) or 0.0)
        text_val = _seg_field(seg, "text", "") or ""
        text = str(text_val).strip()
        segments.append({"start": start, "end": end, "text": text})
    if not segments and getattr(response, "text", None):
        segments = [{"start": 0.0, "end": 0.0, "text": str(getattr(response, "text", "") or "").strip()}]
    return segments


def _translate_batch(
    translator: TranslatorAgent,
    lines: list[str],
    target_language: str,
    target_lang_name: str,
    seed: ProjectSeed,
) -> list[str]:
    """Переводит один батч пронумерованных строк. Возвращает список переведённых строк в том же порядке."""
    if not lines:
        return []
    numbered = "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
    prompt = (
        f"Переведи следующие пронумерованные строки на {target_lang_name}. "
        "Сохрани нумерацию в формате 1. 2. 3. Выведи только переведённые строки, без заголовков."
    )
    system = f"Ты переводчик. Переводишь только текст на {target_lang_name}. Сохраняй нумерацию 1. 2. 3."
    out = translator.llm.complete(system=system, user=f"{prompt}\n\n{numbered}", temperature=0.2)
    out = (out or "").strip()
    result = []
    for raw_line in out.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r"^\s*\d+\.\s*(.+)$", line)
        if m:
            result.append(m.group(1).strip())
        else:
            result.append(line)
    if len(result) < len(lines):
        result.extend(lines[len(result) :])
    return result[: len(lines)]


def translate_segments_batched(
    segments: list[dict],
    target_language: str,
    translator: TranslatorAgent,
    seed: ProjectSeed,
    progress_callback: Callable[[str], None] | None = None,
) -> list[dict]:
    """
    Переводит сегменты батчами, сохраняя таймкоды и порядок.
    """
    if progress_callback:
        progress_callback("translate")
    language_names = {
        "en": "английский",
        "kg": "киргизский",
        "uz": "узбекский",
        "tg": "таджикский",
        "ru": "русский",
    }
    target_lang_name = language_names.get(target_language, target_language)
    if target_language == "ru":
        return segments
    result: list[dict | None] = [None] * len(segments)
    batch_lines: list[str] = []
    batch_indices: list[int] = []
    total_chars = 0
    for i, seg in enumerate(segments):
        text = (seg.get("text") or "").strip()
        if not text:
            result[i] = {**seg, "text": ""}
            continue
        batch_lines.append(text)
        batch_indices.append(i)
        total_chars += len(text)
        if len(batch_lines) >= SUBTITLE_BATCH_SIZE or total_chars >= SUBTITLE_BATCH_CHARS:
            out_lines = _translate_batch(
                translator, batch_lines, target_language, target_lang_name, seed
            )
            for j, idx in enumerate(batch_indices):
                result[idx] = {
                    **segments[idx],
                    "text": out_lines[j] if j < len(out_lines) else batch_lines[j],
                }
            batch_lines = []
            batch_indices = []
            total_chars = 0
    if batch_lines:
        out_lines = _translate_batch(
            translator, batch_lines, target_language, target_lang_name, seed
        )
        for j, idx in enumerate(batch_indices):
            result[idx] = {
                **segments[idx],
                "text": out_lines[j] if j < len(out_lines) else batch_lines[j],
            }
    return [r for r in result if r is not None]


def run_video_to_subtitles_pipeline(
    video_path: str | Path,
    target_language: str,
    source_language: str | None = None,
    subtitle_format: str = "srt",
    progress_callback: Callable[[str], None] | None = None,
    translator: TranslatorAgent | None = None,
    seed: ProjectSeed | None = None,
) -> tuple[str, str]:
    """
    Полный пайплайн: видео -> аудио -> транскрипция -> перевод -> субтитры.

    Args:
        video_path: путь к файлу видео
        target_language: целевой язык перевода (ru, en, kg, uz, tg)
        source_language: исходный язык речи для Whisper (опционально)
        subtitle_format: "srt" или "vtt"
        progress_callback: вызывается с фазами extract_audio, transcribe, translate, build_srt
        translator: агент перевода (если None, создаётся временный)
        seed: ProjectSeed для контекста перевода (если None, минимальный)

    Returns:
        (translated_subtitles, original_transcript)
        original_transcript — исходный текст с таймкодами (SRT) для справки.
    """
    from content_gen.llm.cached_client import CachedLLMClient

    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Видео не найдено: {video_path}")

    if translator is None:
        llm = CachedLLMClient(provider="openai", enable_cache=True, enable_batching=True)
        translator = TranslatorAgent(llm)
    if seed is None:
        seed = ProjectSeed(
            language="ru",
            project_type="individual",
            project_description="Субтитры к видео",
        )

    audio_path = None
    try:
        audio_path = extract_audio(video_path, progress_callback)
        segments = transcribe(audio_path, source_language=source_language, progress_callback=progress_callback)
        if not segments:
            return "", ""

        original_srt = build_srt(segments)
        if progress_callback:
            progress_callback("build_srt")

        translated_segments = translate_segments_batched(
            segments,
            target_language,
            translator,
            seed,
            progress_callback,
        )
        if subtitle_format.lower() == "vtt":
            result = build_vtt(translated_segments)
        else:
            result = build_srt(translated_segments)
        return result, original_srt
    finally:
        if audio_path and os.path.exists(audio_path):
            try:
                os.unlink(audio_path)
            except OSError:
                pass
