"""Structure phase executor for title, annotation, and README skeleton."""

import logging

from .generation_runtime import GenerationRuntimeContainer
from .models.flow_state import ProjectBlueprint
from .models.schemas import Annotation, IntroSection, ProjectContextMeta, ProjectSeed
from .validators.structural_preflight import StructuralPreflightResult

logger = logging.getLogger("content_gen.orchestrator.phases.phase_1")


def _execute_skeleton_phase(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
    generate_bonus: bool
) -> tuple[str, StructuralPreflightResult, str, Annotation, IntroSection, ProjectBlueprint]:
    """
    Phase 1: Каркас с StructuralPreflight.
    
    Args:
        orchestrator: Экземпляр OrchestratorPhases
        seed: Проектный seed
        context_meta: Метаданные curriculum context
        generate_bonus: Генерировать ли бонусные задания
        
    Returns:
        (md, preflight_result, title, annotation, intro_section, blueprint)
    """
    title, annotation = _generate_title_annotation(orchestrator, seed, context_meta)
    md, preflight_result, intro_section, blueprint = _build_structure(
        orchestrator,
        seed,
        context_meta,
        generate_bonus,
        title,
        annotation,
    )

    return md, preflight_result, title, annotation, intro_section, blueprint


def _generate_title_annotation(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
) -> tuple[str, Annotation]:
    """Generate the project title and annotation as a separately reviewable artifact."""
    logger.info("🔄 Phase 1 | TitleAnnotation")
    ta = orchestrator.title_annot.generate(seed, context_meta)
    annotation = Annotation(text=ta.annotation.text, chars=len(ta.annotation.text))
    return ta.title, annotation


def _build_structure(
    orchestrator,
    seed: ProjectSeed,
    context_meta: ProjectContextMeta,
    generate_bonus: bool,
    title: str,
    annotation: Annotation | dict,
) -> tuple[str, StructuralPreflightResult, IntroSection, ProjectBlueprint]:
    """Build the README skeleton and intro using an already approved title/annotation."""
    logger.info("🔄 Phase 1 | Skeleton")
    annotation_text = _annotation_text(annotation)
    sk = orchestrator.skeleton.build(language=seed.language, has_bonus=generate_bonus)
    md = orchestrator.skeleton.stitch(title=title, annotation_md=annotation_text, sk=sk)

    logger.info("🔄 Phase 1 | IntroRules")
    intro_res = orchestrator.intro.generate(seed, context_meta, annotation_text=annotation_text)
    md = orchestrator.intro.inject_into_markdown(md, intro_res)
    intro_section = IntroSection(
        intro_text=intro_res.intro_text,
        instruction_text=intro_res.instruction_text,
    )
    blueprint = ProjectBlueprint(
        language=str(seed.language),
        has_bonus=generate_bonus,
        section_order=["title", "annotation", "toc", "intro", "theory", "practice"] + (["bonus"] if generate_bonus else []),
        chapter_titles={
            "toc": sk.toc_anchor.splitlines()[0].strip(),
            "intro": sk.ch1.splitlines()[0].strip(),
            "theory": sk.ch2.splitlines()[0].strip(),
            "practice": sk.ch3.splitlines()[0].strip(),
            "bonus": sk.bonus.splitlines()[0].strip() if sk.bonus else "",
        },
        intro_subsections=["Введение", "Инструкция"],
        planned_tasks_count=seed.tasks_count,
        planned_task_complexity=seed.task_complexity,
    )

    # Structural Preflight
    logger.info("🔄 Phase 1 | StructuralPreflight")
    preflight_result = orchestrator.structural_preflight.check(md, has_bonus=generate_bonus)

    if not preflight_result.passed:
        logger.warning(f"⚠️ Structural Preflight: {len(preflight_result.hard_issues)} HARD проблем")
        # Попытка исправления через Regeneration
        if preflight_result.hard_issues:
            fixable_issues = [i for i in preflight_result.hard_issues if i.fixable]
            if fixable_issues:
                logger.info("🔄 Phase 1 | Regeneration (fix structure)")
                issues_text = "\n".join(f"- {i.message}" for i in fixable_issues[:3])
                try:
                    md = orchestrator.regeneration.regenerate(
                        original_md=md,
                        comments=f"Исправь следующие проблемы структуры:\n{issues_text}",
                        language=seed.language
                    ).regenerated_md
                    # Повторная проверка
                    preflight_result = orchestrator.structural_preflight.check(md, has_bonus=generate_bonus)
                except Exception as e:
                    logger.warning(f"⚠️ Regeneration не удался: {e}")

    return md, preflight_result, intro_section, blueprint


def _annotation_text(annotation: Annotation | dict) -> str:
    """Read annotation text from either hydrated schema or persisted paused-state dict."""
    if isinstance(annotation, dict):
        return str(annotation.get("text") or "")
    return str(getattr(annotation, "text", "") or "")


class StructurePhaseExecutor:
    """Execute Phase 1 title, annotation, and README structure steps."""

    def __init__(self, runtime: GenerationRuntimeContainer) -> None:
        self.runtime = runtime

    def build_skeleton(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
        generate_bonus: bool,
    ) -> tuple[str, StructuralPreflightResult, str, Annotation, IntroSection, ProjectBlueprint]:
        return _execute_skeleton_phase(self.runtime, seed, context_meta, generate_bonus)

    def generate_title_annotation(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
    ) -> tuple[str, Annotation]:
        return _generate_title_annotation(self.runtime, seed, context_meta)

    def build_structure(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
        generate_bonus: bool,
        title: str,
        annotation: Annotation | dict,
    ) -> tuple[str, StructuralPreflightResult, IntroSection, ProjectBlueprint]:
        return _build_structure(self.runtime, seed, context_meta, generate_bonus, title, annotation)
