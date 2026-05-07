from types import SimpleNamespace

from content_gen.agents.flow import FlowNodeOutput
from content_gen.domain_contracts import SectionContextPolicy
from content_gen.flow_handlers import GenerationFlowHandlers
from content_gen.models.generation_context import ContextNodeResult, GenerationContext
from content_gen.node_services import (
    ContextNodeService,
    EvaluationNodeService,
    FinalizeNodeService,
    PracticeNodeService,
    QualityNodeService,
    SectionContextRecorder,
    TaskPlanningNodeService,
    TitleAnnotationNodeService,
    TranslationNodeService,
)


def test_generation_context_from_legacy_excludes_state() -> None:
    state = object()
    context = GenerationContext.from_legacy(
        {
            "raw_input": {"language": "RU"},
            "track_files": ["track.xlsx"],
            "warnings": ["w"],
            "state": state,
        }
    )

    assert context.raw_input == {"language": "RU"}
    assert context.track_files == ["track.xlsx"]
    assert context.warnings == ["w"]
    assert not hasattr(context, "state")


def test_context_node_service_returns_typed_updates() -> None:
    seed = SimpleNamespace(bonus_wish=None)
    context_meta = SimpleNamespace(search_metrics={"previous_projects_count": 2, "reference_enabled": True})
    context_analysis = SimpleNamespace()
    context_bundle = SimpleNamespace()

    def build_context(raw_input, track_files):
        assert raw_input == {"language": "RU"}
        assert track_files == ["track.xlsx"]
        return seed, context_meta, context_analysis, context_bundle, ["prev"], ["warn"]

    result = ContextNodeService(build_context).execute(
        GenerationContext(raw_input={"language": "RU"}, track_files=["track.xlsx"])
    )

    assert result.target_language == "ru"
    assert result.generate_bonus is False
    assert result.warnings == ["warn"]
    assert result.issues == ["warn"]
    assert result.updates()["seed"] is seed


def test_task_planning_service_syncs_legacy_contract_state() -> None:
    seed = SimpleNamespace(tasks_count=None, task_complexity=None)
    context_meta = SimpleNamespace()
    context_analysis = SimpleNamespace()
    story_map = SimpleNamespace()
    practice_plan = SimpleNamespace()
    artifact_chain = SimpleNamespace(evidence_specs=["e1"])
    legacy_state = SimpleNamespace()

    class Planner:
        def plan(self, _seed, _context_meta, _context_analysis):
            return SimpleNamespace(tasks_count=3, complexity="medium")

    class BlueprintPlanner:
        def build(self, _seed, task_plan, _context_meta, _context_bundle):
            assert task_plan.tasks_count == 3
            return story_map, practice_plan, artifact_chain

    service = TaskPlanningNodeService(Planner(), BlueprintPlanner(), legacy_state=legacy_state)
    result = service.execute(
        GenerationContext(seed=seed, context_meta=context_meta, context_analysis=context_analysis)
    )

    assert seed.tasks_count == 3
    assert seed.task_complexity == "medium"
    assert result.story_map_contract is story_map
    assert result.practice_plan_contract is practice_plan
    assert result.artifact_chain_plan is artifact_chain
    assert result.evidence_specs == ["e1"]
    assert legacy_state.story_map_contract is story_map
    assert legacy_state.practice_plan_contract is practice_plan
    assert legacy_state.artifact_chain_plan is artifact_chain


def test_title_annotation_service_returns_typed_updates() -> None:
    seed = SimpleNamespace()
    context_meta = SimpleNamespace()
    annotation = SimpleNamespace(summary="short")

    def build_title_annotation(_seed, _context_meta):
        return "Название", annotation

    result = TitleAnnotationNodeService(build_title_annotation).execute(
        GenerationContext(seed=seed, context_meta=context_meta)
    )

    assert result.title == "Название"
    assert result.annotation is annotation
    assert result.updates() == {"title": "Название", "annotation": annotation}


def test_quality_service_wraps_markdown_update() -> None:
    seed = SimpleNamespace()

    def improve_quality(_seed, markdown):
        return markdown + "\nquality"

    result = QualityNodeService(improve_quality).execute(GenerationContext(seed=seed, markdown="# README"))

    assert result.markdown == "# README\nquality"
    assert result.updates() == {"markdown": "# README\nquality"}


def test_evaluation_service_serializes_issues() -> None:
    seed = SimpleNamespace()

    class Issue:
        def __init__(self) -> None:
            self.severity = "soft"
            self.message = "warning"

    def evaluate(_seed, markdown):
        assert markdown == "# README"
        return {"passed": True}, [Issue()]

    result = EvaluationNodeService(evaluate, lambda issues: [issue.__dict__ for issue in issues]).execute(
        GenerationContext(seed=seed, markdown="# README")
    )

    assert result.rubric_json == {"passed": True}
    assert result.serialized_issues == [{"severity": "soft", "message": "warning"}]
    assert result.updates() == {"rubric_json": {"passed": True}}


def test_translation_service_normalizes_target_language() -> None:
    seed = SimpleNamespace(language="EN")

    def translate(_seed, markdown, target_language):
        assert markdown == "# README"
        assert target_language == "en"
        return markdown, "# TRANSLATED"

    result = TranslationNodeService(translate).execute(
        GenerationContext(seed=seed, markdown="# README", target_language=" EN ")
    )

    assert result.target_language == "en"
    assert result.updates()["translated_markdown"] == "# TRANSLATED"


def test_practice_service_preserves_legacy_context_side_effects() -> None:
    seed = SimpleNamespace(
        title_seed="Проект",
        project_description="Описание",
        learning_outcomes=["LO1"],
        skills=["Skill"],
        required_tools=[],
        curriculum_context={},
    )
    blueprint = SimpleNamespace()
    practice_plan = SimpleNamespace()
    artifact_chain = SimpleNamespace(evidence_specs=["e1"])
    legacy_state = SimpleNamespace(
        story_map_contract=SimpleNamespace(),
        practice_plan_contract=practice_plan,
        artifact_chain_plan=artifact_chain,
        evidence_specs=["e1"],
        dataset_files=[{"path": "data.csv"}],
        practice_critic_issues=[{"message": "critic"}],
    )
    task = SimpleNamespace(covered_outcomes=["LO1"], theory_support=["2.1"])

    class Issue:
        def __init__(self) -> None:
            self.severity = "soft"
            self.message = "practice note"

    def generate_practice(_seed, markdown, _generate_bonus, practice_plan_contract, artifact_chain_plan, section_context):
        assert markdown == "# README"
        assert practice_plan_contract is practice_plan
        assert artifact_chain_plan is artifact_chain
        assert "project_description" in section_context
        return "# README\npractice", [task], [Issue()], ["warn"]

    service = PracticeNodeService(
        generate_practice,
        SectionContextRecorder(),
        lambda issues: [issue.__dict__ for issue in issues],
        lambda _issues: False,
        lambda issues: [issue.message for issue in issues],
        legacy_state=legacy_state,
    )
    legacy_context = {"seed": seed, "markdown": "# README", "issues": [], "warnings": []}
    result = service.execute(
        GenerationContext(seed=seed, markdown="# README", blueprint=blueprint),
        legacy_context,
    )

    assert result.markdown == "# README\npractice"
    assert result.practice_tasks == [task]
    assert result.dataset_files == [{"path": "data.csv"}]
    assert result.practice_critic_issues == [{"message": "critic"}]
    assert blueprint.lo_task_map == {"LO1": [1]}
    assert blueprint.theory_task_map == {"2.1": [1]}
    assert legacy_context["issues"] == [{"severity": "soft", "message": "practice note"}]
    assert legacy_context["warnings"] == ["warn"]
    assert "practice" in result.section_contexts
    assert "dataset" in result.section_contexts


def test_finalize_service_prefers_resumed_context_dataset_files() -> None:
    captured = {}

    class Finalized:
        result = object()
        project_spec = object()
        markdown = "# final"
        translated_markdown = None
        assets_binary = {}
        step_warnings = ["final warn"]

    class ResultAssembler:
        def assemble(self, context, dataset_files):
            captured["context"] = context
            captured["dataset_files"] = dataset_files
            return Finalized()

    legacy_state = SimpleNamespace(dataset_files=[{"path": "stale.csv"}])
    dataset_files = [{"path": "resumed.csv"}]
    context = {
        "seed": SimpleNamespace(
            title_seed="Проект",
            project_description="Описание",
            learning_outcomes=[],
            skills=[],
            required_tools=[],
            curriculum_context={},
        ),
        "dataset_files": dataset_files,
        "section_contexts": {},
    }

    result = FinalizeNodeService(ResultAssembler(), SectionContextRecorder(), legacy_state=legacy_state).execute(context)

    assert captured["dataset_files"] == dataset_files
    assert result.markdown == "# final"
    assert result.issues == ["final warn"]
    assert "finalize" in result.section_contexts
    assert context["markdown"] == "# final"


def test_flow_handler_uses_injected_context_service() -> None:
    seed = SimpleNamespace(bonus_wish=None)
    context_meta = SimpleNamespace()
    context_analysis = SimpleNamespace()
    context_bundle = SimpleNamespace()

    class Service:
        def execute(self, context):
            assert isinstance(context, GenerationContext)
            return ContextNodeResult(
                seed=seed,
                target_language="ru",
                generate_bonus=False,
                context_meta=context_meta,
                context_analysis=context_analysis,
                context_bundle=context_bundle,
                similar_projects=[],
                warnings=["typed warning"],
                issues=["typed warning"],
            )

    handlers = GenerationFlowHandlers(
        phases=object(),
        task_planner=object(),
        result_assembler=object(),
        log_phase=lambda _phase, _message: None,
        context_service=Service(),
    )
    context = {"raw_input": {"language": "ru"}, "track_files": [], "warnings": []}

    output = handlers.node_context(context)

    assert isinstance(output, FlowNodeOutput)
    assert output.updates["seed"] is seed
    assert output.issues == ["typed warning"]
    assert context["warnings"] == ["typed warning"]


def test_section_context_recorder_filters_theory_context() -> None:
    recorder = SectionContextRecorder()
    context = {
        "seed": SimpleNamespace(
            title_seed="Проект",
            project_description="Описание",
            learning_outcomes=["LO"],
            skills=["Skill"],
            required_tools=[],
            curriculum_context={"narrative_contract": {"case": "x"}},
        ),
        "context_analysis": SimpleNamespace(context_summary="summary", narrative_anchor="anchor"),
        "markdown": "# README",
        "instruction_text": "Нельзя попадать в theory context",
    }

    filtered = recorder.record(context, policy=SectionContextPolicy.for_theory())

    assert context["section_contexts"]["theory"] == filtered
    assert "project_description" in filtered
    assert "instruction_text" not in filtered
