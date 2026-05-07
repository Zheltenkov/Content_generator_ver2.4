from content_gen.agents.context_analysis import ContextAnalysisResult
from content_gen.models.schemas import (
    Annotation,
    IntroSection,
    PracticeTask,
    ProjectContextMeta,
    ProjectSeed,
    TheoryPart,
)
from content_gen.result_assembly import ResultAssembler


class DummyLLM:
    def complete(self, **kwargs):
        return "Public Speaking"


class UnexpectedTitleAgent:
    def generate(self, *_args, **_kwargs):
        raise AssertionError("title fallback should not run when structured title exists")


def _seed() -> ProjectSeed:
    return ProjectSeed(
        language="ru",
        project_type="individual",
        thematic_block="PjM",
        audience_level="base",
        required_tools=[],
        title_seed="Test",
        project_description="Desc",
        learning_outcomes=["LO1"],
        skills=["Skill1"],
        curriculum_context={"block": "PjM"},
    )


def _context_meta() -> ProjectContextMeta:
    return ProjectContextMeta(track="PjM", thematic_block="PjM", last_order=1, context_summary="Summary")


def _context_analysis() -> ContextAnalysisResult:
    return ContextAnalysisResult(
        is_first_project=False,
        context_summary="ctx",
        narrative_anchor="anchor",
        similar_projects=[],
        skills_alignment={"intersection": ["Skill1"], "new": []},
        learning_outcomes_alignment={"continuation": [], "new": ["LO1"]},
        tools_alignment={"used": [], "new": []},
        audience_level_match=True,
        metrics={"hits": 1},
    )


def test_result_assembler_builds_spec_report_and_assets() -> None:
    assembler = ResultAssembler(
        llm_client=DummyLLM(),
        title_annotation_agent=UnexpectedTitleAgent(),
        intro_splitter=lambda _markdown: ("intro", "instruction"),
        theory_parts_parser=lambda _markdown: [],
        practice_tasks_parser=lambda _markdown: [],
    )
    context = {
        "seed": _seed(),
        "context_meta": _context_meta(),
        "context_analysis": _context_analysis(),
        "rubric_json": {"score": 5},
        "warnings": [],
        "issues": [],
        "markdown": "# Публичные выступления\n\nBody",
        "target_language": "ru",
        "title": "Публичные выступления",
        "annotation": Annotation(text="Annotation", chars=10),
        "intro_section": IntroSection(intro_text="Intro", instruction_text="Instruction"),
        "theory_parts": [TheoryPart(title="Theory", body="Body", example="", bridge_questions=[])],
        "practice_tasks": [
            PracticeTask(
                title="Task",
                input_data="Repo",
                goal="Build artifact",
                approach_bullets=["Step"],
                expected_artifact="README",
                artifact_location="project/task/README.md",
            )
        ],
    }

    finalized = assembler.assemble(context, dataset_files=[{"path": "data/sample.csv", "data": b"a,b\n"}])

    assert finalized.project_spec.title == "Публичные выступления"
    assert finalized.result.report_json["title_en"] == "PublicSpeaking"
    assert finalized.result.report_json["text_stats"]["chars"] == len(finalized.markdown)
    assert finalized.result.report_json["assets"]["files"]
    assert finalized.assets_binary["files"][0]["path"] == "project/task/README.md"
    artifact_template = finalized.assets_binary["files"][0]["data"].decode("utf-8")
    assert "Этот файл — рабочий шаблон артефакта, а не готовое решение." in artifact_template
    assert "## Входные данные" in artifact_template
    assert "## Итоговый артефакт" in artifact_template
