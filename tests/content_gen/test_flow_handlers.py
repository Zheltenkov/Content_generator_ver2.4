from content_gen.flow_handlers import GenerationFlowHandlers


class _Finalized:
    result = object()
    project_spec = object()
    markdown = "# md"
    translated_markdown = None
    assets_binary = {}
    step_warnings = []


def test_generation_flow_handlers_registry_exposes_expected_nodes() -> None:
    handlers = GenerationFlowHandlers(
        phases=object(),
        task_planner=object(),
        result_assembler=object(),
        log_phase=lambda _phase, _message: None,
    )

    assert set(handlers.registry()) == {
        "context",
        "task_planning",
        "title_annotation",
        "skeleton",
        "theory",
        "practice",
        "global_quality",
        "evaluation",
        "translate",
        "finalize",
    }


def test_generation_flow_handlers_issue_helpers() -> None:
    class Issue:
        def __init__(self) -> None:
            self.severity = "hard"
            self.message = "Hard issue"

    assert GenerationFlowHandlers._has_hard_issues([Issue()]) is True
    assert GenerationFlowHandlers._issue_messages([Issue()]) == ["Hard issue"]
    assert GenerationFlowHandlers._serialize_issues([Issue()]) == [{"severity": "hard", "message": "Hard issue"}]


def test_finalize_uses_dataset_files_from_resumed_context() -> None:
    captured = {}

    class ResultAssembler:
        def assemble(self, context, dataset_files):
            captured["dataset_files"] = dataset_files
            return _Finalized()

    handlers = GenerationFlowHandlers(
        phases=object(),
        task_planner=object(),
        result_assembler=ResultAssembler(),
        log_phase=lambda _phase, _message: None,
    )
    dataset_files = [{"path": "materials/raw.md", "data": b"raw"}]
    context = {
        "dataset_files": dataset_files,
        "section_contexts": {},
        "seed": None,
    }

    handlers.node_finalize(context)

    assert captured["dataset_files"] == dataset_files
