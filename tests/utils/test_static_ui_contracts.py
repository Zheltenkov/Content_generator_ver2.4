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


def test_methodology_panel_has_assistant_command_chat():
    js = (ROOT / "static" / "js" / "modules" / "methodologyPanel.js").read_text(encoding="utf-8")

    assert "methodologyAssistantInput" in js
    assert "submitAssistantCommand" in js
    assert "/assistant-command" in js
    assert "selected_target_id" in js


def test_main_extracts_table_captions_and_renders_generated_data_tab():
    renderer_js = (ROOT / "static" / "js" / "modules" / "markdownRendering.js").read_text(encoding="utf-8")
    result_tabs_js = (ROOT / "static" / "js" / "modules" / "generationResultTabs.js").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

    assert "function extractTableCaption" in renderer_js
    assert "function renderGeneratedDataTab" in result_tabs_js
    assert "renderGeneratedDataTab(data.result);" in main_js


def test_generation_results_return_to_readme_tab_after_methodology_completion():
    js = (ROOT / "static" / "js" / "modules" / "generationResultTabs.js").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")

    assert "function activateResultTab" in js
    assert "activateResultTab('readme');" in main_js


def test_generation_runtime_split_modules_are_loaded():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    polling_js = (ROOT / "static" / "js" / "modules" / "generationPolling.js").read_text(encoding="utf-8")
    persistence_js = (ROOT / "static" / "js" / "modules" / "generationPersistence.js").read_text(encoding="utf-8")

    assert "generationPolling.js" in html
    assert "generationPersistence.js" in html
    assert "async function pollGenerationStatus" in polling_js
    assert "async function loadGenerationState" in persistence_js
    assert "async function pollGenerationStatus" not in main_js
    assert "async function loadGenerationState" not in main_js


def test_methodology_assistant_chat_is_split_from_main():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    chat_js = (ROOT / "static" / "js" / "modules" / "methodologyAssistantChat.js").read_text(encoding="utf-8")

    assert "methodologyAssistantChat.js" in html
    assert "window.MethodologyAssistantChat" in chat_js
    assert "async function send" in chat_js
    assert "assistant-command" in chat_js
    assert "function initializeMethodologyAssistantChat" not in main_js
    assert "async function sendAssistantChatMessage" not in main_js
    assert "window.MethodologyAssistantChat?.configure" in main_js


def test_generation_pipeline_ui_matches_runtime_flow_without_antiplag_stage():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    run_view_js = (ROOT / "static" / "js" / "modules" / "generationRunView.js").read_text(encoding="utf-8")
    flow_yaml = (ROOT / "content_gen" / "config" / "flow.yaml").read_text(encoding="utf-8")

    assert "antiplag" not in flow_yaml.lower()
    assert "data-run-stage=\"antiplagiarism\"" not in html
    assert "Антиплагиат" not in html
    assert "id: 'antiplagiarism'" not in run_view_js
    assert "plagiarism: 'antiplagiarism'" not in run_view_js
    assert "generationRunStageTotal\">9<" in html


def test_curriculum_form_runtime_is_split_from_main():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    curriculum_js = (ROOT / "static" / "js" / "modules" / "curriculumForm.js").read_text(encoding="utf-8")

    assert "curriculumForm.js" in html
    assert "async function handleCurriculumUpload" in curriculum_js
    assert "function buildCurriculumContext" in curriculum_js
    assert "getCurrentCurriculumContext" in curriculum_js
    assert "async function handleCurriculumUpload" not in main_js
    assert "function buildCurriculumContext" not in main_js
    assert "getCurrentCurriculumContext" in main_js


def test_metrics_view_runtime_is_split_from_main():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    metrics_js = (ROOT / "static" / "js" / "modules" / "metricsView.js").read_text(encoding="utf-8")

    assert "metricsView.js" in html
    assert "function displayMetrics" in metrics_js
    assert "function displayReport" in metrics_js
    assert "function filterMetrics" in metrics_js
    assert "function displayMetrics" not in main_js
    assert "function displayReport" not in main_js
    assert "function filterMetrics" not in main_js


def test_checker_runtime_is_split_into_focused_modules():
    html = (ROOT / "static" / "checker.html").read_text(encoding="utf-8")
    checker_js = (ROOT / "static" / "js" / "modules" / "checkerPage.js").read_text(encoding="utf-8")
    preview_js = (ROOT / "static" / "js" / "modules" / "checkerReadmePreview.js").read_text(encoding="utf-8")
    diff_js = (ROOT / "static" / "js" / "modules" / "checkerDiffView.js").read_text(encoding="utf-8")
    metrics_js = (ROOT / "static" / "js" / "modules" / "checkerMetricsSwitch.js").read_text(encoding="utf-8")
    curriculum_js = (ROOT / "static" / "js" / "modules" / "checkerCurriculumState.js").read_text(encoding="utf-8")
    modal_js = (ROOT / "static" / "js" / "modules" / "checkerImprovementModal.js").read_text(encoding="utf-8")
    run_js = (ROOT / "static" / "js" / "modules" / "checkerImprovementRun.js").read_text(encoding="utf-8")

    assert "checkerReadmePreview.js" in html
    assert "checkerDiffView.js" in html
    assert "checkerMetricsSwitch.js" in html
    assert "checkerCurriculumState.js" in html
    assert "checkerImprovementModal.js" in html
    assert "checkerImprovementRun.js" in html
    assert "function displayImprovedReadme" in preview_js
    assert "function displayReadmeDiff" in diff_js
    assert "function switchCheckerMetricsVersion" in metrics_js
    assert "function handleCheckerCurriculumUpload" in curriculum_js
    assert "function startImprovement" in modal_js
    assert "function generateImprovedReadme" in run_js
    assert "function displayImprovedReadme" not in checker_js
    assert "function displayReadmeDiff" not in checker_js
    assert "function switchCheckerMetricsVersion" not in checker_js
    assert "function handleCheckerCurriculumUpload" not in checker_js
    assert "function startImprovement" not in checker_js
    assert "function generateImprovedReadme" not in checker_js


def test_checker_page_styles_are_split_from_design_monolith():
    html = (ROOT / "static" / "checker.html").read_text(encoding="utf-8")
    design_css = (ROOT / "static" / "css" / "s21-design.css").read_text(encoding="utf-8")
    checker_css = (ROOT / "static" / "css" / "s21-checker.css").read_text(encoding="utf-8")
    tokens_css = (ROOT / "static" / "css" / "s21-tokens.css").read_text(encoding="utf-8")
    base_css = (ROOT / "static" / "css" / "s21-base.css").read_text(encoding="utf-8")
    forms_css = (ROOT / "static" / "css" / "s21-forms.css").read_text(encoding="utf-8")
    buttons_css = (ROOT / "static" / "css" / "s21-buttons.css").read_text(encoding="utf-8")
    badges_css = (ROOT / "static" / "css" / "s21-badges.css").read_text(encoding="utf-8")
    markdown_css = (ROOT / "static" / "css" / "s21-markdown.css").read_text(encoding="utf-8")

    assert "s21-checker.css" in html
    assert "s21-tokens.css" in html
    assert "s21-base.css" in html
    assert "s21-forms.css" in html
    assert "s21-buttons.css" in html
    assert "s21-badges.css" in html
    assert "s21-markdown.css" in html
    assert "body.s21-product.page-checker" in checker_css
    assert "body.s21-product.page-checker" not in design_css
    assert "МОДАЛКА" not in checker_css
    assert ":root" in tokens_css
    assert "body.s21-product {" in base_css
    assert "body.s21-product input[type=\"text\"]" in forms_css
    assert "body.s21-product .btn" in buttons_css
    assert "body.s21-product .badge" in badges_css
    assert "body.s21-product .markdown-preview" in markdown_css


def test_page_specific_product_styles_are_split_from_design_monolith():
    index_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app_html = (ROOT / "static" / "app.html").read_text(encoding="utf-8")
    checker_html = (ROOT / "static" / "checker.html").read_text(encoding="utf-8")
    translator_html = (ROOT / "static" / "translator.html").read_text(encoding="utf-8")
    design_css = (ROOT / "static" / "css" / "s21-design.css").read_text(encoding="utf-8")
    workflow_css = (ROOT / "static" / "css" / "s21-workflow.css").read_text(encoding="utf-8")
    methodology_css = (ROOT / "static" / "css" / "s21-methodology.css").read_text(encoding="utf-8")
    generate_css = (ROOT / "static" / "css" / "s21-generate.css").read_text(encoding="utf-8")
    metrics_css = (ROOT / "static" / "css" / "s21-metrics.css").read_text(encoding="utf-8")
    dashboard_css = (ROOT / "static" / "css" / "s21-dashboard.css").read_text(encoding="utf-8")
    translation_css = (ROOT / "static" / "css" / "s21-translation.css").read_text(encoding="utf-8")

    assert "s21-workflow.css" in index_html
    assert "s21-methodology.css" in index_html
    assert "s21-generate.css" in index_html
    assert "s21-metrics.css" in index_html
    assert "s21-dashboard.css" in app_html
    assert "s21-workflow.css" in checker_html
    assert "s21-metrics.css" in checker_html
    assert "s21-workflow.css" in translator_html
    assert "body.s21-product .generation-status-panel {" in workflow_css
    assert "body.s21-product .methodology-review-workspace {" in methodology_css
    assert "body.s21-product.page-generate {" in generate_css
    assert ".s21-metrics-view {" in metrics_css
    assert "body.s21-product.page-menu {" in dashboard_css
    assert ".translate-topbar {" in translation_css
    assert "body.s21-product .generation-status-panel {" not in design_css
    assert "body.s21-product.page-generate {" not in design_css
    assert ".s21-metrics-view {" not in design_css
    assert "body.s21-product.page-menu {" not in design_css
    assert ".dashboard-header {" not in design_css
    assert ".generator-topbar {" not in design_css
    assert ".s21-metric-row {" not in design_css
    assert ".translate-topbar {" not in design_css
    assert ".methodology-assistant-chat {" not in design_css
    assert "@media (max-width: 820px)" in dashboard_css
    assert "@media (max-width: 820px)" in generate_css
    assert "@media (max-width: 820px)" in metrics_css
    assert "@media (max-width: 820px)" in translation_css


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
    js = (ROOT / "static" / "js" / "modules" / "markdownRendering.js").read_text(encoding="utf-8")
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
