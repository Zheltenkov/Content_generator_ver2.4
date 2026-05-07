from types import SimpleNamespace

from content_gen.generation_runtime import GenerationRuntimeContainer
import content_gen.phase_executors as phase_executors
from content_gen.orchestrator_phases_modules.phases.phase_4 import phase_4_global_quality
from content_gen.orchestrator_phases_modules.phases.phase_6 import phase_6_final_evaluation
from content_gen.orchestrator_phases_modules.phases.phase_7 import phase_7_translate
from content_gen.orchestrator_phases import OrchestratorPhases
from content_gen.practice_phase_executor import PracticePhaseExecutor
from content_gen.phase_executors import (
    ContextPhaseExecutor,
    EvaluationPhaseExecutor,
    PracticePhaseExecutor,
    QualityPhaseExecutor,
    StructurePhaseExecutor,
    TheoryPhaseExecutor,
    TranslationPhaseExecutor,
)


class FakeLLM:
    def complete(self, *args, **kwargs):
        return ""


def test_orchestrator_phases_delegates_runtime_state() -> None:
    phases = OrchestratorPhases(FakeLLM())

    phases.story_map_contract = {"completion": "done"}
    phases.dataset_files = [{"path": "materials/raw.csv"}]

    assert isinstance(phases.runtime, GenerationRuntimeContainer)
    assert isinstance(phases.context_executor, ContextPhaseExecutor)
    assert isinstance(phases.structure_executor, StructurePhaseExecutor)
    assert isinstance(phases.theory_executor, TheoryPhaseExecutor)
    assert isinstance(phases.practice_executor, PracticePhaseExecutor)
    assert isinstance(phases.quality_executor, QualityPhaseExecutor)
    assert isinstance(phases.evaluation_executor, EvaluationPhaseExecutor)
    assert isinstance(phases.translation_executor, TranslationPhaseExecutor)
    assert phases.runtime.story_map_contract == {"completion": "done"}
    assert phases.runtime.dataset_files == [{"path": "materials/raw.csv"}]
    assert phases.intro is phases.runtime.intro


def test_orchestrator_phases_delegates_context_to_executor(monkeypatch) -> None:
    phases = OrchestratorPhases(FakeLLM())
    captured = {}

    def fake_execute(raw_input, track_files):
        captured["raw_input"] = raw_input
        captured["track_files"] = track_files
        return None, None, None, None, [], []

    monkeypatch.setattr(phases.context_executor, "execute", fake_execute)

    phases.phase_0_context({"language": "ru"}, ["track.xlsx"])

    assert captured["raw_input"] == {"language": "ru"}
    assert captured["track_files"] == ["track.xlsx"]


def test_orchestrator_phases_delegates_structure_to_executor(monkeypatch) -> None:
    phases = OrchestratorPhases(FakeLLM())
    captured = {}

    def fake_generate_title_annotation(seed, context_meta):
        captured["seed"] = seed
        captured["context_meta"] = context_meta
        return "Название", {"text": "Аннотация"}

    monkeypatch.setattr(
        phases.structure_executor,
        "generate_title_annotation",
        fake_generate_title_annotation,
    )

    seed = object()
    context_meta = object()
    title, annotation = phases.phase_1_title_annotation(seed, context_meta)

    assert title == "Название"
    assert annotation == {"text": "Аннотация"}
    assert captured == {"seed": seed, "context_meta": context_meta}


def test_orchestrator_phases_delegates_theory_to_executor(monkeypatch) -> None:
    phases = OrchestratorPhases(FakeLLM())
    captured = {}

    def fake_execute(seed, context_meta, markdown, practice_plan_contract=None, section_context=None):
        captured.update(
            {
                "seed": seed,
                "context_meta": context_meta,
                "markdown": markdown,
                "practice_plan_contract": practice_plan_contract,
                "section_context": section_context,
            }
        )
        return "theory-md", [], [], []

    monkeypatch.setattr(phases.theory_executor, "execute", fake_execute)

    seed = object()
    context_meta = object()
    result = phases.phase_2_theory(
        seed,
        context_meta,
        "# md",
        practice_plan_contract={"plan": True},
        section_context={"allowed": True},
    )

    assert result == ("theory-md", [], [], [])
    assert captured == {
        "seed": seed,
        "context_meta": context_meta,
        "markdown": "# md",
        "practice_plan_contract": {"plan": True},
        "section_context": {"allowed": True},
    }


def test_orchestrator_phases_delegates_practice_to_executor(monkeypatch) -> None:
    phases = OrchestratorPhases(FakeLLM())
    captured = {}

    def fake_execute(seed, markdown, generate_bonus, practice_plan_contract=None, artifact_chain_plan=None, section_context=None):
        captured.update(
            {
                "seed": seed,
                "markdown": markdown,
                "generate_bonus": generate_bonus,
                "practice_plan_contract": practice_plan_contract,
                "artifact_chain_plan": artifact_chain_plan,
                "section_context": section_context,
            }
        )
        return "practice-md", [], [], []

    monkeypatch.setattr(phases.practice_executor, "execute", fake_execute)

    seed = object()
    result = phases.phase_3_practice(
        seed,
        "# md",
        True,
        practice_plan_contract={"plan": True},
        artifact_chain_plan={"chain": True},
        section_context={"allowed": True},
    )

    assert result == ("practice-md", [], [], [])
    assert captured == {
        "seed": seed,
        "markdown": "# md",
        "generate_bonus": True,
        "practice_plan_contract": {"plan": True},
        "artifact_chain_plan": {"chain": True},
        "section_context": {"allowed": True},
    }


def test_orchestrator_phases_delegates_terminal_phases_to_executors(monkeypatch) -> None:
    phases = OrchestratorPhases(FakeLLM())

    monkeypatch.setattr(phases.quality_executor, "execute", lambda seed, markdown: markdown + "\nquality")
    monkeypatch.setattr(phases.evaluation_executor, "execute", lambda seed, markdown: ({"ok": True}, ["issue"]))
    monkeypatch.setattr(
        phases.translation_executor,
        "execute",
        lambda seed, markdown, target_language: (markdown, f"{target_language}:{markdown}"),
    )

    seed = object()

    assert phases.phase_4_global_quality(seed, "# md") == "# md\nquality"
    assert phases.phase_6_final_evaluation(seed, "# md") == ({"ok": True}, ["issue"])
    assert phases.phase_7_translate(seed, "# md", "en") == ("# md", "en:# md")


def test_quality_phase_wrapper_executes_canonical_quality_logic() -> None:
    class ContentEditor:
        def ensure_global_coherence(self, markdown, _seed):
            return markdown

    class Toc:
        def build(self, _markdown, language):
            assert language == "ru"
            return SimpleNamespace(toc_md="- [Заключение](#заключение)")

        def inject(self, markdown, toc_md):
            return f"{markdown}\n{toc_md}"

    class Style:
        def lint(self, _markdown, _language):
            return []

    runtime = SimpleNamespace(
        content_editor=ContentEditor(),
        story_map_contract=SimpleNamespace(completion="Собери итоговый макет."),
        toc=Toc(),
        style=Style(),
    )
    seed = SimpleNamespace(language="ru", title_seed="Проект", project_description="")

    markdown = phase_4_global_quality(runtime, seed, "# Проект\n")

    assert "## Заключение" in markdown
    assert "Собери итоговый макет" in markdown
    assert "- [Заключение](#заключение)" in markdown


def test_translation_phase_wrapper_executes_canonical_translation_logic() -> None:
    class Translator:
        def translate(self, markdown, target_language, _seed):
            return f"{target_language}:{markdown}"

    runtime = SimpleNamespace(translator=Translator())
    seed = SimpleNamespace(language="ru")

    assert phase_7_translate(runtime, seed, "# md", "en") == ("# md", "en:# md")
    assert phase_7_translate(runtime, seed, "# md", "ru") == ("# md", "# md")


def test_evaluation_phase_wrapper_executes_canonical_evaluation_logic(monkeypatch) -> None:
    class Validator:
        def __init__(self, message):
            self.message = message

        def validate_markdown(self, *_args):
            return [SimpleNamespace(message=self.message, severity="soft")]

    class Rubric:
        def __init__(self, language, llm_client):
            self.language = language
            self.llm_client = llm_client

        def score(self, markdown, learning_outcomes):
            return {"markdown": markdown, "learning_outcomes": learning_outcomes}

    monkeypatch.setattr(phase_executors, "RubricScorer", Rubric)
    monkeypatch.setattr(phase_executors, "criteria_to_json", lambda report: {"report": report})

    runtime = SimpleNamespace(
        intro_validator=Validator("intro"),
        theory_validator=Validator("theory"),
        practice_validator=Validator("practice"),
        llm=FakeLLM(),
        rubric=None,
    )
    seed = SimpleNamespace(language="ru", tasks_count=1, learning_outcomes=["LO"])

    rubric_json, issues = phase_6_final_evaluation(runtime, seed, "# md")

    assert rubric_json == {"report": {"markdown": "# md", "learning_outcomes": ["LO"]}}
    assert [issue["message"] for issue in issues] == ["intro", "theory", "practice"]
    assert isinstance(runtime.rubric, Rubric)


def test_practice_executor_selects_serious_critic_issues_only() -> None:
    issues = [
        SimpleNamespace(kind="p2p_check", severity="critical"),
        SimpleNamespace(kind="style", severity="critical"),
        SimpleNamespace(kind="theory_alignment", severity="minor"),
        SimpleNamespace(kind="story_alignment", severity="hard"),
    ]

    selected = PracticePhaseExecutor._critic_issues_for_regeneration(issues)

    assert selected == [issues[0], issues[3]]


def test_practice_executor_extracts_instruction_and_theory_summary() -> None:
    class Intro:
        def _split_intro_instruction(self, markdown):
            assert markdown == "# README"
            return "intro", "instruction"

    runtime = SimpleNamespace(
        intro=Intro(),
        theory_parts=[SimpleNamespace(title="Риск", body="**Риск** — это событие, влияющее на срок проекта.")],
    )
    seed = SimpleNamespace(language="ru")

    instruction, theory_summary = PracticePhaseExecutor(runtime).extract_instruction_and_theory_summary("# README", seed)

    assert instruction == "instruction"
    assert "Риск" in theory_summary


def test_practice_executor_renders_practice_and_bonus_blocks() -> None:
    task = SimpleNamespace(
        title="Собрать артефакт",
        situation="Есть задача",
        input_data="Бриф",
        goal="Собрать таблицу",
        constraints_or_risk="Не добавлять лишних данных",
        group_roles=[],
        expected_artifact="Таблица",
        artifact_location="materials/task.csv",
        p2p_criteria=["Файл открыт"],
        approach_bullets=["Заполни строки"],
    )
    seed = SimpleNamespace(language="ru")

    markdown = PracticePhaseExecutor.render_practice_markdown(
        "## Глава 3. Практический блок\n\nЧерновик\n\n## Бонус\n\nЧерновик",
        [task],
        [task],
        True,
        seed,
    )

    assert "### Задание 1. Собрать артефакт" in markdown
    assert "### Бонусное задание 1*" in markdown
