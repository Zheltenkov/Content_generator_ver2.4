"""Compatibility wrappers for Phase 1 structure generation."""

from __future__ import annotations

from ...models.flow_state import ProjectBlueprint
from ...models.schemas import Annotation, IntroSection, ProjectContextMeta, ProjectSeed
from ...structure_phase_executor import (
    _annotation_text,
    _build_structure,
    _execute_skeleton_phase,
    _generate_title_annotation,
)
from ...validators.structural_preflight import StructuralPreflightResult


def phase_1_skeleton(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
    generate_bonus: bool,
) -> tuple[str, StructuralPreflightResult, str, Annotation, IntroSection, ProjectBlueprint]:
    """Execute Phase 1 skeleton through the canonical structure phase executor."""
    from ...structure_phase_executor import StructurePhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return StructurePhaseExecutor(runtime).build_skeleton(seed, context_meta, generate_bonus)


def phase_1_title_annotation(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
) -> tuple[str, Annotation]:
    """Execute Phase 1 title/annotation through the canonical structure phase executor."""
    from ...structure_phase_executor import StructurePhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return StructurePhaseExecutor(runtime).generate_title_annotation(seed, context_meta)


def phase_1_structure(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
    generate_bonus: bool,
    title: str,
    annotation: Annotation | dict,
) -> tuple[str, StructuralPreflightResult, IntroSection, ProjectBlueprint]:
    """Execute Phase 1 structure through the canonical structure phase executor."""
    from ...structure_phase_executor import StructurePhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return StructurePhaseExecutor(runtime).build_structure(seed, context_meta, generate_bonus, title, annotation)
