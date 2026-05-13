"""Pure artifact helpers for methodology review UI payloads."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from content_gen.methodology import build_requirement_matrix
from content_gen.models.readme_document import ReadmeDocument
from content_gen.utils.markdown_display_normalizer import normalize_markdown_display_blocks

JsonDict = dict[str, Any]


def methodology_human_review_enabled(
    project_seed_payload: JsonDict,
    context: JsonDict | None = None,
) -> bool:
    """Return whether a request should pause for human methodologist approval."""
    raw_value = project_seed_payload.get("methodology_human_review")
    if raw_value is not None:
        if isinstance(raw_value, bool):
            return raw_value
        if isinstance(raw_value, str):
            return raw_value.strip().lower() in {"1", "true", "yes", "on", "enabled"}
        return bool(raw_value)

    if context:
        if context.get("methodology_human_review_enabled") is True:
            return True
        if context.get("human_approval_checkpoint") or context.get("human_approval_checkpoints"):
            return True
    return False


def annotation_text_from_context(context: JsonDict) -> str:
    """Extract annotation text from dict or typed annotation object."""
    annotation = context.get("annotation")
    if isinstance(annotation, dict):
        return str(annotation.get("text") or "")
    if hasattr(annotation, "text"):
        return str(annotation.text or "")
    return ""


def context_preview_markdown(context: JsonDict) -> str:
    """Build the most useful README preview from a paused flow context."""
    markdown = normalize_markdown_display_blocks(str(context.get("markdown") or "")).strip()
    if markdown:
        return markdown

    title = str(context.get("title") or "").strip()
    annotation = annotation_text_from_context(context).strip()
    blocks: list[str] = []
    if title:
        blocks.append(f"# {title}")
    if annotation:
        blocks.append(annotation)
    return "\n\n".join(blocks).strip()


def markdown_outline(markdown: str) -> list[JsonDict]:
    """Return a serializable Markdown heading outline."""
    return [
        {"level": len(match.group(1)), "title": match.group(2).strip()}
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", markdown or "", flags=re.MULTILINE)
    ]


def markdown_section(markdown: str, marker: str) -> str:
    """Return a section whose heading title contains marker."""
    return ReadmeDocument.from_markdown(markdown).section_markdown_by_title_fragment(marker).strip()


def markdown_subsections(markdown: str, *, min_level: int = 3) -> list[dict[str, str]]:
    """Split Markdown into tab-ready sections by heading level."""
    return ReadmeDocument.from_markdown(markdown).markdown_subsections(min_level=min_level)


def checkpoint_payload_hash(checkpoint: JsonDict) -> str:
    """Hash checkpoint payload excluding previous artifact hash."""
    payload = {key: value for key, value in checkpoint.items() if key != "artifact_hash"}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def is_final_checkpoint_payload(checkpoint: Any) -> bool:
    """Return whether checkpoint payload represents the final README review."""
    if not isinstance(checkpoint, dict):
        return False
    stage = str(checkpoint.get("stage") or "").lower()
    checkpoint_id = str(checkpoint.get("id") or "").lower()
    node_id = str(checkpoint.get("node_id") or "").lower()
    return stage == "final" or checkpoint_id in {"quality", "evaluation"} or node_id in {
        "global_quality",
        "evaluation",
    }


def refresh_checkpoint_artifact(context: JsonDict) -> None:
    """Keep the visible human-review artifact aligned with context Markdown."""
    checkpoint = context.get("human_approval_checkpoint")
    if not isinstance(checkpoint, dict):
        return

    markdown = context_preview_markdown(context)
    artifact = dict(checkpoint.get("artifact") or {})
    stage = str(checkpoint.get("stage") or checkpoint.get("id") or "")
    title = str(context.get("title") or artifact.get("title") or "").strip()
    if title:
        artifact["title"] = title

    if stage in {"title", "annotation"}:
        artifact["annotation"] = annotation_text_from_context(context)
    elif stage == "skeleton":
        artifact["markdown_excerpt"] = markdown
        artifact["structure_outline"] = markdown_outline(markdown)
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = markdown_subsections(markdown, min_level=2)
    elif stage == "theory":
        chapter = markdown_section(markdown, "глава 2") or markdown
        artifact["markdown_excerpt"] = normalize_markdown_display_blocks(chapter)
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = markdown_subsections(chapter)
    elif stage == "practice":
        chapter = markdown_section(markdown, "глава 3") or markdown
        artifact["markdown_excerpt"] = normalize_markdown_display_blocks(chapter)
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = markdown_subsections(chapter)
        artifact["dataset_files"] = [
            {"path": str(item.get("path") or ""), "bytes": len(item.get("data") or b"")}
            for item in context.get("dataset_files") or []
            if isinstance(item, dict)
        ]
    elif is_final_checkpoint_payload(checkpoint):
        artifact["markdown_excerpt"] = markdown
        artifact["requirements_matrix"] = build_requirement_matrix(context, markdown)
        artifact["markdown_sections"] = markdown_subsections(markdown, min_level=2)
    else:
        artifact["markdown_excerpt"] = markdown[:5000]

    checkpoint["artifact"] = artifact
    checkpoint["artifact_hash"] = checkpoint_payload_hash(checkpoint)
    context["human_approval_checkpoint"] = checkpoint
