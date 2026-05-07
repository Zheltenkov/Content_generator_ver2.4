"""Пайплайн: видео -> транскрипция (Whisper) -> перевод сегментов -> SRT/VTT."""

from .pipeline import run_video_to_subtitles_pipeline

__all__ = ["run_video_to_subtitles_pipeline"]
