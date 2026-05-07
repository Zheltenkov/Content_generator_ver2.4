"""Compatibility wrapper for Phase 2 theory generation."""

from __future__ import annotations

from typing import Any

from ...models.schemas import ProjectContextMeta, ProjectSeed, TheoryPart
from ...theory_phase_executor import (
    _parse_theory_part_markdown,
    _polish_theory_part,
    _remove_static_instruction_leaks,
    _render_theory_part_markdown,
)


def phase_2_theory(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
    md: str,
    practice_plan_contract: Any | None = None,
    section_context: dict[str, Any] | None = None,
) -> tuple[str, list[TheoryPart], list[Any], list[str]]:
    """Execute Phase 2 through the canonical theory phase executor."""
    from ...theory_phase_executor import TheoryPhaseExecutor

    runtime = getattr(orchestrator, "runtime", orchestrator)
    return TheoryPhaseExecutor(runtime).execute(
        seed,
        context_meta,
        md,
        practice_plan_contract=practice_plan_contract,
        section_context=section_context,
    )
