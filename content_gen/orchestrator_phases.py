"""
Модуль фаз для нового архитектурного подхода.

Разделяет пайплайн на 6 фаз с встроенными проверками:
- Phase 0: Intent & curriculum context
- Phase 1: Каркас (с StructuralPreflight)
- Phase 2: Теория (с TheoryChecks и локальной Regeneration)
- Phase 3: Практика (с PracticeChecks)
- Phase 4: Глобальное качество
- Phase 5: Итоговая оценка
- Phase 6: Перевод
"""

from __future__ import annotations

import logging
from typing import Any

from .agents.context_analysis import ContextAnalysisResult
from .models.schemas import Annotation, IntroSection, PracticeTask, ProjectContextMeta, ProjectSeed, TheoryPart
from .models.flow_state import ProjectBlueprint, ProjectContextBundle
from .generation_runtime import GenerationRuntimeContainer
from .phase_executors import (
    ContextPhaseExecutor,
    EvaluationPhaseExecutor,
    PracticePhaseExecutor,
    QualityPhaseExecutor,
    StructurePhaseExecutor,
    TheoryPhaseExecutor,
    TranslationPhaseExecutor,
)
from .validators.structural_preflight import StructuralPreflightResult

# Настраиваем logger для orchestrator_phases
logger = logging.getLogger("content_gen.orchestrator_phases")


class OrchestratorPhases:
    """
    Новый подход к оркестрации с фазами и встроенными проверками.
    
    Каждая фаза:
    1. Генерирует контент
    2. Проверяет критерии
    3. При необходимости применяет Regeneration
    4. Переходит к следующей фазе только если HARD критерии пройдены
    """

    def __init__(self, llm_client, cancellation_token=None, progress_tracker=None):
        """Инициализация фазового оркестратора."""
        object.__setattr__(
            self,
            "runtime",
            GenerationRuntimeContainer(
                llm_client,
                cancellation_token=cancellation_token,
                progress_tracker=progress_tracker,
            ),
        )
        object.__setattr__(self, "context_executor", ContextPhaseExecutor(self.runtime))
        object.__setattr__(self, "structure_executor", StructurePhaseExecutor(self.runtime))
        object.__setattr__(self, "theory_executor", TheoryPhaseExecutor(self.runtime))
        object.__setattr__(self, "practice_executor", PracticePhaseExecutor(self.runtime))
        object.__setattr__(self, "quality_executor", QualityPhaseExecutor(self.runtime))
        object.__setattr__(self, "evaluation_executor", EvaluationPhaseExecutor(self.runtime))
        object.__setattr__(self, "translation_executor", TranslationPhaseExecutor(self.runtime))

    def __getattr__(self, name: str) -> Any:
        """Delegate legacy attribute reads to the runtime container."""
        runtime = object.__getattribute__(self, "runtime")
        try:
            return getattr(runtime, name)
        except AttributeError as exc:
            raise AttributeError(f"{type(self).__name__} has no attribute {name!r}") from exc

    def __setattr__(self, name: str, value: Any) -> None:
        """Delegate legacy mutable state writes to the runtime container."""
        if name.endswith("_executor") or name == "runtime":
            object.__setattr__(self, name, value)
            return
        runtime = self.__dict__.get("runtime")
        if runtime is not None and hasattr(runtime, name):
            setattr(runtime, name, value)
            return
        object.__setattr__(self, name, value)

    def _log_phase(self, phase_name: str, sub_phase: str = ""):
        """Логирует текущую фазу."""
        if sub_phase:
            logger.info(f"🔄 {phase_name} | {sub_phase}")
        else:
            logger.info(f"🔄 {phase_name}")

    def phase_0_context(
        self,
        raw_input: dict[str, Any],
        track_files: list[str] = None
    ) -> tuple[
        ProjectSeed,
        ProjectContextMeta,
        ContextAnalysisResult,
        ProjectContextBundle,
        list[Any],
        list[str],
    ]:
        """
        Phase 0: Intent & curriculum context.
        
        Returns:
            (seed, context_meta, context_analysis, context_bundle, similar_projects, warnings)
        """
        return self.context_executor.execute(raw_input, track_files)

    def phase_1_skeleton(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
        generate_bonus: bool
    ) -> tuple[str, StructuralPreflightResult, str, Annotation, IntroSection, ProjectBlueprint]:
        """
        Phase 1: Каркас с StructuralPreflight.
        
        Returns:
            (md, preflight_result, title, annotation, intro_section, blueprint)
        """
        return self.structure_executor.build_skeleton(seed, context_meta, generate_bonus)

    def phase_1_title_annotation(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
    ) -> tuple[str, Annotation]:
        """Phase 1a: generate title and annotation for explicit methodologist approval."""
        return self.structure_executor.generate_title_annotation(seed, context_meta)

    def phase_1_structure(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
        generate_bonus: bool,
        title: str,
        annotation: Annotation,
    ) -> tuple[str, StructuralPreflightResult, IntroSection, ProjectBlueprint]:
        """Phase 1b: build README skeleton after title/annotation approval."""
        return self.structure_executor.build_structure(seed, context_meta, generate_bonus, title, annotation)

    def phase_2_theory(
        self,
        seed: ProjectSeed,
        context_meta: ProjectContextMeta,
        md: str,
        practice_plan_contract: Any | None = None,
        section_context: dict[str, Any] | None = None,
    ) -> tuple[str, list[TheoryPart], list[Any], list[str]]:
        """
        Phase 2: Теория с проверками и локальной Regeneration.
        
        Returns:
            (md, theory_parts, issues, warnings)
        """
        return self.theory_executor.execute(
            seed,
            context_meta,
            md,
            practice_plan_contract=practice_plan_contract,
            section_context=section_context,
        )

    def phase_3_practice(
        self,
        seed: ProjectSeed,
        md: str,
        generate_bonus: bool,
        practice_plan_contract: Any | None = None,
        artifact_chain_plan: Any | None = None,
        section_context: dict[str, Any] | None = None,
    ) -> tuple[str, list[PracticeTask], list[Any], list[str]]:
        """
        Phase 3: Практика с проверками.
        
        Returns:
            (md, practice_tasks, issues, warnings)
        """
        return self.practice_executor.execute(
            seed,
            md,
            generate_bonus,
            practice_plan_contract=practice_plan_contract,
            artifact_chain_plan=artifact_chain_plan,
            section_context=section_context,
        )

    def phase_4_global_quality(
        self,
        seed: ProjectSeed,
        md: str
    ) -> str:
        """
        Phase 4: Глобальное качество (когерентность, TOC, стиль).
        
        Returns:
            md
        """
        return self.quality_executor.execute(seed, md)

    def phase_7_translate(
        self,
        seed: ProjectSeed,
        md: str,
        target_language: str
    ) -> tuple[str, str]:
        """
        Phase 6: Перевод на целевой язык (после оценки критериев).
        
        Returns:
            (original_md, translated_md)
        """
        return self.translation_executor.execute(seed, md, target_language)

    def phase_6_final_evaluation(
        self,
        seed: ProjectSeed,
        md: str
    ) -> tuple[dict[str, Any], list[Any]]:
        """
        Phase 6: Итоговая оценка (validators + rubric).
        
        Returns:
            (rubric_json, all_issues)
        """
        return self.evaluation_executor.execute(seed, md)

    def _create_empty_context(self, thematic_block: str):
        """Создает пустой curriculum context для fallback."""
        return self.runtime.create_empty_context(thematic_block)

    def _create_empty_context_analysis(self):
        """Создает пустой context-analysis результат для fallback."""
        return self.runtime.create_empty_context_analysis()
