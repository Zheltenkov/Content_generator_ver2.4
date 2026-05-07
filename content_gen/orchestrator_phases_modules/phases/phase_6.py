"""Compatibility wrapper for final evaluation."""

from __future__ import annotations

from typing import Any

from ...models.schemas import ProjectSeed


def phase_6_final_evaluation(
    orchestrator,
    seed: ProjectSeed,
    md: str,
) -> tuple[dict[str, Any], list[Any]]:
    """Execute final evaluation through the canonical phase executor."""
    from ...phase_executors import EvaluationPhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return EvaluationPhaseExecutor(runtime).execute(seed, md)
