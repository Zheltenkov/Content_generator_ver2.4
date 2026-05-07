"""Тесты run()-адаптеров для non-Base агентов."""

from content_gen.agents.intent_mapper import IntentMapper
from content_gen.agents.intro_rules import IntroResult, IntroRulesAgent
from content_gen.agents.practice import PracticeAgent
from content_gen.agents.practice_critic import PracticeCriticAgent, PracticeIssue
from content_gen.agents.regeneration import RegenerationAgent, RegenerationResult
from content_gen.agents.skeleton import SkeletonAgent
from content_gen.agents.style_guard import StyleGuardAgent
from content_gen.agents.title_annotation import TitleAnnotation, TitleAnnotationAgent
from content_gen.agents.toc import TOCAgent
from content_gen.agents.translator import TranslatorAgent
from content_gen.models.criteria_models import CriteriaReport
from content_gen.models.schemas import Annotation, PracticeTask, ProjectContextMeta, ProjectSeed
from content_gen.validators.rubric.scorer import RubricScorer


class MockLLMClient:
    """Минимальный мок LLM клиента."""

    def complete(self, system: str, user: str, **kwargs) -> str:
        return ""


def _seed() -> ProjectSeed:
    return ProjectSeed(
        language="ru",
        project_type="individual",
        project_description="desc",
        learning_outcomes=["lo"],
        skills=["skill"],
    )


def _context_meta() -> ProjectContextMeta:
    return ProjectContextMeta(track="DS", thematic_block="DS block", context_summary="", narrative_anchor="")


def test_title_annotation_run_delegates_generate(monkeypatch):
    agent = TitleAnnotationAgent(MockLLMClient())
    expected = TitleAnnotation(title="T", annotation=Annotation(text="A", chars=1))
    monkeypatch.setattr(agent, "generate", lambda seed, context: expected)
    out = agent.run({"seed": _seed(), "context": _context_meta()})
    assert out["result"] == expected


def test_intro_rules_run_delegates_generate(monkeypatch):
    agent = IntroRulesAgent(MockLLMClient())
    expected = IntroResult(intro_text="intro", instruction_text="instr")
    monkeypatch.setattr(agent, "generate", lambda seed, context: expected)
    out = agent.run({"seed": _seed(), "context": _context_meta()})
    assert out["result"] == expected


def test_regeneration_run_delegates_regenerate(monkeypatch):
    agent = RegenerationAgent(MockLLMClient())
    expected = RegenerationResult(changes=["ok"], regenerated_md="new", original_md="old")
    monkeypatch.setattr(
        agent,
        "regenerate",
        lambda original_md, comments, language="ru": expected,
    )
    out = agent.run({"original_md": "old", "comments": "fix", "language": "ru"})
    assert out["result"] == expected


def test_toc_run_delegates_build():
    agent = TOCAgent()
    md = "## Глава 1\n\n### Подраздел\n"
    out = agent.run({"md": md, "language": "ru"})
    assert "Глава 1" in out["result"].toc_md
    assert "Подраздел" in out["result"].toc_md


def test_style_guard_run_lint_and_rewrite():
    agent = StyleGuardAgent()
    text = "Нажми кнопку для продолжения."
    issues = agent.run({"op": "lint", "text": text, "language": "ru"})["result"]
    assert len(issues) >= 1
    fixed = agent.run({"op": "rewrite", "text": text, "language": "ru"})["result"]
    assert "нажми" not in fixed.lower()


def test_rubric_scorer_run_delegates_score(monkeypatch):
    scorer = RubricScorer(language="ru", llm_client=None)
    report = CriteriaReport(items=[], total=0, max_score=1)
    monkeypatch.setattr(
        scorer,
        "score",
        lambda md, learning_outcomes=None, use_cache=True: report,
    )
    out = scorer.run({"md": "# x", "learning_outcomes": ["a"]})
    assert out["result"] is report


def test_skeleton_run_build_and_stitch():
    agent = SkeletonAgent()
    sk = agent.run({"op": "build", "language": "ru", "has_bonus": False})["result"]
    md = agent.run(
        {
            "op": "stitch",
            "title": "Проект",
            "annotation_md": "Кратко.",
            "sk": sk,
        }
    )["result"]
    assert "# Проект" in md
    assert "Содержание" in md


def test_translator_run_delegates_translate(monkeypatch):
    agent = TranslatorAgent(MockLLMClient())
    seed = _seed()
    monkeypatch.setattr(agent, "translate", lambda *a, **k: "TRANSLATED")
    out = agent.run(
        {"markdown": "orig", "target_language": "en", "seed": seed}
    )
    assert out["result"] == "TRANSLATED"


def test_intent_mapper_run_matches_map():
    mapper = IntentMapper()
    raw = {
        "language": "ru",
        "project_type": "individual",
        "project_description": "desc",
        "learning_outcomes": ["lo"],
        "skills": ["s"],
    }
    a = mapper.run({"raw": raw})
    b_seed, b_warn = mapper.map(raw)
    assert a["seed"].project_description == b_seed.project_description
    assert a["warnings"].messages == b_warn.messages


def test_practice_run_bonus_op(monkeypatch):
    agent = PracticeAgent(MockLLMClient())
    seed = _seed()
    fake_tasks = [
        PracticeTask(title="B1", goal="g", expected_artifact="a"),
    ]
    monkeypatch.setattr(agent, "generate_bonus", lambda s, n: fake_tasks)
    out = agent.run({"op": "bonus", "seed": seed, "n_bonus": 1})
    assert out["result"] == fake_tasks
    assert len(out["tasks"]) == 1


def test_practice_critic_run_delegates_review(monkeypatch):
    agent = PracticeCriticAgent(MockLLMClient())
    seed = _seed()
    issues = [
        PracticeIssue(
            task_index=0,
            kind="x",
            severity="warning",
            message="m",
            suggestion="s",
        )
    ]
    monkeypatch.setattr(agent, "review", lambda **k: issues)
    out = agent.run(
        {
            "seed": seed,
            "practice_markdown": "md",
            "theory_summary": "th",
        }
    )
    assert out["result"] == issues


