from api.db.paused_generation_codec import hydrate_context, hydrate_steps, serialize_context, serialize_steps
from content_gen.agents.flow import FlowExecutionStep
from content_gen.agents.task_planner import TaskPlan
from content_gen.models.flow_state import ProjectFlowState
from content_gen.models.schemas import ProjectSeed


def test_paused_generation_codec_roundtrips_typed_context() -> None:
    seed = ProjectSeed(
        language="ru",
        project_type="individual",
        thematic_block="PjM",
        audience_level="base",
        required_tools=[],
        title_seed="Test",
        project_description="Desc",
        learning_outcomes=["LO1"],
        skills=["Skill1"],
    )
    task_plan = TaskPlan(
        tasks_count=3,
        complexity="medium",
        level_index=1,
        level_source="test",
        rationale="rationale",
        explanation="explanation",
        curriculum_context={},
    )
    state = ProjectFlowState.from_initial_input({"language": "ru"})
    context = {
        "state": state,
        "seed": seed,
        "task_plan": task_plan,
        "dataset_files": [{"path": "materials/raw.md", "data": b"raw bytes"}],
    }

    hydrated = hydrate_context(serialize_context(context))

    assert isinstance(hydrated["seed"], ProjectSeed)
    assert isinstance(hydrated["task_plan"], TaskPlan)
    assert hydrated["task_plan"].tasks_count == 3
    assert hydrated["dataset_files"][0]["data"] == b"raw bytes"
    assert isinstance(hydrated["state"], ProjectFlowState)
    assert hydrated["state"].seed == hydrated["seed"]


def test_paused_generation_codec_roundtrips_steps() -> None:
    steps = [
        FlowExecutionStep(
            node_id="context",
            node_name="Context",
            status="paused",
            duration_ms=12.3,
            issues=["needs review"],
        )
    ]

    hydrated = hydrate_steps(serialize_steps(steps))

    assert hydrated[0].node_id == "context"
    assert hydrated[0].status == "paused"
    assert hydrated[0].issues == ["needs review"]


def test_paused_generation_codec_records_unknown_type_compatibility_event() -> None:
    hydrated = hydrate_context(
        {
            "legacy": {
                "__paused_type__": "old.module:Thing",
                "data": {"value": 42},
            }
        }
    )

    assert hydrated["legacy"] == {"value": 42}
    assert hydrated["compatibility_events"][0]["compatibility_type"] == "unknown_paused_type"
    assert hydrated["compatibility_events"][0]["metadata"] == {"type_name": "old.module:Thing"}


def test_paused_generation_codec_records_model_validation_compatibility_event() -> None:
    hydrated = hydrate_context(
        {
            "seed": {
                "__paused_type__": "content_gen.models.schemas:ProjectSeed",
                "data": {"language": "ru"},
            }
        }
    )

    assert hydrated["seed"] == {"language": "ru"}
    assert hydrated["compatibility_events"][0]["compatibility_type"] == "pydantic_model_validation_failed"
    assert hydrated["compatibility_events"][0]["metadata"] == {
        "type_name": "content_gen.models.schemas:ProjectSeed"
    }
