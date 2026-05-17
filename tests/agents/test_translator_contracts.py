from __future__ import annotations

from content_gen.agents.base.llm_client import LLMClientProtocol
from content_gen.agents.translator import TranslatorAgent
from content_gen.models.schemas import ProjectSeed
from content_gen.utils.protected_blocks import protect_blocks


class RecordingTranslationLLM(LLMClientProtocol):
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict[str, str]] = []

    def complete(self, system: str, user: str, response_format=None, **kwargs) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response


def _seed() -> ProjectSeed:
    return ProjectSeed(
        language="ru",
        project_type="individual",
        direction="PjM",
        thematic_block="Блок",
        audience_level="base",
        project_description="Описание",
        sjm="Сюжет",
        learning_outcomes=[],
        skills=[],
        required_tools=[],
    )


def test_translation_protection_can_leave_tables_and_formulas_editable() -> None:
    markdown = """# Проект

| Риск | Вероятность |
| --- | --- |
| Срыв срока | высокая |

$$R = P \\cdot I \\quad \\text{Ожидаемый риск}$$

```mermaid
flowchart TD
    A --> B
```
"""

    protected, blocks = protect_blocks(
        markdown,
        protect_code=True,
        protect_mermaid=True,
        protect_formulas=False,
        protect_tables=False,
    )

    assert "| Риск | Вероятность |" in protected
    assert "$$R = P \\cdot I" in protected
    assert "[[[BLOCK_0]]]" in protected
    assert blocks[0].block_type == "mermaid"


def test_kyrgyz_translation_prompt_requires_cyrillic_and_exposes_tables_formulas() -> None:
    original = """# Проект

| Риск | Вероятность |
| --- | --- |
| Срыв срока | высокая |

$$R = P \\cdot I \\quad \\text{Ожидаемый риск}$$

```mermaid
flowchart TD
    A --> B
```
"""
    translated = """# Долбоор

| Тобокелдик | Ыктымалдык |
| --- | --- |
| Мөөнөт үзүлүшү | жогору |

$$R = P \\cdot I \\quad \\text{Күтүлгөн тобокелдик}$$

```mermaid
flowchart TD
A --> B
```
"""
    llm = RecordingTranslationLLM(translated)
    result = TranslatorAgent(llm).translate(original, "kg", _seed(), strict=True)

    prompt = llm.calls[0]["user"]
    system = llm.calls[0]["system"]
    assert "кыргызской кириллицей" in system
    assert "кыргызской кириллицей" in prompt
    assert "| Риск | Вероятность |" in prompt
    assert "$$R = P \\cdot I" in prompt
    assert "```mermaid" not in prompt
    assert "| Тобокелдик | Ыктымалдык |" in result
    assert "Ожидаемый риск" not in result


def test_translation_script_validator_flags_wrong_script() -> None:
    agent = TranslatorAgent(RecordingTranslationLLM(""))

    latin_kyrgyz = (
        "Bul dokumenttoghu tekst kyrgyz tilinde bolush kerek, birok al latin "
        "transliteratsiyasy menen jazylgan jana oquuchu uchun tushunuksuz."
    )
    assert agent._validate_script_coverage(latin_kyrgyz, "kg")
    assert not agent._validate_script_coverage(
        "Бул документ кыргыз тилинде жазылган, README жана API терминдери гана өзгөрбөйт.",
        "kg",
    )
    assert agent._validate_script_coverage(
        "Бу ҳужжат ҳали ҳам кириллда қолган ва ўзбек лотинига ўтмаган.",
        "uz",
    )
