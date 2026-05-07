"""Compatibility wrapper for Phase 0 context generation."""

from __future__ import annotations

from typing import Any

from ...agents.context_analysis import ContextAnalysisResult
from ...context_phase_executor import (
    _build_context_summary,
    _build_narrative_anchor,
    _collect_project_values,
    _execute_context_phase,
    _normalize_list,
    _safe_int,
)
from ...curriculum.models import CurriculumEntry
from ...models.flow_state import ProjectContextBundle
from ...models.schemas import ProjectContextMeta, ProjectSeed


def phase_0_context(
    orchestrator,
    raw_input: dict[str, Any],
    track_files: list[str] = None,
) -> tuple[
    ProjectSeed,
    ProjectContextMeta,
    ContextAnalysisResult,
    ProjectContextBundle,
    list[CurriculumEntry],
    list[str],
]:
    """Execute Phase 0 through the canonical context phase executor."""
    from ...context_phase_executor import ContextPhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return ContextPhaseExecutor(runtime).execute(raw_input, track_files)
