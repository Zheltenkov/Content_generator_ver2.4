from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_checker_loads_mermaid_for_markdown_preview():
    html = (ROOT / "static" / "checker.html").read_text(encoding="utf-8")

    assert "mermaid.min.js" in html


def test_translator_video_limit_hint_matches_backend_default():
    html = (ROOT / "static" / "translator.html").read_text(encoding="utf-8")

    assert "До 100 MB" in html
    assert "До 500 MB" not in html


def test_main_exports_shared_markdown_renderer_for_checker():
    js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

    assert "window.displayMarkdown = displayMarkdown;" in js
    assert "window.renderMarkdownPreview = renderMarkdownPreview;" in js
    assert "window.normalizeMarkdownForDisplay = normalizeMarkdownForDisplay;" in js
    assert "window.renderMermaidDiagrams = renderMermaidDiagrams;" in js


def test_generator_results_tabs_have_data_tab_without_methodologist_tab():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert "showTab('generatedData'" in html
    assert 'id="generatedDataContent"' in html
    assert "showTab('methodology'" not in html


def test_methodology_change_request_button_copy_is_edit_changes():
    js = (ROOT / "static" / "js" / "modules" / "methodologyPanel.js").read_text(encoding="utf-8")

    assert "Изменить правки" in js
    assert "Запросить правки</button>" not in js


def test_main_extracts_table_captions_and_renders_generated_data_tab():
    js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

    assert "function extractTableCaption" in js
    assert "function renderGeneratedDataTab" in js
    assert "renderGeneratedDataTab(data.result);" in js


def test_generation_results_return_to_readme_tab_after_methodology_completion():
    js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

    assert "function activateResultTab" in js
    assert "activateResultTab('readme');" in js


def test_methodology_review_renders_requirement_matrix_as_ui():
    js = (ROOT / "static" / "js" / "modules" / "methodologyPanel.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderRequirementsMatrix" in js
    assert "key === 'requirements_matrix'" in js
    assert "methodology-requirements-matrix" in js
    assert ".methodology-requirements-matrix" in css
    assert ".methodology-requirement-row.status-fail" in css


def test_methodology_preview_uses_shared_markdown_renderer():
    js = (ROOT / "static" / "js" / "modules" / "methodologyPanel.js").read_text(encoding="utf-8")

    assert "window.renderMarkdownPreview" in js
    assert "function repairBrokenMermaidPreviewMarkdown" not in js
    assert "function renderBasicMarkdownHtml" not in js
    assert "function wrapMarkdownTables(root)" not in js


def test_mermaid_diagram_contract_is_scrollable_and_shared_with_images():
    js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    assert "function renderMarkdownPreview" in js
    assert "function wrapDiagramImages" in js
    assert "holder.dataset.diagramOverflow = isWide ? 'scroll' : 'fit';" in js
    assert ".diagram-image-surface" in css
    assert "data-diagram-overflow=\"scroll\"" in css


def test_path_like_values_do_not_wrap_one_character_per_line():
    css = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
    methodology_js = (ROOT / "static" / "js" / "modules" / "methodologyPanel.js").read_text(encoding="utf-8")

    assert ".markdown-preview :not(pre) > code" in css
    assert ".generated-data-path" in css
    assert ".methodology-artifact-list code.path-token" in css
    assert "white-space: nowrap !important;" in css
    assert "overflow-x: auto;" in css
    assert "word-break: normal !important;" in css
    assert "overflow-wrap: normal !important;" in css
    assert 'class="path-token"' in methodology_js
