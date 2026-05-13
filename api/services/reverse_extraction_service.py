"""Application service for reverse README extraction."""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass
from typing import Any

from api.utils.logger import get_logger
from content_gen.llm.client import LLMClient
from content_gen.reverse_extraction import ReverseExtractionOrchestrator

logger = get_logger("reverse_extraction")


@dataclass(frozen=True)
class ReverseExtractionCommand:
    """Input contract for README reverse extraction."""

    request_id: str
    user_id: str
    readme_text: str


@dataclass(frozen=True)
class ReverseExtractionResult:
    """Result contract for extracted Excel artifact."""

    request_id: str
    status: str
    excel_file_id: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class ReverseExtractionDownload:
    """Downloadable Excel artifact."""

    filename: str
    excel_bytes: bytes
    metadata: dict[str, Any]


class ReverseExtractionService:
    """Coordinate reverse extraction and short-lived Excel artifact storage."""

    def __init__(self, llm_factory=None, orchestrator_factory=None) -> None:
        self._llm_factory = llm_factory or LLMClient
        self._orchestrator_factory = orchestrator_factory or ReverseExtractionOrchestrator
        self._file_cache: dict[str, bytes] = {}
        self._metadata_cache: dict[str, dict[str, Any]] = {}

    def extract_from_readme(self, command: ReverseExtractionCommand) -> ReverseExtractionResult:
        """Extract project fields from README text and cache generated Excel bytes."""
        logger.info("📄 Начало обратного извлечения для пользователя %s", command.user_id)

        llm_client = self._llm_factory()
        orchestrator = self._orchestrator_factory(llm_client)
        excel_buffer, metadata = orchestrator.extract_from_readme(command.readme_text)

        excel_file_id = str(uuid.uuid4())
        excel_bytes = excel_buffer.getvalue()
        self._file_cache[excel_file_id] = excel_bytes
        self._metadata_cache[excel_file_id] = metadata

        logger.info(
            "✅ Обратное извлечение завершено: file_id=%s, размер Excel=%s байт",
            excel_file_id,
            len(excel_bytes),
        )
        return ReverseExtractionResult(
            request_id=command.request_id,
            status="completed",
            excel_file_id=excel_file_id,
            metadata=metadata,
        )

    def get_download(self, file_id: str) -> ReverseExtractionDownload | None:
        """Return cached Excel artifact for download."""
        excel_bytes = self._file_cache.get(file_id)
        if excel_bytes is None:
            return None

        metadata = self._metadata_cache.get(file_id, {})
        title = metadata.get("extracted_fields", {}).get("final_mapping", {}).get("title_seed", "project")
        filename = build_excel_filename(str(title or "project"))
        return ReverseExtractionDownload(filename=filename, excel_bytes=excel_bytes, metadata=metadata)


_TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "Yo",
    "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M",
    "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U",
    "Ф": "F", "Х": "H", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Sch",
    "Ъ": "", "Ы": "Y", "Ь": "", "Э": "E", "Ю": "Yu", "Я": "Ya",
}
_INVALID_FILENAME_CHARS = set('<>:"/\\|?*;')


def build_excel_filename(title: str) -> str:
    """Build stable ASCII filename for extracted project spec."""
    result = []
    for char in title:
        if char in _TRANSLIT_MAP:
            result.append(_TRANSLIT_MAP[char])
        elif char in _INVALID_FILENAME_CHARS:
            result.append("_")
        elif char.isalnum() or char in (" ", "-", "_", "."):
            result.append(char)
        else:
            result.append("_")

    safe_title = "".join(result)
    safe_title = "_".join(safe_title.split())
    safe_title = re.sub(r"_+", "_", safe_title)[:50].strip("_")
    return f"{safe_title}_spec.xlsx" if safe_title else "project_spec.xlsx"


def bytes_to_stream(excel_bytes: bytes) -> io.BytesIO:
    """Wrap bytes for StreamingResponse without leaking service internals."""
    return io.BytesIO(excel_bytes)
