"""Document-level agent contracts that remain after graph/run adapters removal."""

from content_gen.agents.style_guard import StyleGuardAgent
from content_gen.agents.toc import TOCAgent
from content_gen.models.readme_document import ReadmeDocument


def test_toc_build_and_inject_document_contract():
    agent = TOCAgent()
    document = ReadmeDocument.from_markdown(
        "# Проект\n\nАннотация.\n\n## Глава 1. Введение\n\n### Инструкция\n\nТекст."
    )

    toc = agent.build_document(document, language="ru")
    updated = agent.inject_document(document, toc.toc_md, language="ru")

    assert updated.sections[0].title == "Содержание"
    assert "- [Глава 1. Введение](#глава-1-введение)" in updated.sections[0].body
    assert "  - [Инструкция](#инструкция)" in updated.sections[0].body


def test_style_guard_document_contract():
    agent = StyleGuardAgent()
    document = ReadmeDocument.from_markdown("# Проект\n\nНажми кнопку для продолжения.")

    issues = agent.lint_document(document, "ru")
    fixed_document = agent.rewrite_document(document, "ru")

    assert issues
    assert isinstance(fixed_document, ReadmeDocument)
    assert "нажми" not in fixed_document.to_markdown().lower()
