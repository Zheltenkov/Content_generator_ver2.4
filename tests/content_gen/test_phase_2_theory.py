from types import SimpleNamespace

from content_gen.agents.theory import TheoryResult
from content_gen.models.schemas import ProjectContextMeta, ProjectSeed, TheoryPart
from content_gen.orchestrator_phases_modules.phases.phase_2 import (
    _remove_static_instruction_leaks,
    phase_2_theory,
)
from content_gen.validators.theory_checks import TheoryChecks


def _make_seed() -> ProjectSeed:
    return ProjectSeed(
        language="ru",
        project_type="individual",
        thematic_block="PjM",
        audience_level="base",
        required_tools=["Miro"],
        title_seed="Test",
        project_description="Проект про планирование и коммуникацию в команде.",
        learning_outcomes=["Понимать базовые принципы планирования проекта"],
        skills=["Планирование", "Коммуникация"],
    )


def _valid_body() -> str:
    definitions = (
        "**Коммуникация** — это согласованный обмен информацией внутри команды. "
        "**Риск** — это событие, которое может сорвать срок, объём или качество результата. "
    )
    filler_sentence = (
        "Ты смотришь на сроки, роли, ожидания, договорённости и последствия решений в проекте. "
    )
    filler = filler_sentence * 28
    return (definitions + filler).strip()


def _invalid_part(idx: int) -> TheoryPart:
    return TheoryPart(
        title=f"Часть {idx}",
        body=_valid_body(),
        example="",
        bridge_questions=[],
    )


class _TheoryAgentStub:
    def generate(self, seed, context_meta, desired_parts=3):
        return TheoryResult(parts=[_invalid_part(1), _invalid_part(2), _invalid_part(3)])


class _IdentityAgent:
    def ensure_definitions(self, part, seed):
        return part

    def fix_length(self, part, seed):
        return part

    def improve_readability(self, part, seed):
        return part


class _EnhancementStub:
    def enhance(self, parts, seed):
        return parts, [], []


class _EditorStub:
    def edit_theory_parts(self, parts, seed):
        return parts


class _RegenerationStub:
    def regenerate(self, original_md, comments, language):
        return SimpleNamespace(
            regenerated_md=(
                "### Часть 1. Исправленная часть\n\n"
                f"{_valid_body()}\n\n"
                "**Пример:** В 2024 году команда сократила задержки, когда заранее описала риски и роли.\n\n"
                "**Вопросы к практике:**\n"
                "- Как ты опишешь риски и роли для своей проектной задачи?\n"
            )
        )


class _OrchestratorStub:
    def __init__(self):
        self.theory = _TheoryAgentStub()
        self.definitions_agent = _IdentityAgent()
        self.length_agent = _IdentityAgent()
        self.readability_agent = _IdentityAgent()
        self.theory_checks = TheoryChecks()
        self.regeneration = _RegenerationStub()
        self.theory_enhancement = _EnhancementStub()
        self.content_editor = _EditorStub()
        self.cancellation_token = None
        self.progress_tracker = None


def test_phase_2_theory_returns_only_final_issues_after_regeneration():
    orchestrator = _OrchestratorStub()
    seed = _make_seed()
    context_meta = ProjectContextMeta(track="PjM", thematic_block="PjM")
    markdown = "## Глава 2. Теоретический блок\n\nЧерновик\n\n## Глава 3. Практический блок\n"

    updated_md, theory_parts, issues, warnings = phase_2_theory(orchestrator, seed, context_meta, markdown)

    assert len(theory_parts) == 3
    assert not [issue for issue in issues if getattr(issue, "severity", None) == "hard"]
    assert "### 2.1." in updated_md
    assert "### Часть 1." not in updated_md
    assert "**Пример:**" in updated_md
    assert "**Вопросы к практике:**" in updated_md
    assert any("локальная коррекция сняла критические замечания" in warning for warning in warnings)


def test_static_instruction_leak_is_removed_from_theory_body():
    text = (
        "Теперь, когда ты освоил базовые навыки работы с репозиторием и методами проверки через P2P, "
        "перейдём к рискам. Риск — это событие, которое может повлиять на срок проекта."
    )

    cleaned = _remove_static_instruction_leaks(text)

    assert "репозиторием" not in cleaned
    assert "P2P" not in cleaned
    assert "Риск" in cleaned
