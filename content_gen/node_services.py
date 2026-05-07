"""Typed node services for the content generation flow."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .agents.task_planner import TaskPlan, TaskPlanner
from .config.thresholds import THRESHOLDS
from .domain_contracts import SectionContextPolicy
from .models.generation_context import (
    ContextNodeResult,
    EvaluationNodeResult,
    FinalizeNodeResult,
    GenerationContext,
    PracticeNodeResult,
    QualityNodeResult,
    SkeletonNodeResult,
    TaskPlanningNodeResult,
    TheoryNodeResult,
    TitleAnnotationNodeResult,
    TranslationNodeResult,
)
from .project_planning import ProjectBlueprintPlanner

logger = logging.getLogger("content_gen.node_services")

IssueSerializer = Callable[[list[Any]], list[Any]]
IssuePredicate = Callable[[list[Any]], bool]
IssueMessages = Callable[[list[Any]], list[str]]
JsonSafe = Callable[[Any], Any]


class SectionContextRecorder:
    """Build and store schema-filtered context for section-scoped nodes."""

    def record(self, context: dict[str, Any], policy: SectionContextPolicy) -> dict[str, Any]:
        """Store the schema-filtered context that a section is allowed to consume/report."""
        seed = context.get("seed")
        payload = self._section_payload(context)
        topic_text = " ".join(
            [
                str(getattr(seed, "title_seed", "") or ""),
                str(getattr(seed, "project_description", "") or ""),
                " ".join(getattr(seed, "learning_outcomes", []) or []) if seed else "",
                " ".join(getattr(seed, "skills", []) or []) if seed else "",
            ]
        )
        filtered = policy.filter_context_payload(payload, topic_text=topic_text)
        context.setdefault("section_contexts", {})[policy.section] = filtered
        return filtered

    def _section_payload(self, context: dict[str, Any]) -> dict[str, Any]:
        seed = context.get("seed")
        context_bundle = context.get("context_bundle")
        curriculum_context = getattr(seed, "curriculum_context", None) if seed is not None else None
        narrative_contract = None
        if context_bundle is not None:
            narrative_contract = getattr(context_bundle, "narrative_contract", None)
        if not narrative_contract and isinstance(curriculum_context, dict):
            narrative_contract = curriculum_context.get("narrative_contract")

        return {
            "curriculum_context": self.json_safe(curriculum_context),
            "narrative_contract": self.json_safe(narrative_contract),
            "sjm_context": self.json_safe(getattr(seed, "sjm", "") if seed else ""),
            "learning_outcomes": self.json_safe(getattr(seed, "learning_outcomes", []) if seed else []),
            "skills": self.json_safe(getattr(seed, "skills", []) if seed else []),
            "required_tools": self.json_safe(getattr(seed, "required_tools", []) if seed else []),
            "project_description": self.json_safe(getattr(seed, "project_description", "") if seed else ""),
            "context_summary": self.json_safe(getattr(context.get("context_analysis"), "context_summary", "")),
            "narrative_anchor": self.json_safe(getattr(context.get("context_analysis"), "narrative_anchor", "")),
            "instruction_text": self.json_safe(getattr(context.get("intro_section"), "instruction_text", "")),
            "theory_summary": self.json_safe(context.get("theory_summary", "")),
            "story_map_contract": self.json_safe(context.get("story_map_contract")),
            "practice_plan_contract": self.json_safe(context.get("practice_plan_contract")),
            "artifact_chain_plan": self.json_safe(context.get("artifact_chain_plan")),
            "evidence_specs": self.json_safe(context.get("evidence_specs", [])),
            "dataset_files": self.json_safe(context.get("dataset_files", [])),
            "practice_tasks": self.json_safe(context.get("practice_tasks", [])),
            "theory_parts": self.json_safe(context.get("theory_parts", [])),
            "rubric_json": self.json_safe(context.get("rubric_json", {})),
            "warnings": self.json_safe(context.get("warnings", [])),
            "issues": self.json_safe(context.get("issues", [])),
            "markdown": self.json_safe(context.get("markdown", "")),
        }

    @classmethod
    def json_safe(cls, value: Any) -> Any:
        """Convert flow artifacts into JSON-compatible values for section context."""
        if value is None:
            return None
        if isinstance(value, bytes):
            return f"<bytes:{len(value)}>"
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [cls.json_safe(item) for item in value]
        if isinstance(value, tuple):
            return [cls.json_safe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): cls.json_safe(item) for key, item in value.items()}
        if hasattr(value, "model_dump"):
            return cls.json_safe(value.model_dump())
        if hasattr(value, "as_dict"):
            return cls.json_safe(value.as_dict())
        if hasattr(value, "__dict__"):
            return cls.json_safe(value.__dict__)
        return str(value)


class ContextNodeService:
    """Build the initial curriculum-aware generation context."""

    def __init__(self, build_context: Callable[[dict[str, Any], list[str]], tuple[Any, ...]]) -> None:
        self.build_context = build_context

    def execute(self, context: GenerationContext) -> ContextNodeResult:
        raw_input = context.raw_input
        target_language = raw_input.get("language", "ru")
        target_language = str(target_language) if not isinstance(target_language, str) else target_language
        target_language = target_language.lower().strip() if isinstance(target_language, str) else target_language

        logger.info("Context is assembled from curriculum input without retrieval search")
        logger.info(
            "Context language from raw_input: '%s' -> target_language='%s'",
            raw_input.get("language"),
            target_language,
        )

        seed, context_meta, context_analysis, context_bundle, similar_projects, warnings = self.build_context(
            raw_input,
            context.track_files,
        )
        warnings = list(warnings or [])

        logger.info(
            "Context target_language='%s', previous_projects=%s, reference=%s",
            target_language,
            context_meta.search_metrics.get("previous_projects_count", 0),
            context_meta.search_metrics.get("reference_enabled", False),
        )

        return ContextNodeResult(
            seed=seed,
            target_language=target_language,
            generate_bonus=seed.bonus_wish is not None,
            context_meta=context_meta,
            context_analysis=context_analysis,
            context_bundle=context_bundle,
            similar_projects=list(similar_projects or []),
            warnings=warnings,
            issues=warnings,
        )


class TitleAnnotationNodeService:
    """Generate title and annotation as an isolated node service."""

    def __init__(self, build_title_annotation: Callable[[Any, Any], tuple[str, Any]]) -> None:
        self.build_title_annotation = build_title_annotation

    def execute(self, context: GenerationContext) -> TitleAnnotationNodeResult:
        seed = context.require("seed")
        context_meta = context.require("context_meta")
        title, annotation = self.build_title_annotation(seed, context_meta)
        return TitleAnnotationNodeResult(title=title, annotation=annotation)


class TaskPlanningNodeService:
    """Plan practice scope and deterministic generation contracts."""

    def __init__(
        self,
        task_planner: TaskPlanner,
        project_blueprint_planner: ProjectBlueprintPlanner | None = None,
        legacy_state: Any | None = None,
    ) -> None:
        self.task_planner = task_planner
        self.project_blueprint_planner = project_blueprint_planner or ProjectBlueprintPlanner()
        self.legacy_state = legacy_state

    def execute(self, context: GenerationContext) -> TaskPlanningNodeResult:
        seed = context.require("seed")
        context_meta = context.require("context_meta")
        context_analysis = context.require("context_analysis")
        warnings: list[str] = []
        task_plan: TaskPlan | None = None

        try:
            task_plan = self.task_planner.plan(seed, context_meta, context_analysis)
            seed.tasks_count = task_plan.tasks_count
            seed.task_complexity = task_plan.complexity
            warnings.append(f"ℹ️ План практики готов: {task_plan.tasks_count} задач ({task_plan.complexity}).")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Practice plan fallback used: %s", exc)
            if not seed.tasks_count:
                seed.tasks_count = THRESHOLDS["practice_tasks_recommend"][0]
                seed.task_complexity = "medium"
            warnings.append("⚠️ Использован дефолтный план практики")

        story_map_contract = None
        practice_plan_contract = None
        artifact_chain_plan = None
        evidence_specs: list[Any] = []
        try:
            story_map_contract, practice_plan_contract, artifact_chain_plan = self.project_blueprint_planner.build(
                seed,
                task_plan,
                context_meta,
                context.context_bundle,
            )
            evidence_specs = list(getattr(artifact_chain_plan, "evidence_specs", []) or [])
            self._sync_legacy_contract_state(
                story_map_contract,
                practice_plan_contract,
                artifact_chain_plan,
                evidence_specs,
            )
            warnings.append("ℹ️ Контракт учебной деятельности готов до генерации теории.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("PracticePlanContract fallback skipped: %s", exc)
            warnings.append(f"⚠️ Не удалось построить PracticePlanContract: {exc}")

        return TaskPlanningNodeResult(
            seed=seed,
            task_plan=task_plan,
            story_map_contract=story_map_contract,
            practice_plan_contract=practice_plan_contract,
            artifact_chain_plan=artifact_chain_plan,
            evidence_specs=evidence_specs,
            warnings=warnings,
            issues=warnings,
        )

    def _sync_legacy_contract_state(
        self,
        story_map_contract: Any,
        practice_plan_contract: Any,
        artifact_chain_plan: Any,
        evidence_specs: list[Any],
    ) -> None:
        if self.legacy_state is None:
            return
        self.legacy_state.story_map_contract = story_map_contract
        self.legacy_state.practice_plan_contract = practice_plan_contract
        self.legacy_state.artifact_chain_plan = artifact_chain_plan
        self.legacy_state.evidence_specs = evidence_specs


class QualityNodeService:
    """Run the global quality pass over the generated README."""

    def __init__(self, improve_quality: Callable[[Any, str], str]) -> None:
        self.improve_quality = improve_quality

    def execute(self, context: GenerationContext) -> QualityNodeResult:
        seed = context.require("seed")
        markdown = context.require("markdown")
        return QualityNodeResult(markdown=self.improve_quality(seed, markdown))


class EvaluationNodeService:
    """Run final rubric evaluation and expose serialized issues."""

    def __init__(
        self,
        evaluate: Callable[[Any, str], tuple[dict[str, Any], list[Any]]],
        serialize_issues: IssueSerializer,
    ) -> None:
        self.evaluate = evaluate
        self.serialize_issues = serialize_issues

    def execute(self, context: GenerationContext) -> EvaluationNodeResult:
        seed = context.require("seed")
        markdown = context.require("markdown")
        rubric_json, final_issues = self.evaluate(seed, markdown)
        return EvaluationNodeResult(
            rubric_json=rubric_json,
            serialized_issues=self.serialize_issues(final_issues),
        )


class TranslationNodeService:
    """Translate the final README when the target language requires it."""

    def __init__(self, translate: Callable[[Any, str, str], tuple[str, str]]) -> None:
        self.translate = translate

    def execute(self, context: GenerationContext, target_language: str | None = None) -> TranslationNodeResult:
        seed = context.require("seed")
        markdown = context.require("markdown")
        resolved_language = self._normalize_target_language(target_language or context.target_language, seed)
        original_md, translated_md = self.translate(seed, markdown, resolved_language)
        return TranslationNodeResult(
            markdown=original_md,
            translated_markdown=translated_md,
            seed=seed,
            target_language=resolved_language,
        )

    @staticmethod
    def _normalize_target_language(target_language: Any, seed: Any) -> str:
        if target_language is None:
            logger.error(
                "target_language is absent in context; seed.language=%r. Using 'ru' fallback.",
                getattr(seed, "language", None),
            )
            return "ru"
        if not isinstance(target_language, str):
            target_language = str(target_language)
        return target_language.lower().strip()


class PracticeNodeService:
    """Generate practice tasks while preserving legacy flow context side effects."""

    def __init__(
        self,
        generate_practice: Callable[..., tuple[str, list[Any], list[Any], list[str]]],
        section_context_recorder: SectionContextRecorder,
        serialize_issues: IssueSerializer,
        has_hard_issues: IssuePredicate,
        issue_messages: IssueMessages,
        legacy_state: Any | None = None,
    ) -> None:
        self.generate_practice = generate_practice
        self.section_context_recorder = section_context_recorder
        self.serialize_issues = serialize_issues
        self.has_hard_issues = has_hard_issues
        self.issue_messages = issue_messages
        self.legacy_state = legacy_state

    def execute(self, context: GenerationContext, legacy_context: dict[str, Any]) -> PracticeNodeResult:
        seed = context.require("seed")
        markdown = context.require("markdown")
        self._hydrate_contracts(legacy_context)
        filtered_context = self.section_context_recorder.record(legacy_context, SectionContextPolicy.for_practice())
        md, practice_tasks, practice_issues, practice_warnings = self.generate_practice(
            seed,
            markdown,
            context.generate_bonus,
            practice_plan_contract=legacy_context.get("practice_plan_contract"),
            artifact_chain_plan=legacy_context.get("artifact_chain_plan"),
            section_context=filtered_context,
        )

        artifact_chain_plan = self._legacy_attr("artifact_chain_plan", context.artifact_chain_plan)
        evidence_specs = list(self._legacy_attr("evidence_specs", context.evidence_specs) or [])
        dataset_files = list(self._legacy_attr("dataset_files", []) or [])
        blueprint = self._update_blueprint_task_maps(context.blueprint, practice_tasks)
        serialized_issues = self.serialize_issues(practice_issues)
        status = "error" if self.has_hard_issues(practice_issues) else "success"

        legacy_context.update(
            {
                "artifact_chain_plan": artifact_chain_plan,
                "evidence_specs": evidence_specs,
                "dataset_files": dataset_files,
                "practice_tasks": practice_tasks,
            }
        )
        self.section_context_recorder.record(legacy_context, SectionContextPolicy.for_practice())
        self.section_context_recorder.record(legacy_context, SectionContextPolicy.for_dataset())
        legacy_context.setdefault("issues", []).extend(serialized_issues)
        legacy_context.setdefault("warnings", []).extend(practice_warnings)

        return PracticeNodeResult(
            markdown=md,
            practice_critic_issues=list(self._legacy_attr("practice_critic_issues", []) or []),
            practice_tasks=list(practice_tasks or []),
            blueprint=blueprint,
            artifact_chain_plan=artifact_chain_plan,
            evidence_specs=evidence_specs,
            dataset_files=dataset_files,
            section_contexts=legacy_context.get("section_contexts", {}),
            warnings=list(practice_warnings or []),
            serialized_issues=serialized_issues,
            issues=self.issue_messages(practice_issues) if status == "error" else list(practice_warnings or []),
            status=status,
        )

    def _hydrate_contracts(self, legacy_context: dict[str, Any]) -> None:
        legacy_context.setdefault("story_map_contract", self._legacy_attr("story_map_contract", None))
        legacy_context.setdefault("practice_plan_contract", self._legacy_attr("practice_plan_contract", None))
        legacy_context.setdefault("artifact_chain_plan", self._legacy_attr("artifact_chain_plan", None))
        legacy_context.setdefault("evidence_specs", list(self._legacy_attr("evidence_specs", []) or []))

    def _legacy_attr(self, name: str, default: Any) -> Any:
        if self.legacy_state is None:
            return default
        return getattr(self.legacy_state, name, default)

    @staticmethod
    def _update_blueprint_task_maps(blueprint: Any | None, practice_tasks: list[Any]) -> Any | None:
        if blueprint is None:
            return None
        lo_task_map: dict[str, list[int]] = {}
        theory_task_map: dict[str, list[int]] = {}
        for idx, task in enumerate(practice_tasks, 1):
            for outcome in getattr(task, "covered_outcomes", []) or []:
                lo_task_map.setdefault(outcome, []).append(idx)
            for topic in getattr(task, "theory_support", []) or []:
                theory_task_map.setdefault(topic, []).append(idx)
        blueprint.lo_task_map = lo_task_map
        blueprint.theory_task_map = theory_task_map
        return blueprint


class FinalizeNodeService:
    """Assemble the final orchestrator result through a typed node service."""

    def __init__(
        self,
        result_assembler: Any,
        section_context_recorder: SectionContextRecorder,
        legacy_state: Any | None = None,
    ) -> None:
        self.result_assembler = result_assembler
        self.section_context_recorder = section_context_recorder
        self.legacy_state = legacy_state

    def execute(self, legacy_context: dict[str, Any]) -> FinalizeNodeResult:
        dataset_files = list(legacy_context.get("dataset_files") or self._legacy_attr("dataset_files", []) or [])
        legacy_context["dataset_files"] = dataset_files
        self.section_context_recorder.record(legacy_context, SectionContextPolicy.for_finalize())
        finalized = self.result_assembler.assemble(
            legacy_context,
            dataset_files=dataset_files,
        )
        result = FinalizeNodeResult(
            result=finalized.result,
            project_spec=finalized.project_spec,
            markdown=finalized.markdown,
            translated_markdown=finalized.translated_markdown,
            assets_binary=finalized.assets_binary,
            section_contexts=legacy_context.get("section_contexts", {}),
            issues=list(finalized.step_warnings or []),
        )
        legacy_context.update(result.updates())
        return result

    def _legacy_attr(self, name: str, default: Any) -> Any:
        if self.legacy_state is None:
            return default
        return getattr(self.legacy_state, name, default)


class SkeletonNodeService:
    """Generate the README structure after title/annotation approval."""

    def __init__(
        self,
        build_skeleton: Callable[..., tuple[Any, ...]],
        build_structure: Callable[..., tuple[Any, ...]],
        serialize_issues: IssueSerializer,
        has_hard_issues: IssuePredicate,
        issue_messages: IssueMessages,
        json_safe: JsonSafe,
    ) -> None:
        self.build_skeleton = build_skeleton
        self.build_structure = build_structure
        self.serialize_issues = serialize_issues
        self.has_hard_issues = has_hard_issues
        self.issue_messages = issue_messages
        self.json_safe = json_safe

    def execute(self, context: GenerationContext) -> SkeletonNodeResult:
        seed = context.require("seed")
        context_meta = context.require("context_meta")
        title = context.title
        annotation = context.annotation

        if title and annotation:
            md, preflight_result, intro_section, blueprint = self.build_structure(
                seed,
                context_meta,
                context.generate_bonus,
                str(title),
                annotation,
            )
        else:
            md, preflight_result, title, annotation, intro_section, blueprint = self.build_skeleton(
                seed,
                context_meta,
                context.generate_bonus,
            )

        warnings: list[str] = []
        serialized_issues: list[Any] = []
        status = "success"
        if not preflight_result.passed:
            warn = f"⚠️ Structural Preflight: {len(preflight_result.hard_issues)} HARD проблем"
            warnings.append(warn)
            serialized_issues.extend(self.serialize_issues(preflight_result.hard_issues))
            status = "error"

        if blueprint is not None:
            if context.story_map_contract is not None:
                blueprint.story_map_contract = self.json_safe(context.story_map_contract)
            if context.practice_plan_contract is not None:
                blueprint.practice_plan_contract = self.json_safe(context.practice_plan_contract)

        flow_issues = self.issue_messages(preflight_result.hard_issues) if status == "error" else warnings
        return SkeletonNodeResult(
            markdown=md,
            title=str(title),
            annotation=annotation,
            intro_section=intro_section,
            blueprint=blueprint,
            warnings=warnings,
            serialized_issues=serialized_issues,
            issues=flow_issues,
            status=status,
        )


class TheoryNodeService:
    """Generate Chapter 2 theory with section-scoped context and typed output."""

    def __init__(
        self,
        generate_theory: Callable[..., tuple[str, list[Any], list[Any], list[str]]],
        section_context_recorder: SectionContextRecorder,
        serialize_issues: IssueSerializer,
        has_hard_issues: IssuePredicate,
        issue_messages: IssueMessages,
    ) -> None:
        self.generate_theory = generate_theory
        self.section_context_recorder = section_context_recorder
        self.serialize_issues = serialize_issues
        self.has_hard_issues = has_hard_issues
        self.issue_messages = issue_messages

    def execute(self, context: GenerationContext, legacy_context: dict[str, Any]) -> TheoryNodeResult:
        seed = context.require("seed")
        context_meta = context.require("context_meta")
        markdown = context.require("markdown")
        filtered_context = self.section_context_recorder.record(legacy_context, SectionContextPolicy.for_theory())
        md, theory_parts, theory_issues, theory_warnings = self.generate_theory(
            seed,
            context_meta,
            markdown,
            practice_plan_contract=context.practice_plan_contract,
            section_context=filtered_context,
        )

        serialized_issues = self.serialize_issues(theory_issues)
        status = "error" if self.has_hard_issues(theory_issues) else "success"
        hard_theory_issues = [
            issue
            for issue in theory_issues
            if (isinstance(issue, dict) and issue.get("severity") == "hard")
            or getattr(issue, "severity", None) == "hard"
        ]
        flow_issues = self.issue_messages(hard_theory_issues) if status == "error" else list(theory_warnings)

        return TheoryNodeResult(
            markdown=md,
            theory_parts=list(theory_parts or []),
            warnings=list(theory_warnings or []),
            serialized_issues=serialized_issues,
            issues=flow_issues,
            status=status,
        )
