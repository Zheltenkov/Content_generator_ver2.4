"""AgentFlow node handlers for content generation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .agents.flow import FlowNodeOutput
from .agents.task_planner import TaskPlanner
from .domain_contracts import SectionContextPolicy
from .models.generation_context import GenerationContext
from .node_services import (
    ContextNodeService,
    EvaluationNodeService,
    FinalizeNodeService,
    PracticeNodeService,
    QualityNodeService,
    SectionContextRecorder,
    SkeletonNodeService,
    TaskPlanningNodeService,
    TheoryNodeService,
    TitleAnnotationNodeService,
    TranslationNodeService,
)
from .result_assembly import ResultAssembler

logger = logging.getLogger("content_gen.flow_handlers")


class GenerationFlowHandlers:
    """Own the concrete node implementations used by the content generation flow."""

    def __init__(
        self,
        phases: Any,
        task_planner: TaskPlanner,
        result_assembler: ResultAssembler,
        log_phase: Callable[[str, str], None],
        context_service: ContextNodeService | None = None,
        title_annotation_service: TitleAnnotationNodeService | None = None,
        task_planning_service: TaskPlanningNodeService | None = None,
        skeleton_service: SkeletonNodeService | None = None,
        theory_service: TheoryNodeService | None = None,
        practice_service: PracticeNodeService | None = None,
        quality_service: QualityNodeService | None = None,
        evaluation_service: EvaluationNodeService | None = None,
        translation_service: TranslationNodeService | None = None,
        finalize_service: FinalizeNodeService | None = None,
        section_context_recorder: SectionContextRecorder | None = None,
    ) -> None:
        self.phases = phases
        self.task_planner = task_planner
        self.result_assembler = result_assembler
        self.log_phase = log_phase
        self.section_context_recorder = section_context_recorder or SectionContextRecorder()
        self.context_service = context_service or self._default_context_service()
        self.title_annotation_service = title_annotation_service or self._default_title_annotation_service()
        self.task_planning_service = task_planning_service or self._default_task_planning_service()
        self.skeleton_service = skeleton_service or self._default_skeleton_service()
        self.theory_service = theory_service or self._default_theory_service()
        self.practice_service = practice_service or self._default_practice_service()
        self.quality_service = quality_service or self._default_quality_service()
        self.evaluation_service = evaluation_service or self._default_evaluation_service()
        self.translation_service = translation_service or self._default_translation_service()
        self.finalize_service = finalize_service or self._default_finalize_service()

    def registry(self) -> dict[str, Callable[[dict[str, Any]], FlowNodeOutput]]:
        """Return AgentFlow handler registry."""
        return {
            "context": self.node_context,
            "task_planning": self.node_task_planning,
            "title_annotation": self.node_title_annotation,
            "skeleton": self.node_skeleton,
            "theory": self.node_theory,
            "practice": self.node_practice,
            "global_quality": self.node_global_quality,
            "evaluation": self.node_evaluation,
            "translate": self.node_translate,
            "finalize": self.node_finalize,
        }

    def node_context(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("context", "Создание seed и контекста проекта из УП")
        result = self._require_service(self.context_service, "context").execute(GenerationContext.from_legacy(context))
        context["target_language"] = result.target_language
        context["generate_bonus"] = result.generate_bonus
        context.setdefault("warnings", []).extend(result.warnings)
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_task_planning(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("task_planning", "Планирование практических задач")
        result = self._require_service(self.task_planning_service, "task_planning").execute(
            GenerationContext.from_legacy(context)
        )
        context.update(
            {
                "story_map_contract": result.story_map_contract,
                "practice_plan_contract": result.practice_plan_contract,
                "artifact_chain_plan": result.artifact_chain_plan,
                "evidence_specs": result.evidence_specs,
            }
        )
        context.setdefault("warnings", []).extend(result.warnings)
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_title_annotation(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("title_annotation", "Агент названия и аннотации")
        result = self._require_service(self.title_annotation_service, "title_annotation").execute(
            GenerationContext.from_legacy(context)
        )
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_skeleton(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("skeleton", "Агент каркаса: создание структуры README")
        result = self._require_service(self.skeleton_service, "skeleton").execute(GenerationContext.from_legacy(context))
        context.setdefault("warnings", []).extend(result.warnings)
        context.setdefault("issues", []).extend(result.serialized_issues)
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_theory(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("theory", "Теоретический агент: генерация теории")
        result = self._require_service(self.theory_service, "theory").execute(
            GenerationContext.from_legacy(context),
            context,
        )
        context.setdefault("issues", []).extend(result.serialized_issues)
        context.setdefault("warnings", []).extend(result.warnings)
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_practice(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("practice", "Практический агент: генерация практических задач")
        result = self._require_service(self.practice_service, "practice").execute(
            GenerationContext.from_legacy(context),
            context,
        )
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_global_quality(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("quality", "Агент качества: проверка и улучшение контента")
        result = self._require_service(self.quality_service, "quality").execute(GenerationContext.from_legacy(context))
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_translate(self, context: dict[str, Any]) -> FlowNodeOutput:
        seed = context["seed"]
        md = context["markdown"]

        logger.info("Translate context keys: %s", list(context.keys()))
        logger.info("Translate target_language before normalization: %r", context.get("target_language"))
        logger.info("Translate seed.language=%r", seed.language)

        target_language = context.get("target_language")
        if target_language is None:
            logger.error(
                "target_language is absent in context; seed.language=%r. Using 'ru' fallback.",
                seed.language,
            )
            target_language = "ru"
        else:
            target_language = str(target_language) if not isinstance(target_language, str) else target_language

        target_language = target_language.lower().strip() if isinstance(target_language, str) else target_language

        logger.info(
            "Translate target_language='%s' (seed.language=%s, context.target_language=%s)",
            target_language,
            seed.language,
            context.get("target_language"),
        )

        if target_language != "ru":
            self.log_phase("translate", f"Агент перевода: перевод на {target_language}")
            logger.info("Starting translation to '%s'", target_language)
        else:
            self.log_phase("translate", "Агент перевода: пропуск (язык уже русский)")
            logger.info("Translation skipped because target_language='%s'", target_language)

        result = self._require_service(self.translation_service, "translate").execute(
            GenerationContext.from_legacy(context),
            target_language=target_language,
        )
        original_md = result.markdown
        translated_md = result.translated_markdown

        logger.info(
            "Translate result: original_chars=%s translated_chars=%s differs=%s",
            len(original_md),
            len(translated_md),
            original_md != translated_md,
        )
        if original_md != translated_md:
            logger.info("Translation first 200 chars: %s", translated_md[:200])
        else:
            logger.warning("Translation output equals original. First 200 chars: %s", translated_md[:200])

        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_evaluation(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("evaluation", "Агент оценки: проверка критериев")
        result = self._require_service(self.evaluation_service, "evaluation").execute(
            GenerationContext.from_legacy(context)
        )
        context["issues"].extend(result.serialized_issues)
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    def node_finalize(self, context: dict[str, Any]) -> FlowNodeOutput:
        self.log_phase("finalize", "Финальная обработка: подготовка результата")
        result = self._require_service(self.finalize_service, "finalize").execute(context)
        return FlowNodeOutput(updates=result.updates(), issues=result.issues, status=result.status)

    @staticmethod
    def _serialize_issues(issues: list[Any]) -> list[Any]:
        """Serialize issue objects for report/json storage."""
        return [issue.__dict__ if hasattr(issue, "__dict__") else str(issue) for issue in issues]

    @staticmethod
    def _has_hard_issues(issues: list[Any]) -> bool:
        """Check whether a list of validator issues contains hard failures."""
        for issue in issues:
            if isinstance(issue, dict) and issue.get("severity") == "hard":
                return True
            if getattr(issue, "severity", None) == "hard":
                return True
        return False

    @staticmethod
    def _issue_messages(issues: list[Any]) -> list[str]:
        """Extract human-readable messages from validator issues."""
        messages: list[str] = []
        for issue in issues:
            if isinstance(issue, dict):
                message = issue.get("message")
            else:
                message = getattr(issue, "message", None)
            if message:
                messages.append(str(message))
        return messages

    def _record_section_context(self, context: dict[str, Any], policy: SectionContextPolicy) -> dict[str, Any]:
        """Store the schema-filtered context that a section is allowed to consume/report."""
        return self.section_context_recorder.record(context, policy)

    def _section_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        return self.section_context_recorder._section_payload(context)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        return SectionContextRecorder.json_safe(value)

    def _default_context_service(self) -> ContextNodeService | None:
        if hasattr(self.phases, "phase_0_context"):
            return ContextNodeService(self.phases.phase_0_context)
        return None

    def _default_title_annotation_service(self) -> TitleAnnotationNodeService | None:
        if hasattr(self.phases, "phase_1_title_annotation"):
            return TitleAnnotationNodeService(self.phases.phase_1_title_annotation)
        return None

    def _default_task_planning_service(self) -> TaskPlanningNodeService:
        return TaskPlanningNodeService(self.task_planner, legacy_state=self.phases)

    def _default_skeleton_service(self) -> SkeletonNodeService | None:
        if not (hasattr(self.phases, "phase_1_skeleton") and hasattr(self.phases, "phase_1_structure")):
            return None
        return SkeletonNodeService(
            self.phases.phase_1_skeleton,
            self.phases.phase_1_structure,
            self._serialize_issues,
            self._has_hard_issues,
            self._issue_messages,
            self._json_safe,
        )

    def _default_theory_service(self) -> TheoryNodeService | None:
        if hasattr(self.phases, "phase_2_theory"):
            return TheoryNodeService(
                self.phases.phase_2_theory,
                self.section_context_recorder,
                self._serialize_issues,
                self._has_hard_issues,
                self._issue_messages,
            )
        return None

    def _default_practice_service(self) -> PracticeNodeService | None:
        if hasattr(self.phases, "phase_3_practice"):
            return PracticeNodeService(
                self.phases.phase_3_practice,
                self.section_context_recorder,
                self._serialize_issues,
                self._has_hard_issues,
                self._issue_messages,
                legacy_state=self.phases,
            )
        return None

    def _default_quality_service(self) -> QualityNodeService | None:
        if hasattr(self.phases, "phase_4_global_quality"):
            return QualityNodeService(self.phases.phase_4_global_quality)
        return None

    def _default_evaluation_service(self) -> EvaluationNodeService | None:
        if hasattr(self.phases, "phase_6_final_evaluation"):
            return EvaluationNodeService(self.phases.phase_6_final_evaluation, self._serialize_issues)
        return None

    def _default_translation_service(self) -> TranslationNodeService | None:
        if hasattr(self.phases, "phase_7_translate"):
            return TranslationNodeService(self.phases.phase_7_translate)
        return None

    def _default_finalize_service(self) -> FinalizeNodeService:
        return FinalizeNodeService(
            self.result_assembler,
            self.section_context_recorder,
            legacy_state=self.phases,
        )

    @staticmethod
    def _require_service(service: Any | None, node_id: str) -> Any:
        if service is None:
            raise RuntimeError(f"Node service is not configured for '{node_id}'")
        return service
