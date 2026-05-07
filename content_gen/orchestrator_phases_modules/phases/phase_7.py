"""Compatibility wrapper for final translation."""

from __future__ import annotations

from ...models.schemas import ProjectSeed


def phase_7_translate(
    orchestrator,
    seed: ProjectSeed,
    md: str,
    target_language: str,
) -> tuple[str, str]:
    """Execute translation through the canonical phase executor."""
    from ...phase_executors import TranslationPhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return TranslationPhaseExecutor(runtime).execute(seed, md, target_language)
