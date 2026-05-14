"""Explicit human approval checkpoints for generated artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..utils.markdown_display_normalizer import normalize_markdown_display_blocks
from .decision import MethodologyGateInterrupt


class HumanApprovalCheckpoint(BaseModel):
    """A paused artifact that must be approved before the next flow node."""

    id: str
    stage: str
    node_id: str
    title: str
    summary: str
    resume_from_node: str
    allowed_targets: list[str] = Field(default_factory=list)
    artifact: dict[str, Any] = Field(default_factory=dict)
    artifact_hash: str = ""


class RequirementMatrixItem(BaseModel):
    """Strict UI contract for methodology requirement matrix rows."""

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=120)
    status: Literal["pass", "fail"]
    passed: bool
    evidence: str = Field(min_length=1, max_length=500)


class HumanApprovalCheckpointPolicy:
    """Deterministic policy for milestone approvals inside AgentFlow."""

    DEFAULT_CHECKPOINTS = {"title", "structure", "theory", "practice", "quality", "evaluation"}
    CHECKPOINT_NODE_MAP = {
        "title_annotation": "title",
        "skeleton": "structure",
        "theory": "theory",
        "practice": "practice",
        "global_quality": "quality",
        "evaluation": "evaluation",
    }

    def __init__(self, checkpoints: set[str] | None = None) -> None:
        self.checkpoints = checkpoints or set()

    @classmethod
    def from_env(cls, *, enabled_by_default: bool = False) -> "HumanApprovalCheckpointPolicy":
        raw_value = os.getenv("METHODOLOGY_HUMAN_CHECKPOINTS")
        if raw_value is None:
            raw_value = "all" if enabled_by_default else ""
        normalized = raw_value.strip().lower()
        if normalized in {"", "0", "false", "off", "none", "disabled"}:
            return cls(set())
        if normalized in {"1", "true", "on", "enabled", "all"}:
            return cls(set(cls.DEFAULT_CHECKPOINTS))
        checkpoints = {part.strip() for part in normalized.split(",") if part.strip()}
        if "all" in checkpoints:
            checkpoints.remove("all")
            checkpoints.update(cls.DEFAULT_CHECKPOINTS)
        if "annotation" in checkpoints:
            checkpoints.remove("annotation")
            checkpoints.add("title")
        return cls(checkpoints)

    def maybe_raise(self, node_id: str, context: dict[str, Any]) -> None:
        """Raise a controlled pause when the completed node produced a gated artifact."""
        checkpoint_id = self.CHECKPOINT_NODE_MAP.get(node_id)
        if not checkpoint_id or checkpoint_id not in self.checkpoints:
            return
        checkpoint = self._build_checkpoint(checkpoint_id, context)
        if checkpoint is None:
            return
        checkpoint.artifact_hash = _checkpoint_artifact_hash(checkpoint)
        checkpoint_payload = checkpoint.model_dump(mode="json")
        if _checkpoint_already_approved(context, checkpoint_payload):
            context["last_skipped_human_approval_checkpoint"] = checkpoint_payload
            return
        context["human_approval_checkpoint"] = checkpoint_payload
        context.setdefault("human_approval_checkpoints", []).append(checkpoint_payload)
        raise MethodologyGateInterrupt(
            checkpoint.summary,
            context={
                "phase": checkpoint.stage,
                "error_type": "HumanApprovalCheckpoint",
                "checkpoint": checkpoint_payload,
            },
        )

    def _build_checkpoint(
        self,
        checkpoint_id: str,
        context: dict[str, Any],
    ) -> HumanApprovalCheckpoint | None:
        builders = {
            "title": self._title_checkpoint,
            "structure": self._structure_checkpoint,
            "annotation": self._annotation_checkpoint,
            "theory": self._theory_checkpoint,
            "practice": self._practice_checkpoint,
            "quality": self._quality_checkpoint,
            "evaluation": self._evaluation_checkpoint,
        }
        builder = builders.get(checkpoint_id)
        if builder is None:
            return None
        return builder(context)

    @staticmethod
    def _title_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        annotation_text = _annotation_text(context.get("annotation"))
        artifact = {
            "title": str(context.get("title") or ""),
            "annotation": annotation_text,
        }
        return HumanApprovalCheckpoint(
            id="title",
            stage="title",
            node_id="title_annotation",
            title="Проверка названия проекта",
            summary="Название и аннотация готовы. Подтвердите их перед сборкой структуры README.",
            resume_from_node="skeleton",
            allowed_targets=["title", "annotation"],
            artifact=artifact,
        )

    @staticmethod
    def _structure_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        markdown = normalize_markdown_display_blocks(str(context.get("markdown") or ""))
        artifact = {
            "title": str(context.get("title") or ""),
            "annotation": _annotation_text(context.get("annotation")),
            "summary": "Черновик структуры README готов: проверьте состав глав, частей и практических блоков.",
            "structure_outline": _markdown_outline(markdown),
            "requirements_matrix": build_requirement_matrix(context, markdown),
            "markdown_excerpt": markdown,
            "markdown_sections": _markdown_subsections(markdown, min_level=2),
        }
        return HumanApprovalCheckpoint(
            id="structure",
            stage="skeleton",
            node_id="skeleton",
            title="Проверка структуры README",
            summary="Черновик структуры готов и требует подтверждения перед генерацией теории.",
            resume_from_node="theory",
            allowed_targets=["title", "annotation", "chapter_1", "chapter_2", "chapter_3", "skeleton"],
            artifact=artifact,
        )

    @staticmethod
    def _annotation_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        artifact = {
            "title": str(context.get("title") or ""),
            "annotation": _annotation_text(context.get("annotation")),
        }
        return HumanApprovalCheckpoint(
            id="annotation",
            stage="annotation",
            node_id="skeleton",
            title="Проверка аннотации",
            summary="Аннотация готова и требует подтверждения методолога перед генерацией теории.",
            resume_from_node="theory",
            allowed_targets=["annotation"],
            artifact=artifact,
        )

    @staticmethod
    def _theory_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        theory_parts = [_part_summary(part) for part in context.get("theory_parts") or []]
        chapter_markdown = _markdown_section(str(context.get("markdown") or ""), "глава 2")
        if not chapter_markdown and theory_parts:
            chapter_markdown = _theory_parts_markdown(context.get("theory_parts") or [])
        chapter_markdown = normalize_markdown_display_blocks(chapter_markdown)
        artifact = {
            "title": str(context.get("title") or ""),
            "summary": f"Сгенерировано частей теории: {len(theory_parts)}",
            "theory_parts": theory_parts,
            "requirements_matrix": build_requirement_matrix(context, str(context.get("markdown") or "")),
            "markdown_excerpt": chapter_markdown,
            "markdown_sections": _markdown_subsections(chapter_markdown),
        }
        return HumanApprovalCheckpoint(
            id="theory",
            stage="theory",
            node_id="theory",
            title="Проверка теории",
            summary="Глава 2 готова и требует подтверждения методолога перед генерацией практики.",
            resume_from_node="practice",
            allowed_targets=["chapter_2", "theory"],
            artifact=artifact,
        )

    @staticmethod
    def _practice_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        practice_tasks = [_task_summary(task) for task in context.get("practice_tasks") or []]
        chapter_markdown = normalize_markdown_display_blocks(
            _markdown_section(str(context.get("markdown") or ""), "глава 3")
        )
        dataset_files = [
            {
                "path": str(item.get("path") or ""),
                "bytes": _data_size(item.get("data")),
            }
            for item in context.get("dataset_files") or []
            if isinstance(item, dict)
        ]
        artifact = {
            "title": str(context.get("title") or ""),
            "summary": f"Сгенерировано задач: {len(practice_tasks)}, materials-файлов: {len(dataset_files)}",
            "practice_tasks": practice_tasks,
            "dataset_files": dataset_files,
            "requirements_matrix": build_requirement_matrix(context, str(context.get("markdown") or "")),
            "markdown_excerpt": chapter_markdown,
            "markdown_sections": _markdown_subsections(chapter_markdown),
        }
        return HumanApprovalCheckpoint(
            id="practice",
            stage="practice",
            node_id="practice",
            title="Проверка практики и материалов",
            summary="Глава 3 и materials готовы и требуют подтверждения перед редакторской сборкой.",
            resume_from_node="global_quality",
            allowed_targets=["chapter_3", "practice", "dataset", "materials"],
            artifact=artifact,
        )

    @staticmethod
    def _quality_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        markdown = normalize_markdown_display_blocks(str(context.get("markdown") or ""))
        artifact = {
            "title": str(context.get("title") or ""),
            "summary": "README прошел глобальную редакторскую сборку.",
            "markdown_chars": len(markdown),
            "warnings_count": len(context.get("warnings") or []),
            "requirements_matrix": build_requirement_matrix(context, markdown),
            # Финальный checkpoint проверяет весь README, поэтому preview не должен
            # терять главу 3 после редакторской сборки.
            "markdown_excerpt": markdown,
            "markdown_sections": _markdown_subsections(markdown, min_level=2),
        }
        return HumanApprovalCheckpoint(
            id="quality",
            stage="final",
            node_id="global_quality",
            title="Проверка редакторской сборки",
            summary="Глобальная связность и редактура применены. Подтвердите перед финальной оценкой.",
            resume_from_node="evaluation",
            allowed_targets=["annotation", "chapter_1", "chapter_2", "chapter_3", "final"],
            artifact=artifact,
        )

    @staticmethod
    def _evaluation_checkpoint(context: dict[str, Any]) -> HumanApprovalCheckpoint:
        rubric = context.get("rubric_json") or {}
        if not isinstance(rubric, dict):
            rubric = {}
        items = rubric.get("items") or []
        failed_count = 0
        if isinstance(items, list):
            failed_count = sum(1 for item in items if isinstance(item, dict) and item.get("passed") is False)
        markdown = normalize_markdown_display_blocks(str(context.get("markdown") or ""))
        artifact = {
            "title": str(context.get("title") or ""),
            "summary": "Финальная оценка завершена. Подтвердите перед сборкой результата.",
            "rubric_score": rubric.get("score") or rubric.get("total_score") or rubric.get("percentage"),
            "rubric_failed_count": failed_count,
            "issues_count": len(context.get("issues") or []),
            "requirements_matrix": build_requirement_matrix(context, markdown),
            # Финальная оценка должна показывать методологу тот же полный README,
            # который будет отправлен на сборку результата.
            "markdown_excerpt": markdown,
            "markdown_sections": _markdown_subsections(markdown, min_level=2),
        }
        return HumanApprovalCheckpoint(
            id="evaluation",
            stage="final",
            node_id="evaluation",
            title="Проверка финальной оценки",
            summary="Валидаторы завершили проверку. Методолог может подтвердить export или запросить точечные правки.",
            resume_from_node="finalize",
            allowed_targets=["annotation", "chapter_1", "chapter_2", "chapter_3", "final"],
            artifact=artifact,
        )


def build_requirement_matrix(context: dict[str, Any], markdown: str | None = None) -> list[dict[str, Any]]:
    """Build deterministic source/didactics pass-fail matrix for review UI."""
    markdown = normalize_markdown_display_blocks(str(markdown if markdown is not None else context.get("markdown") or ""))
    chapter_2 = _markdown_section(markdown, "глава 2")
    chapter_3 = _markdown_section(markdown, "глава 3")
    final_section = _final_section(markdown)
    dataset_files = [item for item in context.get("dataset_files") or [] if isinstance(item, dict)]
    theory_headers = re.findall(r"^###\s+(.+?)\s*$", chapter_2, flags=re.M)
    task_blocks = _practice_task_blocks(chapter_3)

    has_h1 = bool(re.search(r"^#\s+.+$", markdown, flags=re.M))
    h1 = re.search(r"^#\s+(.+?)\s*$", markdown, flags=re.M)
    h1_words = len(h1.group(1).split()) if h1 else 0
    has_toc = bool(re.search(r"^##\s+(?:Содержание|Оглавление|Content|Мазмун)\s*$", markdown, flags=re.M))
    has_chapters = all(
        re.search(rf"^##\s+Глава\s+{chapter}\b", markdown, flags=re.M)
        for chapter in ("1", "2", "3")
    )
    has_final = bool(final_section.strip())

    canonical_theory = bool(theory_headers) and all(re.match(r"2\.\d+\.", header) for header in theory_headers)
    legacy_theory_count = len(re.findall(r"^###\s+Часть\s+\d+\.", chapter_2, flags=re.M))

    canonical_tasks = bool(task_blocks) and all(
        re.match(r"###\s+Задание\s+\d+\.", block.strip()) for block in task_blocks
    )
    task_template_ok = bool(task_blocks) and all(
        _has_markdown_label(block, "Что нужно сделать")
        and _has_markdown_label(block, "Что должно получиться")
        and _has_markdown_label(block, "Формат сдачи")
        and _has_markdown_label(block, "Переход к следующему заданию")
        for block in task_blocks
    )
    p2p_ok = bool(task_blocks) and all(_task_has_p2p_outcomes(block) for block in task_blocks)
    story_chain_ok = (
        context.get("story_map_contract") is not None
        or context.get("practice_plan_contract") is not None
        or "Переход к следующему заданию" in chapter_3
    )
    final_ok = has_final and not re.search(r"следующ(?:ий|ем)\s+проект", final_section, flags=re.I)

    return [
        _matrix_item(
            "structure",
            "Структура README",
            has_h1 and 1 <= h1_words <= 3 and has_toc and has_chapters and has_final,
            f"H1={h1_words} слов, TOC={has_toc}, главы 1-3={has_chapters}, финал={has_final}",
        ),
        _matrix_item(
            "theory",
            "Формат теории",
            canonical_theory and legacy_theory_count == 0,
            f"canonical 2.N={len(theory_headers)}, legacy Часть={legacy_theory_count}",
        ),
        _matrix_item(
            "practice_template",
            "Шаблон практики",
            canonical_tasks and task_template_ok,
            f"заданий={len(task_blocks)}, canonical={canonical_tasks}, pdf_blocks={task_template_ok}",
        ),
        _matrix_item(
            "p2p",
            "P2P-проверяемость",
            p2p_ok,
            "в каждом задании есть 2+ наблюдаемых результата и путь/артефакт",
        ),
        _matrix_item(
            "story_chain",
            "Единая цепочка",
            story_chain_ok,
            "есть story/practice contract или публичные переходы между заданиями",
        ),
        _matrix_item(
            "materials",
            "Сгенерированные данные",
            bool(dataset_files) or bool(context.get("evidence_specs")) or bool(context.get("practice_tasks")),
            f"materials={len(dataset_files)}, evidence_specs={len(context.get('evidence_specs') or [])}",
        ),
        _matrix_item(
            "final_closure",
            "Финальное завершение",
            final_ok,
            "финальный раздел завершает текущий проект без анонса следующего",
        ),
    ]


def _part_summary(part: Any) -> dict[str, Any]:
    title = _get_value(part, "title") or _get_value(part, "heading") or _get_value(part, "name")
    text = (
        _get_value(part, "text")
        or _get_value(part, "content")
        or _get_value(part, "body")
        or _get_value(part, "text_markdown")
        or ""
    )
    example = _get_value(part, "example") or ""
    combined_text = " ".join([str(text or ""), str(example or "")]).strip()
    return {
        "title": str(title or "Часть теории"),
        "words": len(combined_text.split()),
    }


def _task_summary(task: Any) -> dict[str, Any]:
    title = _get_value(task, "title") or _get_value(task, "name") or _get_value(task, "task_title")
    objective = _get_value(task, "objective") or _get_value(task, "goal") or _get_value(task, "description")
    return {
        "title": str(title or "Практическая задача"),
        "objective": _truncate_text(str(objective or ""), 220),
    }


def _get_value(value: Any, field: str) -> Any:
    if isinstance(value, dict):
        return value.get(field)
    return getattr(value, field, None)


def _markdown_section(markdown: str, heading_marker: str, limit: int = 1800) -> str:
    if not markdown:
        return ""
    marker = heading_marker.lower()
    lines = markdown.splitlines()
    start_index = None
    start_level = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip().lower()
        if marker in title:
            start_index = index
            start_level = len(stripped) - len(stripped.lstrip("#"))
            break
    if start_index is None:
        return _truncate_text(markdown, limit)
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


def _annotation_text(annotation: Any) -> str:
    if isinstance(annotation, dict):
        return str(annotation.get("text") or "")
    if hasattr(annotation, "text"):
        return str(annotation.text or "")
    return ""


def _checkpoint_artifact_hash(checkpoint: HumanApprovalCheckpoint) -> str:
    payload = checkpoint.model_dump(mode="json", exclude={"artifact_hash"})
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _checkpoint_already_approved(context: dict[str, Any], checkpoint: dict[str, Any]) -> bool:
    checkpoint_id = str(checkpoint.get("id") or "")
    checkpoint_hash = str(checkpoint.get("artifact_hash") or "")
    if not checkpoint_id or not checkpoint_hash:
        return False

    for action in reversed(list(context.get("methodology_review_actions") or [])):
        if not isinstance(action, dict) or action.get("action") != "approved":
            continue
        details = action.get("details") if isinstance(action.get("details"), dict) else {}
        if (
            str(details.get("checkpoint_id") or "") == checkpoint_id
            and str(details.get("checkpoint_hash") or "") == checkpoint_hash
        ):
            return True
        approved_checkpoint = details.get("checkpoint")
        if isinstance(approved_checkpoint, dict) and (
            str(approved_checkpoint.get("id") or "") == checkpoint_id
            and str(approved_checkpoint.get("artifact_hash") or "") == checkpoint_hash
        ):
            return True
    return False


def _theory_parts_markdown(parts: list[Any]) -> str:
    blocks = ["## Глава 2. Теоретический блок"]
    for index, part in enumerate(parts, 1):
        title = _get_value(part, "title") or _get_value(part, "heading") or f"Часть {index}"
        body = (
            _get_value(part, "text")
            or _get_value(part, "content")
            or _get_value(part, "body")
            or _get_value(part, "text_markdown")
            or ""
        )
        example = _get_value(part, "example") or ""
        blocks.append(f"### 2.{index}. {title}".strip())
        if body:
            blocks.append(str(body).strip())
        if example:
            blocks.append(str(example).strip())
    return "\n\n".join(block for block in blocks if block).strip()


def _markdown_outline(markdown: str) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", str(markdown or ""), flags=re.MULTILINE):
        outline.append(
            {
                "level": len(match.group(1)),
                "title": match.group(2).strip(),
            }
        )
    return outline


def _markdown_subsections(section_markdown: str, *, min_level: int = 3) -> list[dict[str, str]]:
    """Split a chapter into addressable markdown subsections for review UI."""
    if not section_markdown:
        return []

    matches = [
        match
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", section_markdown, flags=re.MULTILINE)
        if len(match.group(1)) >= min_level
    ]
    sections: list[dict[str, str]] = []
    used_ids: set[str] = set()
    for index, match in enumerate(matches):
        level = len(match.group(1))
        title = match.group(2).strip()
        end = len(section_markdown)
        for next_match in matches[index + 1 :]:
            if len(next_match.group(1)) <= level:
                end = next_match.start()
                break
        section_id = _unique_section_id(_slug_text(title), used_ids)
        sections.append(
            {
                "id": section_id,
                "title": title,
                "markdown": section_markdown[match.start() : end].strip(),
            }
        )
    return sections


def _slug_text(value: str) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-zа-яё0-9]+", "_", text, flags=re.I)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:80] or "section"


def _unique_section_id(base: str, used_ids: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used_ids.add(candidate)
    return candidate


def _truncate_text(text: str, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return f"{value[:limit].rstrip()}..."


def _matrix_item(item_id: str, title: str, passed: bool, evidence: str) -> dict[str, Any]:
    return RequirementMatrixItem(
        id=item_id,
        title=title,
        status="pass" if passed else "fail",
        passed=bool(passed),
        evidence=evidence,
    ).model_dump(mode="json")


def _has_markdown_label(text: str, label: str) -> bool:
    return bool(re.search(rf"\*\*{re.escape(label)}:?\*\*", text, flags=re.I))


def _practice_task_blocks(chapter_3: str) -> list[str]:
    raw = re.split(r"(?=^###\s+(?:Задание|Задача)\s+\d+\.)", chapter_3, flags=re.M)
    return [chunk.strip() for chunk in raw if chunk.strip().startswith("###")]


def _task_has_p2p_outcomes(task_block: str) -> bool:
    result_match = re.search(
        r"\*\*(?:Что должно получиться|Критерии проверки.*?):?\*\*\s*(.+?)(?=\n\*\*|\n###|\Z)",
        task_block,
        flags=re.S | re.I,
    )
    if not result_match:
        return False
    checklist = [
        line
        for line in result_match.group(1).splitlines()
        if re.match(r"^\s*[-*]\s*(?:\[[ xX]?\]\s*)?.{10,}", line)
    ]
    has_location = bool(re.search(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./{}:\-]+\.[A-Za-z0-9]+", task_block))
    has_artifact = bool(re.search(r"\b(файл|документ|таблиц|схем|артефакт|отчет|отчёт|README|Markdown)\b", task_block, re.I))
    return len(checklist) >= 2 and (has_location or has_artifact)


def _final_section(markdown: str) -> str:
    matches = list(re.finditer(r"^##\s+(.+?)\s*$", markdown, flags=re.M))
    for index, match in enumerate(matches):
        title = match.group(1).strip().lower()
        if not re.search(r"(заключение|итог проекта|финал проекта|завершение проекта)", title, flags=re.I):
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        return markdown[match.start():end].strip()
    return ""


def _data_size(data: Any) -> int:
    if data is None:
        return 0
    if isinstance(data, bytes):
        return len(data)
    return len(str(data).encode("utf-8"))
