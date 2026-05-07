"""Compatibility wrapper for Phase 3 practice generation."""

from __future__ import annotations

from typing import Any

from ...models.schemas import PracticeTask, ProjectSeed
from ...practice_phase_executor import (
    _apply_critic_suggestions,
    _build_theory_summary,
    _clean_inline_text,
    _format_approach_bullet,
    _observable_results,
    _render_bonus_block,
    _render_practice_block,
    _render_public_task,
    _replace_bonus_content,
    _strip_check_marker,
    _submission_format,
    _task_location,
    _transition_text,
)


def phase_3_practice(
    orchestrator,
    seed: ProjectSeed,
    md: str,
    generate_bonus: bool,
    practice_plan_contract: Any | None = None,
    artifact_chain_plan: Any | None = None,
    section_context: dict[str, Any] | None = None,
) -> tuple[str, list[PracticeTask], list[Any], list[str]]:
    """Execute Phase 3 through the canonical practice phase executor."""
    from ...practice_phase_executor import PracticePhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return PracticePhaseExecutor(runtime).execute(
        seed,
        md,
        generate_bonus,
        practice_plan_contract=practice_plan_contract,
        artifact_chain_plan=artifact_chain_plan,
        section_context=section_context,
    )
