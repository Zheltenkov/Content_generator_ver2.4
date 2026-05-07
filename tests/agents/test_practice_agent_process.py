"""Тесты контракта process/run для PracticeAgent."""

from content_gen.agents.base.llm_client import LLMClientProtocol
from content_gen.agents.practice import PracticeAgent, PracticeResult
from content_gen.models.schemas import PracticeTask, ProjectSeed


class MockLLMClient(LLMClientProtocol):
    """Минимальный мок LLM клиента."""

    def complete(self, system: str, user: str, response_format=None, **kwargs) -> str:
        return "mock response"


def _seed() -> ProjectSeed:
    return ProjectSeed(
        language="ru",
        project_type="individual",
        project_description="Тестовый проект",
        learning_outcomes=["Сформулировать цель"],
        skills=["Анализ требований"],
    )


def test_process_returns_serialized_tasks_and_result(monkeypatch):
    """process() должен возвращать сериализованные задачи и оригинальный result."""
    agent = PracticeAgent(MockLLMClient())
    seed = _seed()
    expected_task = PracticeTask(
        title="Задание 1. Тест",
        situation="Команда получила неоднозначный запрос и не понимает, какой артефакт нужен для проверки.",
        constraints_or_risk="Если не зафиксировать результат сейчас, ревьюер не сможет проверить задачу одинаково с автором.",
        input_data="Описание запроса — см. файл `materials/request.md`",
        goal="Подготовь проверяемый артефакт по задаче.",
        approach_bullets=["Собери требования к результату.", "Оформи артефакт в понятном виде."],
        expected_artifact="Документ размещён в `PjM00_Test/part-03/task-01/README.md`",
        artifact_location="PjM00_Test/part-03/task-01/README.md",
        p2p_criteria=[
            "Документ размещён по указанному пути.",
            "В документе есть минимум 3 проверяемых пункта.",
            "Результат можно проверить без пояснений автора.",
        ],
    )

    def fake_generate(seed_arg, instruction_text="", theory_summary=""):
        assert seed_arg == seed
        assert instruction_text == "instr"
        assert theory_summary == "theory"
        return PracticeResult(tasks=[expected_task], bonus_tasks=[])

    monkeypatch.setattr(agent, "generate", fake_generate)

    out = agent.process(
        {
            "seed": seed,
            "instruction_text": "instr",
            "theory_summary": "theory",
        }
    )
    assert out["tasks"][0]["title"] == "Задание 1. Тест"
    assert out["result"].tasks[0].title == "Задание 1. Тест"
