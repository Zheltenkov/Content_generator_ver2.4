// Shared Markdown normalization/rendering utilities for generator, checker and translator.
// Keep this file API-compatible with the legacy globals previously declared in main.js.

        const BLOCK_PLACEHOLDER = (idx) => `@@FORMULABLOCK${idx}@@`;
        const INLINE_PLACEHOLDER = (idx) => `@@FORMULAINLINE${idx}@@`;
        const escapeRegex = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        function byId(id) {
            return document.getElementById(id);
        }

        function getChecked(id, fallback = false) {
            const element = byId(id);
            return element ? !!element.checked : fallback;
        }

        function setChecked(id, value) {
            const element = byId(id);
            if (element) {
                element.checked = !!value;
            }
        }

        function setValue(id, value) {
            const element = byId(id);
            if (element) {
                element.value = value ?? '';
            }
        }

        function normalizeAudienceLevel(value) {
            const norm = String(value || '').trim().toLowerCase();
            if (!norm) return 'beginner_plus';
            if (['beginner_plus', 'beginner+', 'basic+', 'base+', 'базовый+', 'начальный+'].includes(norm)) {
                return 'beginner_plus';
            }
            if (['beginner', 'basic', 'base', 'базовый', 'начальный'].includes(norm)) return 'beginner';
            if (['middle', 'intermediate', 'средний'].includes(norm)) return 'middle';
            if (['advanced', 'продвинутый'].includes(norm)) return 'advanced';
            if (['professional', 'pro', 'expert', 'профессиональный', 'экспертный'].includes(norm)) return 'professional';
            return 'beginner_plus';
        }

        function setAudienceLevel(value) {
            setValue('audienceLevel', normalizeAudienceLevel(value));
        }

        function splitCommaList(value) {
            return String(value || '')
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean);
        }

        function setDisplay(id, displayValue) {
            const element = byId(id);
            if (element) {
                element.style.display = displayValue;
            }
        }

        function protectFormulas(markdown) {
            const block = [];
            const inline = [];
            let text = markdown.replace(/\$\$([\s\S]*?)\$\$/g, (match, formula) => {
                const idx = block.length;
                block.push(formula.trim());
                return BLOCK_PLACEHOLDER(idx);
            });

            const inlineRegex = /(^|[^\$\\])\$(?!\$)([^$\n]+?)\$(?!\$)/g;
            text = text.replace(inlineRegex, (match, prefix, formula) => {
                const idx = inline.length;
                inline.push(formula.trim());
                return `${prefix}${INLINE_PLACEHOLDER(idx)}`;
            });

            return { markdown: text, block, inline };
        }

        function restoreFormulas(html, guards) {
            const { block, inline } = guards;

            block.forEach((formula, index) => {
                const placeholder = new RegExp(escapeRegex(BLOCK_PLACEHOLDER(index)), 'g');
                html = html.replace(placeholder, `\n\n$$${formula}$$\n\n`);
            });

            inline.forEach((formula, index) => {
                const placeholder = new RegExp(escapeRegex(INLINE_PLACEHOLDER(index)), 'g');
                html = html.replace(placeholder, `$${formula}$`);
            });

            return html;
        }

        function applyOutsideFencedBlocks(markdown, transform) {
            const text = markdown || '';
            const rx = /```[\s\S]*?```/g;
            let result = '';
            let pos = 0;
            let match;
            while ((match = rx.exec(text)) !== null) {
                result += transform(text.slice(pos, match.index));
                result += match[0];
                pos = match.index + match[0].length;
            }
            result += transform(text.slice(pos));
            return result;
        }

        function looksLikeFlattenedTable(line) {
            const pipeCount = (line.match(/\|/g) || []).length;
            return pipeCount >= 6
                && /\|\s+(?=\|)/.test(line)
                && /\|\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|/.test(line);
        }

        function repairFlattenedTableLine(line) {
            const firstPipe = line.indexOf('|');
            if (firstPipe < 0) return [line];

            const prefix = line.slice(0, firstPipe).trimEnd();
            const tableText = line.slice(firstPipe).trim().replace(/\|\s+(?=\|)/g, '|\n');
            const repaired = [];
            const trailing = [];

            if (prefix) repaired.push(prefix, '');

            tableText.split(/\r?\n/).forEach((rawRow) => {
                const row = rawRow.trimEnd();
                if (!row) return;
                if (!row.trimStart().startsWith('|')) {
                    trailing.push(row.trim());
                    return;
                }

                const lastPipe = row.lastIndexOf('|');
                if (lastPipe <= 0) {
                    repaired.push(row);
                    return;
                }

                const core = row.slice(0, lastPipe + 1).trimEnd();
                const suffix = row.slice(lastPipe + 1).trim();
                if (core) repaired.push(core);
                if (suffix) trailing.push(suffix);
            });

            if (trailing.length) repaired.push('', ...trailing);
            return repaired.length ? repaired : [line];
        }

        function normalizeInlineMarkdownTables(markdown) {
            return applyOutsideFencedBlocks(markdown || '', (chunk) => {
                const output = [];
                chunk.split(/\r?\n/).forEach((line) => {
                    if (looksLikeFlattenedTable(line)) {
                        output.push(...repairFlattenedTableLine(line));
                    } else {
                        output.push(line);
                    }
                });
                return output.join('\n');
            });
        }

        function normalizeMermaidCodeBlock(code) {
            const raw = (code || '').trim();
            if (!raw) return raw;

            let body = raw.replace(/%%\{init:[\s\S]*?\}%%/gi, ' ').replace(/[ \t]+/g, ' ').trim();
            body = body.replace(/\b((?:flowchart|graph)\s+(?:TB|TD|BT|RL|LR))\s+(?=\S)/i, '$1\n    ');
            body = body.replace(/\b(sequenceDiagram|stateDiagram-v2|stateDiagram|classDiagram|erDiagram|journey|gantt|pie)\s+(?=\S)/i, '$1\n    ');
            body = body.replace(/((?:[\]\)\}]|\b[A-Za-z][A-Za-z0-9_]*))\s+(?=[A-Za-z][A-Za-z0-9_]*\s*(?:-->|---|-.->|==>|--|==))/g, '$1\n    ');

            const lines = [];
            body.split(/\r?\n/).forEach((line) => {
                const cleaned = line.trim();
                if (!cleaned) return;
                const isDeclaration = /^(flowchart|graph|sequenceDiagram|stateDiagram|classDiagram|erDiagram|journey|gantt|pie)\b/i.test(cleaned);
                if (lines.length && !isDeclaration && !cleaned.startsWith('%%{')) {
                    lines.push(`    ${cleaned}`);
                } else {
                    lines.push(cleaned);
                }
            });

            return lines.join('\n').trim();
        }

        function normalizeInlineMermaidFences(markdown) {
            const repaired = repairBrokenMermaidFences(markdown || '');
            const normalized = repaired.replace(/```mermaid\s+([\s\S]*?)```/gi, (_match, body) => {
                const code = normalizeMermaidCodeBlock(body);
                return `\n\`\`\`mermaid\n${code}\n\`\`\`\n`;
            });
            return normalized.replace(/([^\n])([ \t]*```mermaid)/gi, '$1\n\n```mermaid');
        }

        function repairBrokenMermaidFences(markdown) {
            let text = String(markdown || '');
            text = text.replace(/([^\n])([ \t]*```mermaid)/gi, '$1\n\n```mermaid');
            text = closeBrokenMermaidFences(text);
            text = text.replace(
                /\s*<p\b[^>]*text-align\s*:\s*center[^>]*>([\s\S]*?)<\/p>\s*(?:<\/div>\s*)*/gi,
                (_match, caption) => `\n\n*${stripHtmlTags(caption).trim()}*\n\n`
            );
            text = text.replace(/\n\s*```\s*\n(?=\s*(?:#{1,6}\s+|\*\*(?:Контекст|Пример|Вопросы|Практика|Ожидаемый|Критерии|Ситуация|Ограничение|Входные данные|Цель|Подход)\b))/gi, '\n\n');
            text = text.replace(/<\/div>\s*<\/div>/gi, '');
            return text;
        }

        function closeBrokenMermaidFences(markdown) {
            const lines = String(markdown || '').replace(/\r\n/g, '\n').split('\n');
            const output = [];
            let inFence = false;
            let fenceLanguage = '';

            const isSectionBoundary = (line) => (
                /^\s*#{1,6}\s+/.test(line)
                || /^\s*\*\*(?:Контекст|Пример|Вопросы|Практика|Ожидаемый|Критерии|Ситуация|Ограничение|Входные данные|Цель|Подход)\b/i.test(line)
                || /^\s*<p\b[^>]*text-align\s*:\s*center/i.test(line)
            );

            for (let index = 0; index < lines.length; index += 1) {
                const line = lines[index];
                const trimmed = line.trim();
                const fenceMatch = /^```([^\s`]*)/.exec(trimmed);

                if (inFence) {
                    if (trimmed === '```') {
                        output.push('```');
                        inFence = false;
                        fenceLanguage = '';
                        continue;
                    }
                    if (fenceLanguage === 'mermaid' && isSectionBoundary(line)) {
                        output.push('```');
                        inFence = false;
                        fenceLanguage = '';
                    } else {
                        output.push(line);
                        continue;
                    }
                }

                if (fenceMatch) {
                    const nextLine = lines[index + 1] || '';
                    const previousNonEmpty = [...output].reverse().find(item => item.trim()) || '';
                    const isLikelyOrphanClosing = !fenceMatch[1] && (isSectionBoundary(nextLine) || /^\*.+\*$/.test(previousNonEmpty.trim()));
                    if (isLikelyOrphanClosing) {
                        continue;
                    }
                    inFence = true;
                    fenceLanguage = String(fenceMatch[1] || '').toLowerCase();
                    output.push(fenceLanguage === 'mermaid' ? '```mermaid' : line);
                    continue;
                }

                output.push(line);
            }

            if (inFence) {
                output.push('```');
            }
            return output.join('\n');
        }

        function stripHtmlTags(value) {
            return String(value || '').replace(/<[^>]+>/g, '');
        }

        function normalizeExampleBlocks(markdown) {
            return applyOutsideFencedBlocks(markdown || '', (chunk) => {
                let text = chunk.replace(/(^|[\s([{>])Пример\s*:/gim, '$1**Пример:**');
                text = text.replace(/\n{1,2}\s*\*\*Пример:\*\*/gi, '\n\n**Пример:**');
                text = text.replace(/([^\n])\s+\*\*Пример:\*\*/gi, '$1\n\n**Пример:**');
                return text;
            });
        }

        function normalizeStaticInstructionMarkdown(markdown) {
            const blockNames = [
                'Контекст и ограничения проекта',
                'Как учиться в проекте',
                'Как работать с проектом',
                'Дисклеймер'
            ];
            let text = markdown || '';
            text = text.replace(
                /(Эта инструкция задаёт \*\*общие правила работы с проектом\*\* и \*\*не описывает конкретные шаги по решению задач\*\*\.)\s*/i,
                '$1\n\n'
            );
            blockNames.forEach((name) => {
                const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
                const rx = new RegExp(`\\s*(\\*\\*${escaped}\\*\\*)\\s*`, 'gi');
                text = text.replace(rx, '\n\n$1\n\n');
            });
            text = text.replace(/\s+(—\s+\*\*[^*]+:\*\*)/g, '\n\n$1');
            text = text.replace(/(\.\s+)(?=—\s+\*\*)/g, '.\n\n');
            text = text.replace(/\n{3,}/g, '\n\n');
            return text.trim();
        }

        function normalizeMarkdownForDisplay(markdown) {
            let normalized = markdown || '';
            normalized = normalizeStaticInstructionMarkdown(normalized);
            normalized = normalizeInlineMermaidFences(normalized);
            normalized = normalizeInlineMarkdownTables(normalized);
            normalized = normalizeExampleBlocks(normalized);
            return normalized;
        }

        function scheduleFormulaCheck(root) {
            setTimeout(() => {
                if (!root) return;
                const leftover = root.innerHTML.includes('FORMULABLOCK') || root.innerHTML.includes('FORMULAINLINE');
                if (leftover) {
                    console.warn('[MathJax] Обнаружены незамененные плейсхолдеры формул.');
                }
                const rawLatex = root.textContent && /\$\$[^$]+\$\$/.test(root.textContent);
                if (rawLatex) {
                    console.warn('[MathJax] Формулы отображаются как сырые $$...$$. Проверить загрузку MathJax.');
                }
            }, 50);
        }

        // Обработка ошибок JavaScript

function displayMarkdown(markdown, containerId) {
            const container = document.getElementById(containerId);
            if (!container) {
                console.error('[displayMarkdown] Контейнер не найден:', containerId);
                return;
            }

            renderMarkdownPreview(container, markdown);
        }

        function renderMarkdownPreview(container, markdown, options = {}) {
            if (!container) {
                console.error('[renderMarkdownPreview] Контейнер не передан');
                return;
            }

            if (!markdown || typeof markdown !== 'string') {
                container.innerHTML = `<div class="info-box">${options.emptyMessage || 'Контент отсутствует'}</div>`;
                return;
            }

            // 0. Чистим старые плейсхолдеры формул, если они были сохранены в тексте
            // (артефакты вида FORMULA_BLOCK_5 / FORMULA_INLINE_2 из предыдущих версий пайплайна)
            markdown = markdown.replace(/FORMULA_(?:BLOCK|INLINE)_\d+/g, '').trim();
            markdown = normalizeMarkdownForDisplay(markdown);

            // 1. Защищаем формулы от обработки marked.js
            const formulaGuards = protectFormulas(markdown);
            let protectedMarkdown = formulaGuards.markdown;

            // 2. Парсим markdown в HTML
            if (typeof marked === 'undefined') {
                console.error('[displayMarkdown] marked.js не загружен');
                if (window.sanitize) {
                    window.sanitize.safeSetErrorMessage(container, 'Ошибка: библиотека marked.js не загружена');
                } else {
                    container.textContent = 'Ошибка: библиотека marked.js не загружена';
                }
                return;
            }

            let html = marked.parse(protectedMarkdown);

            html = restoreFormulas(html, formulaGuards);

            // 3. Вставляем HTML в контейнер (с санитизацией)
            if (window.sanitize) {
                window.sanitize.safeSetMarkdownHTML(container, html);
            } else {
                container.innerHTML = html;
            }
            normalizeRenderedTaskLists(container);

            // 3.1. Чистим артефакты Markdown-таблиц вида "| Точность (Precision) |"
            // которые приходят как обычные параграфы после парсинга.
            const paras = container.querySelectorAll('p');
            paras.forEach(p => {
                const text = p.textContent || '';
                const m = text.match(/^\s*\|\s*([^|]+?)\s*\|\s*$/);
                if (m) {
                    p.textContent = m[1].trim();
                }
            });

            // 4. Оборачиваем таблицы в "wrapper" с горизонтальной прокруткой
            wrapMarkdownTables(container);

            convertLatexLikeTableCells(container);

            // 5. Рендерим Mermaid-диаграммы
            renderMermaidDiagrams(container);
            wrapDiagramImages(container);

            // 6. Рендерим MathJax-формулы
            typesetMathJax(container);

            // 7. Подменяем локальные изображения для диаграмм, если они закодированы в ответе
            hydrateLocalImages(container, options);
            scheduleFormulaCheck(container);
        }

        function wrapMarkdownTables(root) {
            if (!root) return;
            const tables = root.querySelectorAll('table');
            tables.forEach(table => {
                let wrapper = table.parentElement?.classList.contains('table-wrapper')
                    ? table.parentElement
                    : null;
                if (!wrapper) {
                    wrapper = document.createElement('div');
                    wrapper.className = 'table-wrapper';
                    table.parentNode.insertBefore(wrapper, table);
                    wrapper.appendChild(table);
                }
                if (wrapper && !wrapper.nextElementSibling?.classList.contains('table-caption')) {
                    const captionText = extractTableCaption(wrapper.nextElementSibling);
                    if (captionText) {
                        const caption = document.createElement('div');
                        caption.className = 'table-caption';
                        caption.textContent = simplifyTableCaption(captionText);
                        wrapper.insertAdjacentElement('afterend', caption);
                    }
                }
            });
        }

        function normalizeRenderedTaskLists(root) {
            if (!root) return;
            root.querySelectorAll('li').forEach(item => {
                const firstMeaningfulChild = [...item.childNodes].find(child => (
                    child.nodeType !== Node.TEXT_NODE || String(child.textContent || '').trim()
                ));
                if (firstMeaningfulChild?.matches?.('input[type="checkbox"]')) {
                    item.classList.add('task-list-item');
                    item.parentElement?.classList.add('contains-task-list');
                    firstMeaningfulChild.disabled = true;
                }
            });
        }

        function convertLatexLikeTableCells(root) {
            if (!root) return;
            const cells = root.querySelectorAll('td, th');
            cells.forEach(cell => {
                if (!cell) return;
                const raw = cell.textContent ? cell.textContent.trim() : '';
                if (!raw || raw.length > 400) return;
                if (raw.includes('$') || raw.includes('$$')) return;
                const hasLatex =
                    /\\[a-zA-Z]+/.test(raw) ||
                    /[A-Za-z0-9]+\_[A-Za-z0-9]/.test(raw) ||
                    raw.includes('^') ||
                    raw.includes('{') ||
                    raw.includes('}');
                if (!hasLatex) return;
                // Сохраняем пробелы компактно
                const latex = raw.replace(/\s+/g, ' ').trim();
                cell.textContent = `$${latex}$`;
            });
        }

        /**
         * Ищет mermaid-блоки и рендерит их через mermaid.render.
         * Ожидается, что markdown размечен либо как ```mermaid, либо как ```mermaid\n...\n```.
         * Marked в таком случае сделает <pre><code class="language-mermaid">...</code></pre>.
         */
        function renderMermaidDiagrams(root) {
            if (typeof mermaid === 'undefined') {
                // Просто оставляем код как есть, без падения
                console.warn('[Mermaid] mermaid.js не загружен — диаграммы будут показаны как код');
                return;
            }

            // Ищем кодовые блоки с классом language-mermaid или mermaid
            const codeBlocks = root.querySelectorAll('pre code.language-mermaid, pre code.mermaid');
            if (!codeBlocks.length) return;

            codeBlocks.forEach((codeBlock, index) => {
                const pre = codeBlock.closest('pre');
                const code = normalizeMermaidCodeBlock(codeBlock.textContent.trim());
                if (!pre || !code) return;

                const figure = document.createElement('figure');
                figure.className = 'diagram-figure';

                const holder = document.createElement('div');
                holder.className = 'mermaid-diagram';

                pre.parentNode.replaceChild(figure, pre);
                figure.appendChild(holder);

                const captionText = extractDiagramCaption(figure.nextElementSibling);
                if (captionText) {
                    const caption = document.createElement('figcaption');
                    caption.className = 'diagram-caption';
                    caption.textContent = simplifyDiagramCaption(captionText);
                    figure.appendChild(caption);
                }

                const renderId = 'mermaid-' + Date.now() + '-' + index;

                // Без повторной initialize — предполагаем, что она уже была вызвана один раз где-то сверху
                mermaid
                    .render(renderId, code)
                    .then(res => {
                        // В новых версиях mermaid res уже объект { svg, bindFunctions }, в старых — просто svg-строка
                        const svg = typeof res === 'string' ? res : res.svg;
                        holder.innerHTML = svg;
                        
                        // Делаем svg адаптивным
                        const svgEl = holder.querySelector('svg');
                        if (svgEl) {
                            normalizeMermaidSvg(svgEl, holder);
                            centerMermaidLabels(svgEl);
                            svgEl.removeAttribute('height');
                            svgEl.removeAttribute('width');
                            svgEl.setAttribute('preserveAspectRatio', 'xMidYMid meet');
                            svgEl.style.width = 'var(--diagram-width, auto)';
                            svgEl.style.maxWidth = holder.dataset.diagramOverflow === 'scroll' ? 'none' : '100%';
                            svgEl.style.height = 'auto';
                            svgEl.style.margin = '0 auto';
                            svgEl.style.display = 'block';
                            holder.classList.add('mermaid-ready');
                            centerScrollableMermaid(holder);
                        }
                    })
                    .catch(err => {
                        console.error('[Mermaid] Ошибка рендеринга диаграммы:', err);
                        holder.innerHTML =
                            '<div class="error-msg">Ошибка отображения диаграммы: ' +
                            (err.message || 'Неизвестная ошибка') +
                            '</div>';
                    });
            });
        }

        function wrapDiagramImages(root) {
            if (!root) return;
            const images = root.querySelectorAll('img');
            images.forEach(img => {
                if (img.closest('figure.diagram-figure')) return;
                const src = img.getAttribute('src') || '';
                const alt = img.getAttribute('alt') || '';
                const isGeneratedDiagram = /^images\/diagram_\d+\.png(?:[?#].*)?$/i.test(src)
                    || /^data:image\/png;base64,/i.test(src) && /^диаграмма\b/i.test(alt)
                    || /^диаграмма\b/i.test(alt);
                if (!isGeneratedDiagram || !img.parentNode) return;

                const figure = document.createElement('figure');
                figure.className = 'diagram-figure';
                const surface = document.createElement('div');
                surface.className = 'diagram-image-surface';
                const host = img.parentElement;
                const imageOnlyParagraph = host?.tagName === 'P'
                    && [...host.childNodes].every(node => node === img || !String(node.textContent || '').trim());
                if (imageOnlyParagraph && host.parentNode) {
                    host.parentNode.insertBefore(figure, host);
                } else {
                    img.parentNode.insertBefore(figure, img);
                }
                surface.appendChild(img);
                figure.appendChild(surface);
                if (imageOnlyParagraph) {
                    host.remove();
                }

                const captionText = extractDiagramCaption(figure.nextElementSibling) || alt;
                if (captionText) {
                    const caption = document.createElement('figcaption');
                    caption.className = 'diagram-caption';
                    caption.textContent = simplifyDiagramCaption(captionText);
                    figure.appendChild(caption);
                }
            });
        }

        function simplifyDiagramCaption(text) {
            const cleaned = String(text || '')
                .replace(/\s+/g, ' ')
                .replace(/^(рис\.?\s*\d*|схема|диаграмма|процесс|алгоритм|таблица)\s*[:.—-]?\s*/i, '')
                .trim();
            const firstSentence = cleaned.split(/(?<=[.!?])\s+/)[0] || cleaned;
            if (firstSentence.length <= 72) return firstSentence;
            return `${firstSentence.slice(0, 69).replace(/\s+\S*$/, '').trim()}...`;
        }

        function extractDiagramCaption(nextElement) {
            return extractDisplayCaption(nextElement, {
                prefixRegex: /^(рис\.?|схема|диаграмма|процесс|алгоритм|таблица)\b/i,
                allowLeadingEmphasis: true
            });
        }

        function extractTableCaption(nextElement) {
            return extractDisplayCaption(nextElement, {
                prefixRegex: /^(табл\.?|таблица)\b/i,
                allowLeadingEmphasis: true
            });
        }

        function simplifyTableCaption(text) {
            const cleaned = String(text || '')
                .replace(/\s+/g, ' ')
                .replace(/^(таблица\s*\d*|табл\.?\s*\d*)\s*[:.—-]?\s*/i, '')
                .trim();
            if (cleaned.length <= 96) return cleaned;
            return `${cleaned.slice(0, 93).replace(/\s+\S*$/, '').trim()}...`;
        }

        function extractDisplayCaption(nextElement, options = {}) {
            if (!nextElement || nextElement.tagName !== 'P') return '';

            const prefixRegex = options.prefixRegex || /^$/;
            const allowLeadingEmphasis = !!options.allowLeadingEmphasis;
            const nextText = (nextElement.textContent || '').trim();
            const firstMeaningfulChild = [...nextElement.childNodes].find(node => (
                node.nodeType !== Node.TEXT_NODE || String(node.textContent || '').trim()
            ));
            const firstElement = firstMeaningfulChild?.nodeType === Node.ELEMENT_NODE
                ? firstMeaningfulChild
                : null;
            const hasOnlyEm = nextElement.children.length === 1 && nextElement.firstElementChild?.tagName === 'EM';
            const looksLikeCaption = prefixRegex.test(nextText) || hasOnlyEm;

            if (looksLikeCaption) {
                nextElement.remove();
                return nextText;
            }

            if (allowLeadingEmphasis && firstElement?.tagName === 'EM') {
                const captionText = (firstElement.textContent || '').trim();
                firstElement.remove();
                trimLeadingText(nextElement);
                if (!(nextElement.textContent || '').trim()) {
                    nextElement.remove();
                }
                return captionText;
            }

            return '';
        }

        function trimLeadingText(element) {
            while (element.firstChild) {
                const node = element.firstChild;
                if (node.nodeType !== Node.TEXT_NODE) break;
                const cleaned = String(node.textContent || '').replace(/^[\s:—-]+/, '');
                if (cleaned) {
                    node.textContent = cleaned;
                    break;
                }
                node.remove();
            }
        }

        function normalizeMermaidSvg(svgEl, holder) {
            if (!svgEl || !holder) return;
            const viewBox = svgEl.getAttribute('viewBox');
            const rawWidth = parseFloat(svgEl.getAttribute('width') || '');
            const rawHeight = parseFloat(svgEl.getAttribute('height') || '');

            if (!viewBox && rawWidth && rawHeight) {
                svgEl.setAttribute('viewBox', `0 0 ${rawWidth} ${rawHeight}`);
            }

            const vb = svgEl.viewBox && svgEl.viewBox.baseVal;
            const width = vb && vb.width ? vb.width : rawWidth;
            const height = vb && vb.height ? vb.height : rawHeight;
            const naturalWidth = Math.max(260, Math.min(width || 720, 1320));
            const naturalHeight = Math.max(180, Math.min(height || 520, 2200));
            const aspectRatio = naturalHeight / Math.max(naturalWidth, 1);
            const isWide = naturalWidth > 980;
            const isTall = aspectRatio > 1.15 || naturalHeight > 900;
            const renderWidth = isWide ? Math.min(naturalWidth, 1320) : (isTall ? 680 : 760);
            const boxWidth = 860;

            holder.style.setProperty('--diagram-width', `${Math.round(renderWidth)}px`);
            holder.style.setProperty('--diagram-box-width', `${Math.round(boxWidth)}px`);
            holder.dataset.diagramOverflow = isWide ? 'scroll' : 'fit';

            if (isWide) {
                holder.dataset.diagramSize = 'wide';
            } else if (isTall) {
                holder.dataset.diagramSize = 'tall';
            } else if (naturalWidth < 560) {
                holder.dataset.diagramSize = 'compact';
            } else {
                holder.dataset.diagramSize = 'normal';
            }
        }

        function centerScrollableMermaid(holder) {
            if (!holder) return;
            window.requestAnimationFrame(() => {
                if (holder.scrollWidth > holder.clientWidth) {
                    holder.scrollLeft = Math.max(0, (holder.scrollWidth - holder.clientWidth) / 2);
                }
            });
        }

        function centerMermaidLabels(svgEl) {
            if (!svgEl) return;

            const labelNodes = svgEl.querySelectorAll(
                '.nodeLabel, .edgeLabel, .label, foreignObject div, foreignObject span'
            );
            labelNodes.forEach(label => {
                label.style.textAlign = 'center';
                label.style.lineHeight = '1.32';
                label.style.whiteSpace = 'normal';
            });
        }

        function hydrateLocalImages(root, options = {}) {
            const result = options.currentResult || window.currentResult || window.__contentGenCurrentResult || null;
            if (!root || !result || !result.assets) {
                return;
            }
            const assets = result.assets;
            const map = new Map();

            const images = Array.isArray(assets.images) ? assets.images : [];
            images.forEach(img => {
                if (img && img.name && img.data) {
                    map.set(img.name, img.data);
                }
            });

            const files = Array.isArray(assets.files) ? assets.files : [];
            files.forEach(file => {
                const path = file && (file.path || file.name);
                if (!path || !file.data) {
                    return;
                }
                const name = path.split('/').pop();
                if (name && !map.has(name)) {
                    map.set(name, file.data);
                }
            });

            if (!map.size) {
                return;
            }

            const imgNodes = root.querySelectorAll('img');
            imgNodes.forEach(img => {
                const src = img.getAttribute('src');
                if (!src || !src.startsWith('images/')) {
                    return;
                }
                const name = src.split('/').pop();
                const base64 = map.get(name);
                if (base64) {
                    img.src = `data:image/png;base64,${base64}`;
                }
            });
        }

        function normalizeMathBlocks(root) {
            if (!root) return;
            const blocks = root.querySelectorAll('mjx-container[display="block"], .MathJax_Display, .MathJax_SVG_Display');
            if (!blocks.length) return;
            blocks.forEach(block => {
                if (!block) {
                    return;
                }
                const parent = block.parentElement;
                const wrapperClass = 'math-center-wrapper';

                const isAlreadyWrapped = parent && parent.classList.contains(wrapperClass);
                if (!isAlreadyWrapped) {
                    const wrapper = document.createElement('div');
                    wrapper.classList.add(wrapperClass);

                    const canReplaceParent = parent &&
                        parent.parentNode &&
                        Array.from(parent.childNodes).every(node => {
                            if (node === block) return true;
                            if (node.nodeType === Node.TEXT_NODE) {
                                return !node.textContent.trim();
                            }
                            return false;
                        });

                    if (canReplaceParent) {
                        parent.parentNode.insertBefore(wrapper, parent);
                        wrapper.appendChild(block);
                        parent.remove();
                    } else if (parent) {
                        parent.insertBefore(wrapper, block);
                        wrapper.appendChild(block);
                    } else {
                        root.appendChild(wrapper);
                        wrapper.appendChild(block);
                    }
                }

                const host = block.parentElement;
                if (host) {
                    host.classList.add(wrapperClass);
                }

                block.classList.add('math-display-block');
                block.style.setProperty('text-align', 'center', 'important');
                block.style.setProperty('justify-content', 'center', 'important');
                block.style.setProperty('display', 'flex', 'important');
                block.style.setProperty('margin', '0 auto', 'important');
                block.style.setProperty('width', '100%', 'important');
                const svg = block.querySelector('svg');
                if (svg) {
                    svg.style.setProperty('margin', '0 auto', 'important');
                    svg.style.setProperty('max-width', '100%', 'important');
                    svg.style.setProperty('height', 'auto', 'important');
                }
            });
        }

        /**
         * Вызывает MathJax для заданного контейнера.
         * Ориентируемся на MathJax v3 (typesetPromise), с fallback на typeset.
         * Дожидается загрузки MathJax, если он еще не готов.
         */
        function typesetMathJax(root) {
            if (!root) return;

            const waitForMathJax = resolve => {
                if (window.MathJax && window.MathJax.startup && window.MathJax.startup.promise) {
                    window.MathJax.startup.promise.then(() => resolve()).catch(resolve);
                    return;
                }
                if (window.MathJax) {
                    resolve();
                    return;
                }
                setTimeout(() => waitForMathJax(resolve), 100);
            };

            new Promise(waitForMathJax)
                .then(() => {
                    const mj = window.MathJax;
                    if (!mj) return;
                    if (typeof mj.typesetPromise === 'function') {
                        return mj.typesetPromise([root]);
                    }
                    if (typeof mj.typeset === 'function') {
                        mj.typeset([root]);
                    }
                })
                .catch(err => {
                    console.error('[MathJax] Ошибка обработки формул:', err);
                })
                .finally(() => {
                    normalizeMathBlocks(root);
                });
        }

        if (typeof window !== 'undefined') {
            window.ContentGenMarkdownRendering = {
                displayMarkdown,
                renderMarkdownPreview,
                normalizeMarkdownForDisplay,
                renderMermaidDiagrams,
                wrapMarkdownTables,
                normalizeRenderedTaskLists,
                convertLatexLikeTableCells,
                normalizeMermaidCodeBlock,
                normalizeInlineMermaidFences,
                repairBrokenMermaidFences,
                closeBrokenMermaidFences,
                scheduleFormulaCheck,
                hydrateLocalImages,
                normalizeMathBlocks,
                typesetMathJax,
            };

            Object.assign(window, {
                byId,
                getChecked,
                setChecked,
                setValue,
                normalizeAudienceLevel,
                setAudienceLevel,
                splitCommaList,
                setDisplay,
                displayMarkdown,
                renderMarkdownPreview,
                normalizeMarkdownForDisplay,
                renderMermaidDiagrams,
            });
        }

