"""Compatibility wrapper for Phase 4 global quality."""

from __future__ import annotations

from ...models.schemas import ProjectSeed


def phase_4_global_quality(
    orchestrator,
    seed: ProjectSeed,
    md: str,
) -> str:
    """Execute Phase 4 through the canonical phase executor."""
    from ...phase_executors import QualityPhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return QualityPhaseExecutor(runtime).execute(seed, md)
