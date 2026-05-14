// Generator result tabs and README/data preview controller.
// Keeps result-specific rendering separate from generation orchestration.

        let resultReadmeRenderMode = 'preview';

        function getResultRuntimeState() {
            const runtime = window.ContentGenGenerationRuntime || {};
            return typeof runtime.getState === 'function' ? runtime.getState() : {};
        }

function extractReadmeToc(markdown) {
            const toc = [];
            String(markdown || '').split(/\r?\n/).forEach((line) => {
                const match = line.match(/^(#{1,3})\s+(.+?)\s*$/);
                if (!match) return;
                const title = match[2].replace(/[#*_`]/g, '').trim();
                if (!title || /^содержание$/i.test(title)) return;
                toc.push({
                    level: match[1].length,
                    title,
                    key: `${match[1].length}-${title.toLowerCase().replace(/\s+/g, '-')}-${toc.length}`
                });
            });
            return toc.slice(0, 18);
        }

        function renderReadmeToc(markdown) {
            const aside = document.getElementById('readmeToc');
            if (!aside) return;
            const toc = extractReadmeToc(markdown);
            aside.innerHTML = '';

            const title = document.createElement('div');
            title.className = 'readme-toc-title';
            title.textContent = 'СОДЕРЖАНИЕ';
            aside.appendChild(title);

            if (!toc.length) {
                const empty = document.createElement('div');
                empty.className = 'readme-toc-empty';
                empty.textContent = 'Заголовки появятся после рендера README.';
                aside.appendChild(empty);
                return;
            }

            toc.forEach((item, index) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `readme-toc-link level-${item.level}${index === 0 ? ' active' : ''}`;
                button.textContent = item.title;
                button.dataset.heading = item.title;
                button.addEventListener('click', () => scrollReadmeToHeading(item.title, button));
                aside.appendChild(button);
            });
        }

        function scrollReadmeToHeading(title, activeButton = null) {
            const container = document.getElementById('readmeContent');
            if (!container) return;
            const normalized = String(title || '').trim();
            const heading = [...container.querySelectorAll('h1, h2, h3')]
                .find((node) => (node.textContent || '').trim() === normalized);
            if (heading) {
                heading.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
            document.querySelectorAll('#readmeToc .readme-toc-link').forEach((btn) => btn.classList.remove('active'));
            if (activeButton) activeButton.classList.add('active');
        }

        function renderResultReadme(markdown) {
            const container = document.getElementById('readmeContent');
            if (!container) return;
            if (resultReadmeRenderMode === 'preview') {
                displayMarkdown(markdown, 'readmeContent');
            } else {
                const escaped = escapeHtmlSafe(markdown || '');
                container.innerHTML = `<pre class="result-markdown-source">${escaped}</pre>`;
            }
            renderReadmeToc(markdown);
        }

        function setReadmeRenderMode(mode) {
            resultReadmeRenderMode = mode === 'preview' ? 'preview' : 'markdown';
            document.getElementById('readmeModeMarkdown')?.classList.toggle('active', resultReadmeRenderMode === 'markdown');
            document.getElementById('readmeModePreview')?.classList.toggle('active', resultReadmeRenderMode === 'preview');
            const { currentMarkdown } = getResultRuntimeState();
            if (currentMarkdown) {
                renderResultReadme(currentMarkdown);
            }
        }

        function compareCurrentResult() {
            const { regeneratedRubric, regeneratedTextStats } = getResultRuntimeState();
            if (regeneratedRubric || regeneratedTextStats || document.getElementById('regenContent')?.textContent?.trim()) {
                showTab('regen', document.querySelector('.result-tabs .tab[onclick*="regen"]'));
                return;
            }
            showTab('metrics', document.querySelector('.result-tabs .tab[onclick*="metrics"]'));
        }

        function openRegenerationFromMetrics() {
            window.fillCommentsFromFailedCriteria?.();
            showTab('regen', document.querySelector('.result-tabs .tab[onclick*="regen"]'));
            document.getElementById('regenerationComments')?.focus();
        }

        function activateResultTab(tabName) {
            const tabButton = [...document.querySelectorAll('#resultsArea .result-tabs .tab, #resultsArea > .tabs .tab')]
                .find(tab => {
                    const handler = tab.getAttribute('onclick') || '';
                    return handler.includes(`'${tabName}'`) || handler.includes(`"${tabName}"`);
                });
            if (tabButton) {
                showTab(tabName, tabButton);
            }
        }

function renderGeneratedDataTab(result) {
            const container = document.getElementById('generatedDataContent');
            if (!container) return;

            const assets = result?.assets || result?.report_json?.assets || {};
            const files = Array.isArray(assets.files) ? assets.files.filter(Boolean) : [];
            if (!files.length) {
                container.innerHTML = '<div>Сгенерированные файлы данных отсутствуют. Если задания ссылаются на materials/data, они появятся здесь после генерации.</div>';
                return;
            }

            const items = files.map((file, index) => {
                const path = String(file.path || file.name || `file-${index + 1}`).trim();
                const decoded = decodeGeneratedAssetText(file);
                const sizeLabel = formatGeneratedAssetSize(file.data);
                const escapedPath = window.sanitize ? window.sanitize.escapeHtml(path) : path;
                const escapedSize = window.sanitize ? window.sanitize.escapeHtml(sizeLabel) : sizeLabel;
                const preview = decoded
                    ? renderGeneratedAssetPreview(decoded)
                    : '<div class="generated-data-empty">Предпросмотр недоступен для бинарного файла. Файл будет в архиве.</div>';
                return `
                    <details class="generated-data-item" ${index === 0 ? 'open' : ''}>
                        <summary>
                            <span class="generated-data-path">${escapedPath}</span>
                            <span class="generated-data-size">${escapedSize}</span>
                        </summary>
                        ${preview}
                    </details>
                `;
            }).join('');

            const intro = `<div class="generated-data-summary">Файлы, которые попадут в архив вместе с README: ${files.length}.</div>`;
            if (window.sanitize) {
                window.sanitize.safeSetHTML(container, intro + `<div class="generated-data-list">${items}</div>`);
            } else {
                container.innerHTML = intro + `<div class="generated-data-list">${items}</div>`;
            }
        }

        function renderGeneratedAssetPreview(text) {
            const previewText = String(text || '').slice(0, 4000);
            const escaped = window.sanitize ? window.sanitize.escapeHtml(previewText) : previewText;
            const suffix = String(text || '').length > previewText.length
                ? '<div class="generated-data-empty">Показан фрагмент первых 4000 символов.</div>'
                : '';
            return `<pre class="generated-data-preview">${escaped}</pre>${suffix}`;
        }

        function decodeGeneratedAssetText(file) {
            const path = String(file?.path || file?.name || '');
            if (!/\.(md|markdown|txt|csv|json|yaml|yml|xml|html|htm|js|ts|py|sql|ini|toml)$/i.test(path)) {
                return '';
            }
            try {
                const raw = atob(String(file.data || ''));
                const bytes = Uint8Array.from(raw, char => char.charCodeAt(0));
                const text = new TextDecoder('utf-8', { fatal: false }).decode(bytes);
                const controlChars = (text.match(/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/g) || []).length;
                if (text.length && controlChars / text.length > 0.04) {
                    return '';
                }
                return text;
            } catch (_error) {
                return '';
            }
        }

        function formatGeneratedAssetSize(base64Data) {
            const value = String(base64Data || '');
            if (!value) return '0 Б';
            const padding = (value.match(/=+$/) || [''])[0].length;
            const bytes = Math.max(0, Math.floor(value.length * 3 / 4) - padding);
            if (bytes < 1024) return `${bytes} Б`;
            if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
            return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
        }

        if (typeof window !== 'undefined') {
            Object.assign(window, {
                extractReadmeToc,
                renderReadmeToc,
                scrollReadmeToHeading,
                renderResultReadme,
                setReadmeRenderMode,
                compareCurrentResult,
                openRegenerationFromMetrics,
                activateResultTab,
                renderGeneratedDataTab,
                renderGeneratedAssetPreview,
                decodeGeneratedAssetText,
                formatGeneratedAssetSize,
            });
        }

