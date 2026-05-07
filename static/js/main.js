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
        window.addEventListener('error', function(e) {
            console.error('JavaScript ошибка:', e.error, e.message, e.filename, e.lineno);
            
            // Если ошибка связана с markdown, показываем её в UI
            if (e.message && (e.message.includes('markdown') || e.message.includes('Cannot read properties'))) {
                const logContent = document.getElementById('logContent');
                if (logContent) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(logContent, `Ошибка: ${e.message}. Проверьте консоль браузера (F12) для подробностей.`);
                    } else {
                        logContent.textContent = `❌ Ошибка: ${e.message}. Проверьте консоль браузера (F12) для подробностей.`;
                    }
                }
                const generationLogs = document.getElementById('generationLogs');
                if (generationLogs) {
                    generationLogs.style.display = 'block';
                }
            }
        });
        
        // Обработка необработанных промисов
        window.addEventListener('unhandledrejection', function(e) {
            console.error('Необработанная ошибка промиса:', e.reason);
            
            // Если ошибка связана с markdown, показываем её в UI
            const errorMsg = e.reason?.message || String(e.reason);
            if (errorMsg && (errorMsg.includes('markdown') || errorMsg.includes('Cannot read properties'))) {
                const logContent = document.getElementById('logContent');
                if (logContent) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(logContent, `Ошибка: ${errorMsg}. Проверьте консоль браузера (F12) для подробностей.`);
                    } else {
                        logContent.textContent = `❌ Ошибка: ${errorMsg}. Проверьте консоль браузера (F12) для подробностей.`;
                    }
                }
                const generationLogs = document.getElementById('generationLogs');
                if (generationLogs) {
                    generationLogs.style.display = 'block';
                }
            }
        });
        
        // Оборачиваем весь код в IIFE, чтобы можно было использовать return
        (function() {
            const API_BASE = window.location.origin;
            const API_URL = `${API_BASE}/api/v1`;
            const REGENERATION_TEMPLATE = 'Примени точечно правки к документу по пунктам ниже не нарушая его структуру и стиль.';
            
            // Проверка аутентификации
            const authToken = localStorage.getItem('auth_token');
            if (!authToken) {
                console.log('Токен не найден, перенаправление на страницу входа');
                window.location.replace('/');
                return; // Теперь return работает, так как мы внутри функции
            }
            
            console.log('Скрипт инициализирован, API_URL:', API_URL);
        
        // Настраиваем marked.js для поддержки GFM таблиц (вызываем один раз при загрузке)
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                gfm: true,
                breaks: true,
                tables: true
            });
        }
        
        // Функция для добавления токена в заголовки запросов
        function getAuthHeaders() {
            const token = localStorage.getItem('auth_token');
            return {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            };
        }
        
        
        let currentRequestId = null;
        let currentMarkdown = null;
        let originalMarkdown = null; // Сохраняем оригинальный markdown отдельно
        let currentTranslatedMarkdown = null; // Сохраняем переведенный markdown
        let currentResult = null;
        let currentFilter = 'all'; // 'all', 'passed', 'failed'
        window.currentFilter = 'all'; // Глобальная копия для фильтра
        let currentSeed = null;
        let generationTimer = null;
        let generationStartTime = null;
        let agentPollInterval = null; // Сохраняем данные формы для восстановления
        let lastKnownGenerationPhase = null;
        let lastKnownGenerationProgress = 0;
        let lastKnownGenerationAgent = 'Инициализация...';

        window.methodologyPanel?.configure({
            apiUrl: API_URL,
            getAuthHeaders,
            getCurrentRequestId: () => currentRequestId,
            onApproved: (requestId) => {
                showCompactGenerationProgress('Генерация проекта продолжается...', {
                    progress: Math.max(lastKnownGenerationProgress || 0, 1),
                    agent: lastKnownGenerationAgent || 'Продолжение генерации'
                });
                const cancelBtn = document.getElementById('cancelGenerationBtn');
                if (cancelBtn) {
                    cancelBtn.style.setProperty('display', 'block', 'important');
                    cancelBtn.disabled = false;
                }
                const btn = document.getElementById('generateBtn');
                if (btn) {
                    btn.disabled = true;
                    btn.textContent = '⏳ Генерация...';
                }
                startTimer();
                pollGenerationStatus(requestId);
            },
            onDiffApproved: (_requestId, reviewState) => {
                applyAcceptedMethodologyPreview(reviewState);
            },
            onRejected: (_requestId, comment) => {
                stopGenerationTracking();
                hideCancelButton();
                const logContent = document.getElementById('logContent');
                if (logContent) {
                    const text = comment
                        ? `Генерация остановлена методологом: ${comment}`
                        : 'Генерация остановлена методологом.';
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(logContent, text);
                    } else {
                        logContent.textContent = text;
                    }
                }
                const btn = document.getElementById('generateBtn');
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🚀 Сгенерировать';
                }
                const noResults = document.getElementById('noResults');
                const resultsArea = document.getElementById('resultsArea');
                if (!currentResult && noResults && resultsArea?.style.display === 'none') {
                    noResults.style.display = 'block';
                }
            },
            onChangeRequested: (_requestId, payload) => {
                const logContent = document.getElementById('logContent');
                if (logContent) {
                    const text = `Методолог запросил правки: ${payload.instruction}`;
                    if (window.sanitize) {
                        window.sanitize.safeSetHTML(logContent, `<div class="info-box">${window.sanitize.escapeHtml(text)}</div>`);
                    } else {
                        logContent.textContent = text;
                    }
                }
            },
            onError: (message) => {
                if (window.toast) {
                    window.toast.error(message);
                }
            }
        });
        
        // Сохраняем оригинальные метрики и отчет для переключения
        let originalRubric = null;
        let originalTextStats = null;
        let regeneratedRubric = null;
        let regeneratedTextStats = null;
        let currentMetricsVersion = 'original'; // 'original' или 'regenerated'
        let currentReportVersion = 'original'; // 'original' или 'regenerated'

        function applyAcceptedMethodologyPreview(reviewState) {
            const markdown = reviewState?.preview_markdown
                || reviewState?.result?.markdown
                || reviewState?.markdown
                || '';
            if (!markdown || typeof markdown !== 'string') {
                return;
            }

            currentMarkdown = markdown;
            if (!originalMarkdown) {
                originalMarkdown = markdown;
            }
            currentResult = {
                ...(currentResult || {}),
                markdown
            };

            const readmeContainer = document.getElementById('readmeContent');
            if (readmeContainer) {
                displayMarkdown(markdown, 'readmeContent');
            }

            const previewContainer = document.getElementById('readmePreview');
            if (previewContainer) {
                displayMarkdown(markdown, 'readmePreview');
            }

            saveGenerationState();
        }
        
        // Функции для работы с sessionStorage
        function saveGenerationState() {
            try {
                const state = {
                    requestId: currentRequestId,
                    markdown: currentMarkdown,
                    originalMarkdown: originalMarkdown, // Сохраняем оригинальный markdown
                    result: currentResult,
                    seed: currentSeed,
                    originalRubric: originalRubric, // Сохраняем оригинальные метрики
                    originalTextStats: originalTextStats, // Сохраняем оригинальную статистику
                    regeneratedRubric: regeneratedRubric,
                    regeneratedTextStats: regeneratedTextStats,
                    regeneratedMarkdown: window.regeneratedMarkdown || null, // Сохраняем перегенерированный markdown
                    generationStartTime: generationStartTime, // Сохраняем время начала генерации
                    lastKnownGenerationPhase,
                    lastKnownGenerationProgress,
                    lastKnownGenerationAgent,
                    timestamp: Date.now()
                };
                sessionStorage.setItem('generation_state', JSON.stringify(state));
                console.log('✅ Состояние генерации сохранено в sessionStorage', {
                    hasOriginalRubric: !!originalRubric,
                    hasRegeneratedRubric: !!regeneratedRubric,
                    hasOriginalTextStats: !!originalTextStats,
                    hasRegeneratedTextStats: !!regeneratedTextStats
                });
            } catch (error) {
                console.error('❌ Ошибка сохранения состояния:', error);
            }
        }
        
        async function loadGenerationState() {
            try {
                const saved = sessionStorage.getItem('generation_state');
                if (saved) {
                    const state = JSON.parse(saved);
                    // Проверяем, что данные не слишком старые (например, не старше 24 часов)
                    const maxAge = 24 * 60 * 60 * 1000; // 24 часа
                    if (state.timestamp && (Date.now() - state.timestamp) < maxAge) {
                        currentRequestId = state.requestId;
                        currentMarkdown = state.markdown;
                        originalMarkdown = state.originalMarkdown || null; // Восстанавливаем оригинальный markdown
                        currentResult = state.result;
                        currentSeed = state.seed;
                        
                        // Восстанавливаем время начала генерации
                        if (state.generationStartTime) {
                            generationStartTime = state.generationStartTime;
                        }
                        lastKnownGenerationPhase = state.lastKnownGenerationPhase || lastKnownGenerationPhase;
                        lastKnownGenerationProgress = Number(state.lastKnownGenerationProgress || 0);
                        lastKnownGenerationAgent = state.lastKnownGenerationAgent || lastKnownGenerationAgent;
                        
                        // Если есть requestId, проверяем статус генерации на сервере
                        if (currentRequestId) {
                            try {
                                const response = await fetch(`${API_URL}/generate/status/${currentRequestId}`, {
                                    headers: getAuthHeaders()
                                });
                                
                                if (response.ok) {
                                    const statusData = await response.json();
                                    const status = statusData.status;
                                    
                                    if (status === 'pending' || status === 'in_progress') {
                                        // Генерация еще идет - возобновляем polling и таймер
                                        console.log('🔄 Генерация еще идет, возобновляем polling...');
                                        
                                        // Показываем область логов
                                        const generationLogs = document.getElementById('generationLogs');
                                        if (generationLogs) {
                                            generationLogs.style.display = 'block';
                                        }
                                        showCompactGenerationProgress('Генерация проекта продолжается...', {
                                            progress: Math.max(lastKnownGenerationProgress || 0, 1),
                                            agent: lastKnownGenerationAgent || 'Продолжение генерации'
                                        });
                                        
                                        // Запускаем таймер
                                        startTimer();
                                        
                                        // Начинаем polling
                                        pollGenerationStatus(currentRequestId);
                                        
                                        // Блокируем кнопку генерации
                                        const btn = document.getElementById('generateBtn');
                                        if (btn) {
                                            btn.disabled = true;
                                            btn.textContent = '⏳ Генерация...';
                                        }
                                        
                                        return true; // Не продолжаем восстановление UI, так как генерация еще идет
                                    } else if (status === 'failed') {
                                        // Генерация завершилась с ошибкой
                                        console.log('❌ Генерация завершилась с ошибкой');
                                        const errorMsg = statusData.error || 'Неизвестная ошибка';
                                        const logContent = document.getElementById('logContent');
                                        if (logContent) {
                                            if (window.sanitize) {
                                                window.sanitize.safeSetErrorMessage(logContent, `Ошибка генерации: ${errorMsg}`);
                                            } else {
                                                logContent.textContent = `❌ Ошибка генерации: ${errorMsg}`;
                                            }
                                        }
                                        clearGenerationState();
                                        return false;
                                    } else if (status === 'completed') {
                                        // Генерация завершена - загружаем результат
                                        console.log('✅ Генерация завершена, загружаем результат...');
                                        if (statusData.result) {
                                            currentResult = statusData.result;
                                            currentMarkdown = statusData.result?.markdown || '';
                                            originalMarkdown = currentMarkdown;
                                            
                                            // Извлекаем originalRubric и originalTextStats из результата
                                            if (statusData.result.rubric && !state.originalRubric) {
                                                originalRubric = statusData.result.rubric;
                                                window.currentRubric = statusData.result.rubric;
                                            }
                                            if (statusData.result.text_stats && !state.originalTextStats) {
                                                originalTextStats = statusData.result.text_stats;
                                            }
                                            
                                            // Сохраняем обновленное состояние
                                            saveGenerationState();
                                            
                                            // Продолжаем восстановление UI ниже
                                        } else {
                                            // Результат не найден
                                            console.warn('⚠️ Результат генерации не найден');
                                            clearGenerationState();
                                            return false;
                                        }
                                    }
                                } else if (response.status === 404) {
                                    // Запрос не найден - возможно истек срок
                                    console.log('⚠️ Запрос генерации не найден на сервере');
                                    clearGenerationState();
                                    return false;
                                }
                            } catch (error) {
                                console.error('❌ Ошибка при проверке статуса генерации:', error);
                                // Продолжаем восстановление из sessionStorage
                            }
                        }
                        
                        // Восстанавливаем оригинальные данные (приоритет - из сохраненного состояния)
                        if (state.originalRubric) {
                            originalRubric = state.originalRubric;
                            window.currentRubric = state.originalRubric;
                            console.log('✅ originalRubric восстановлен из sessionStorage:', originalRubric.items?.length || 0, 'критериев');
                        } else if (currentResult && currentResult.rubric) {
                            // Fallback: используем данные из currentResult
                            originalRubric = currentResult.rubric;
                            window.currentRubric = currentResult.rubric;
                            console.log('✅ originalRubric восстановлен из currentResult:', originalRubric.items?.length || 0, 'критериев');
                        }
                        
                        if (state.originalTextStats) {
                            originalTextStats = state.originalTextStats;
                            console.log('✅ originalTextStats восстановлен из sessionStorage');
                        } else if (currentResult && currentResult.text_stats) {
                            // Fallback: используем данные из currentResult
                            originalTextStats = currentResult.text_stats;
                            console.log('✅ originalTextStats восстановлен из currentResult');
                        }
                        
                        // Восстанавливаем перегенерированные данные, если они есть
                        if (state.regeneratedRubric) {
                            regeneratedRubric = state.regeneratedRubric;
                            window.regeneratedRubric = state.regeneratedRubric;
                            console.log('✅ regeneratedRubric восстановлен из sessionStorage:', regeneratedRubric.items?.length || 0, 'критериев');
                        }
                        if (state.regeneratedTextStats) {
                            regeneratedTextStats = state.regeneratedTextStats;
                            window.regeneratedTextStats = state.regeneratedTextStats;
                            console.log('✅ regeneratedTextStats восстановлен из sessionStorage');
                        }
                        if (state.regeneratedMarkdown) {
                            window.regeneratedMarkdown = state.regeneratedMarkdown;
                            console.log('✅ regeneratedMarkdown восстановлен из sessionStorage');
                        }
                        
                        // Восстанавливаем форму из seed, если есть
                        if (currentSeed) {
                            fillFormFromData(currentSeed);
                        }
                        
                        // Восстанавливаем UI - с проверкой структуры данных
                        if (currentResult && typeof currentResult === 'object') {
                            // Проверяем наличие markdown перед отображением
                            if (typeof currentResult.markdown !== 'string') {
                                console.warn('⚠️ currentResult не содержит markdown при восстановлении:', currentResult);
                                // Не отображаем результаты, если нет markdown
                                return false;
                            }
                            
                            // Создаем объект данных в формате, который ожидает displayResults
                            const restoredData = {
                                result: currentResult,
                                request_id: currentRequestId,
                                warnings: [] // Предупреждения не сохраняем, но это не критично
                            };
                            
                            // Вызываем displayResults с обработкой ошибок
                            try {
                            displayResults(restoredData);
                            } catch (displayError) {
                                console.error('❌ Ошибка при восстановлении отображения результатов:', displayError);
                                // Очищаем состояние, если не можем отобразить
                                clearGenerationState();
                                return false;
                            }
                            
                            // ВАЖНО: После восстановления нужно убедиться, что оригинальные данные отображены
                            // и переключатели правильно настроены
                            if (originalRubric) {
                                displayMetrics(originalRubric, 'metricsContentOriginal');
                                console.log('✅ Оригинальные метрики отображены после восстановления');
                            }
                            if (originalTextStats) {
                                displayReport({ text_stats: originalTextStats }, 'reportContentOriginal');
                                console.log('✅ Оригинальный отчет отображен после восстановления');
                            }
                            
                            // Если есть перегенерированные данные, отображаем их в соответствующих контейнерах
                            if (regeneratedRubric) {
                                displayMetrics(regeneratedRubric, 'metricsContentRegen');
                                console.log('✅ Перегенерированные метрики отображены после восстановления');
                            }
                            if (regeneratedTextStats) {
                                displayReport({ text_stats: regeneratedTextStats }, 'reportContentRegen');
                                console.log('✅ Перегенерированный отчет отображен после восстановления');
                            }
                            
                            // Обновляем переключатели после восстановления
                            updateVersionButtons();
                            
                            // Устанавливаем исходное состояние переключателей
                            if (originalRubric) {
                                switchMetricsVersion('original');
                            } else if (regeneratedRubric) {
                                switchMetricsVersion('regenerated');
                            }
                            
                            if (originalTextStats) {
                                switchReportVersion('original');
                            } else if (regeneratedTextStats) {
                                switchReportVersion('regenerated');
                            }
                        }
                        
                        // Восстанавливаем данные формы, если они есть
                        if (currentSeed) {
                            restoreFormData(currentSeed);
                        }
                        
                        console.log('✅ Состояние генерации восстановлено из sessionStorage');
                        return true;
                    } else {
                        // Данные слишком старые, очищаем
                        clearGenerationState();
                    }
                }
            } catch (error) {
                console.error('❌ Ошибка восстановления состояния:', error);
                clearGenerationState();
            }
            return false;
        }
        
        function clearGenerationState() {
            try {
                sessionStorage.removeItem('generation_state');
                currentRequestId = null;
                currentMarkdown = null;
                originalMarkdown = null;
                currentTranslatedMarkdown = null;
                currentResult = null;
                currentSeed = null;
                lastKnownGenerationPhase = null;
                lastKnownGenerationProgress = 0;
                lastKnownGenerationAgent = 'Инициализация...';
                console.log('✅ Состояние генерации очищено');
            } catch (error) {
                console.error('❌ Ошибка очистки состояния:', error);
            }
        }
        
        function restoreFormData(seed) {
            // Восстанавливаем значения полей формы
            if (seed.language) document.getElementById('language').value = seed.language;
            if (seed.project_type) document.getElementById('projectType').value = seed.project_type;
            if (seed.thematic_block) document.getElementById('thematicBlock').value = seed.thematic_block;
            if (seed.audience_level) document.getElementById('audienceLevel').value = seed.audience_level;
            if (seed.required_tools) document.getElementById('requiredTools').value = seed.required_tools.join(', ');
            if (seed.title_seed) document.getElementById('titleSeed').value = seed.title_seed;
            if (seed.project_description) document.getElementById('projectDescription').value = seed.project_description;
            if (seed.sjm) document.getElementById('storytelling').value = seed.sjm;
            if (seed.learning_outcomes) document.getElementById('learningOutcomes').value = seed.learning_outcomes.join('\n');
            if (seed.skills) document.getElementById('skills').value = seed.skills.join('\n');
            if (seed.group_size) document.getElementById('groupSize').value = seed.group_size;
            if (seed.repo_path_template) document.getElementById('repoPathTemplate').value = seed.repo_path_template;
            
            // Восстанавливаем чекбоксы
            setChecked('methodologyHumanReview', !!seed.methodology_human_review);
            if (seed.bonus_wish !== null && seed.bonus_wish !== undefined) {
                setChecked('generateBonus', true);
                setValue('bonusWish', seed.bonus_wish || '');
            }
            
        }
        // Направления (ранее thematicBlocks)
        let directions = {
            "Бизнес аналитика": "BSA",
            "Кибербезопасность": "Cb",
            "DevOps": "DO",
            "Проектный менеджмент": "PjM",
            "Тестирование и обеспечение качества": "QA",
            "Машинное обучение": "DS"
        };
        
        // Обратная совместимость: thematicBlocks = directions
        let thematicBlocks = directions;
        
        // === УЧЕБНЫЙ ПЛАН (УП) ===
        // Хранится только в текущей сессии (sessionStorage)
        let currentCurriculum = null;
        let currentCurriculumContext = null;
        
        /**
         * Обработка загрузки CSV файла учебного плана
         */
        async function handleCurriculumUpload(event) {
            const fileInput = event && event.target ? event.target : null;
            const file = fileInput && fileInput.files ? fileInput.files[0] : null;
            if (!file) return;
            
            document.getElementById('curriculumFileName').textContent = '⏳ Загрузка...';
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const token = localStorage.getItem('auth_token');
                const response = await fetch(`${API_URL}/curriculum/upload`, {
                    method: 'POST',
                    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
                    body: formData
                });
                
                if (!response.ok) {
                    const error = await response.json().catch(() => ({ detail: 'Ошибка загрузки' }));
                    throw new Error(error.detail || `Ошибка ${response.status}`);
                }
                
                currentCurriculum = await response.json();
                
                // Сохраняем в sessionStorage
                sessionStorage.setItem('curriculum_data', JSON.stringify(currentCurriculum));
                
                // Устанавливаем направление из УП
                const directionCode = currentCurriculum.direction_code;
                const directionSelect = document.getElementById('direction');
                if (directionSelect && directionCode && directionCode !== 'UNK') {
                    // Проверяем, есть ли такой код в списке
                    const hasOption = Array.from(directionSelect.options).some(opt => opt.value === directionCode);
                    if (hasOption) {
                        directionSelect.value = directionCode;
                    }
                }
                
                // Заполняем каскадный селектор блоков
                populateCurriculumBlocks();
                
                // Показываем каскадные селекторы
                document.getElementById('curriculumBlockGroup').style.display = 'block';
                
                document.getElementById('curriculumFileName').textContent = `✅ ${file.name} (${currentCurriculum.blocks.length} блоков)`;
                
                if (window.toast) {
                    window.toast.success(`УП загружен: ${currentCurriculum.direction} (${currentCurriculum.blocks.length} блоков)`);
                }
                
                console.log('✅ УП загружен:', currentCurriculum);
                
            } catch (error) {
                document.getElementById('curriculumFileName').textContent = `❌ Ошибка: ${error.message}`;
                console.error('❌ Ошибка загрузки УП:', error);
                if (window.toast) {
                    window.toast.error(`Ошибка загрузки УП: ${error.message}`);
                }
            }
        }
        
        /**
         * Заполняет селектор тематических блоков из УП
         */
        function populateCurriculumBlocks() {
            const select = document.getElementById('curriculumBlock');
            if (!select || !currentCurriculum) return;
            
            select.innerHTML = '<option value="">-- Выберите блок --</option>';
            
            for (const block of currentCurriculum.blocks) {
                const option = document.createElement('option');
                option.value = block.name;
                option.textContent = block.name;
                option.dataset.goals = JSON.stringify(block.goals || []);
                select.appendChild(option);
            }
        }
        
        /**
         * Обработка выбора тематического блока из УП
         */
        function onCurriculumBlockChange() {
            const blockName = document.getElementById('curriculumBlock').value;
            const projectGroup = document.getElementById('curriculumProjectGroup');
            const projectSelect = document.getElementById('curriculumProject');
            
            // Обновляем скрытое поле thematicBlock
            document.getElementById('thematicBlock').value = blockName;
            
            if (!blockName || !currentCurriculum) {
                projectGroup.style.display = 'none';
                return;
            }
            
            const block = currentCurriculum.blocks.find(b => b.name === blockName);
            if (!block) return;
            
            projectSelect.innerHTML = '<option value="">-- Выберите проект --</option>';
            
            for (const proj of block.projects) {
                const option = document.createElement('option');
                option.value = proj.order;
                option.textContent = `${proj.order}. ${proj.title}`;
                option.dataset.project = JSON.stringify(proj);
                projectSelect.appendChild(option);
            }
            
            projectGroup.style.display = 'block';
        }
        
        /**
         * Обработка выбора проекта из УП
         */
        function onCurriculumProjectChange() {
            const projectSelect = document.getElementById('curriculumProject');
            const selectedOption = projectSelect.selectedOptions[0];
            
            if (!selectedOption || !selectedOption.dataset.project) return;
            
            const project = JSON.parse(selectedOption.dataset.project);
            const blockName = document.getElementById('curriculumBlock').value;
            const block = currentCurriculum.blocks.find(b => b.name === blockName);
            
            if (!block) return;
            
            // === АВТОЗАПОЛНЕНИЕ ПОЛЕЙ ===
            
            // Название проекта
            document.getElementById('titleSeed').value = project.title || '';
            
            // Описание
            document.getElementById('projectDescription').value = project.description || '';
            
            // Образовательные результаты
            if (project.learning_outcomes && project.learning_outcomes.length > 0) {
                document.getElementById('learningOutcomes').value = project.learning_outcomes.join('\n');
            }
            
            // Получаемые навыки (из колонки "Список навыков" УП)
            const skillsEl = document.getElementById('skills');
            if (skillsEl) {
                skillsEl.value = (project.skills && project.skills.length > 0)
                    ? project.skills.join('\n')
                    : '';
            }

            // Уровень аудитории
            const audienceLevelEl = document.getElementById('audienceLevel');
            if (audienceLevelEl) {
                audienceLevelEl.value = project.audience_level || '';
            }
            
            // Обязательные инструменты: новая колонка УП имеет приоритет над legacy "Необходимое ПО/веб".
            const requiredToolsEl = document.getElementById('requiredTools');
            if (requiredToolsEl) {
                if (project.required_tools && project.required_tools.length > 0) {
                    requiredToolsEl.value = project.required_tools.join(', ');
                } else if (project.required_software) {
                    requiredToolsEl.value = project.required_software;
                } else {
                    requiredToolsEl.value = '';
                }
            }

            // Сторителлинг / SJM
            const storytellingEl = document.getElementById('storytelling');
            if (storytellingEl) {
                storytellingEl.value = project.sjm || '';
            }
            
            // Тип проекта
            if (project.format) {
                document.getElementById('projectType').value = project.format;
                toggleGroupSize();
            }
            
            // Размер группы
            if (project.group_size) {
                document.getElementById('groupSize').value = project.group_size;
            }
            
            // Направление
            if (block.code && block.code !== 'UNK') {
                document.getElementById('direction').value = block.code;
            }
            
            // === СТРОИМ КОНТЕКСТ ДЛЯ ГЕНЕРАЦИИ ===
            currentCurriculumContext = buildCurriculumContext(block, project);
            
            // Сохраняем в sessionStorage
            sessionStorage.setItem('curriculum_context', JSON.stringify(currentCurriculumContext));
            
            console.log('✅ Данные проекта загружены из УП:', project.title);
            console.log('📋 Контекст УП:', currentCurriculumContext);
            
            if (window.toast) {
                window.toast.success(`Загружен проект: ${project.title}`);
            }
        }
        
        /**
         * Строит контекст для генерации на основе выбранного проекта
         */
        function buildCurriculumContext(block, currentProject) {
            if (!currentCurriculum || !block || !currentProject) return null;
            
            const blockIndex = currentCurriculum.blocks.findIndex(b => b.name === block.name);
            const projectIndex = block.projects.findIndex(p => p.order === currentProject.order);
            
            // Соседние проекты внутри блока
            const previousProjects = block.projects.slice(0, projectIndex).map(p => ({
                order: p.order,
                title: p.title,
                description: p.description,
                learning_outcomes: p.learning_outcomes || [],
                block_name: block.name
            }));
            
            const nextProjects = block.projects.slice(projectIndex + 1).map(p => ({
                order: p.order,
                title: p.title,
                description: p.description,
                learning_outcomes: p.learning_outcomes || [],
                block_name: block.name
            }));
            
            // Все образовательные результаты блока
            const allBlockLO = [];
            for (const p of block.projects) {
                if (p.learning_outcomes) {
                    allBlockLO.push(...p.learning_outcomes);
                }
            }
            
            // Кросс-блочные связи
            const crossBlockDepth = 2;
            let previousBlockProjects = [];
            let nextBlockProjects = [];
            
            if (blockIndex > 0) {
                const prevBlock = currentCurriculum.blocks[blockIndex - 1];
                previousBlockProjects = prevBlock.projects.slice(-crossBlockDepth).map(p => ({
                    order: p.order,
                    title: p.title,
                    description: p.description,
                    learning_outcomes: p.learning_outcomes || [],
                    block_name: prevBlock.name
                }));
            }
            
            if (blockIndex < currentCurriculum.blocks.length - 1) {
                const nextBlock = currentCurriculum.blocks[blockIndex + 1];
                nextBlockProjects = nextBlock.projects.slice(0, crossBlockDepth).map(p => ({
                    order: p.order,
                    title: p.title,
                    description: p.description,
                    learning_outcomes: p.learning_outcomes || [],
                    block_name: nextBlock.name
                }));
            }
            
            return {
                block_name: block.name,
                block_goals: block.goals || [],
                current_project_order: currentProject.order,
                current_project_description: currentProject.description || '',
                current_project_skills: currentProject.skills || [],
                current_project_audience_level: currentProject.audience_level || null,
                current_project_required_tools: currentProject.required_tools || [],
                previous_projects: previousProjects,
                next_projects: nextProjects,
                all_block_learning_outcomes: [...new Set(allBlockLO)],
                previous_block_projects: previousBlockProjects,
                next_block_projects: nextBlockProjects,
                sjm_context: currentProject.sjm || null,
                expert_development_notes: currentProject.expert_notes || null,
                additional_materials: currentProject.additional_materials || null
            };
        }
        
        /**
         * Обработка изменения направления
         */
        function onDirectionChange() {
            const directionSelect = document.getElementById('direction');
            if (directionSelect.value === 'ADD') {
                document.getElementById('addBlockExpander').style.display = 'block';
            } else {
                document.getElementById('addBlockExpander').style.display = 'none';
                document.getElementById('thematicBlock').value = directionSelect.value;
            }
        }
        
        /**
         * Восстановление УП из sessionStorage
         */
        function restoreCurriculumFromSession() {
            try {
                const savedCurriculum = sessionStorage.getItem('curriculum_data');
                if (savedCurriculum) {
                    currentCurriculum = JSON.parse(savedCurriculum);
                    populateCurriculumBlocks();
                    document.getElementById('curriculumBlockGroup').style.display = 'block';
                    document.getElementById('curriculumFileName').textContent = `✅ ${currentCurriculum.direction} (восстановлен из сессии)`;
                    console.log('📚 УП восстановлен из сессии');
                }
                
                const savedContext = sessionStorage.getItem('curriculum_context');
                if (savedContext) {
                    currentCurriculumContext = JSON.parse(savedContext);
                    console.log('📋 Контекст УП восстановлен из сессии');
                }
            } catch (e) {
                console.warn('⚠️ Не удалось восстановить УП из сессии:', e);
            }
        }
        
        // Инициализация Mermaid с темной темой (если библиотека подключена)
        if (typeof mermaid !== 'undefined') {
            mermaid.initialize({ 
                startOnLoad: false, 
                securityLevel: 'loose',
                theme: 'dark',
                flowchart: {
                    htmlLabels: true,
                    curve: 'linear',
                    padding: 18,
                    nodeSpacing: 48,
                    rankSpacing: 58,
                    wrappingWidth: 190
                },
                themeVariables: {
                    primaryColor: '#141b2f',
                    primaryTextColor: '#edf3fb',
                    primaryBorderColor: '#64748b',
                    lineColor: '#8aa0ba',
                    secondaryColor: '#182033',
                    tertiaryColor: '#202a42',
                    background: 'transparent',
                    mainBkg: '#141b2f',
                    secondBkg: '#182033',
                    textColor: '#e0e6ed',
                    border1: '#64748b',
                    border2: '#5f6f89',
                    arrowheadColor: '#8aa0ba',
                    edgeLabelBackground: '#0d1428',
                    fontSize: '14px',
                    fontFamily: '-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, sans-serif'
                }
            });
        } else {
            console.warn('[Mermaid] Скрипт Mermaid не загружен на этой странице.');
        }
        
        // Загрузка направлений (ранее тематических блоков)
        async function loadThematicBlocks() {
            try {
                const response = await fetch(`${API_BASE}/api/v1/thematic-blocks`);
                if (response.ok) {
                    directions = await response.json();
                    thematicBlocks = directions; // обратная совместимость
                    updateDirectionSelect();
                }
            } catch (e) {
                console.log('Используем направления по умолчанию');
            }
            
            // Восстанавливаем УП из сессии
            restoreCurriculumFromSession();
        }
        
        function updateDirectionSelect() {
            const select = document.getElementById('direction');
            if (!select) return;
            
            const currentValue = select.value;
            select.innerHTML = '';
            
            for (const [name, code] of Object.entries(directions)) {
                const option = document.createElement('option');
                option.value = code;
                option.textContent = name;
                select.appendChild(option);
            }
            
            const addOption = document.createElement('option');
            addOption.value = 'ADD';
            addOption.textContent = 'Добавить';
            select.appendChild(addOption);
            
            if (currentValue && currentValue !== 'ADD') {
                select.value = currentValue;
            }
            
            select.onchange = onDirectionChange;
        }
        
        // Обратная совместимость
        function updateThematicBlockSelect() {
            updateDirectionSelect();
        }
        
        function toggleGroupSize() {
            const projectType = document.getElementById('projectType').value;
            const groupSizeGroup = document.getElementById('groupSizeGroup');
            groupSizeGroup.style.display = projectType === 'group' ? 'block' : 'none';
        }
        
        function toggleBonusWish() {
            const generateBonus = getChecked('generateBonus');
            setDisplay('bonusWishGroup', generateBonus ? 'block' : 'none');
        }
        
        function toggleExpander(id) {
            // Пытаемся найти элемент по ID
            const contentElement = document.getElementById(id);
            if (!contentElement) {
                console.error(`Элемент с ID "${id}" не найден`);
                return;
            }
            
            // Находим родительский элемент .expander
            let expander = contentElement.closest('.expander');
            
            // Если не нашли через closest, пытаемся найти напрямую
            if (!expander) {
                expander = contentElement.parentElement;
                while (expander && !expander.classList.contains('expander')) {
                    expander = expander.parentElement;
                }
            }
            
            if (expander) {
                const isOpen = expander.classList.contains('open');
                expander.classList.toggle('open');
                console.log(`Expander "${id}" ${isOpen ? 'закрыт' : 'открыт'}`);
            } else {
                console.error(`Родительский элемент .expander не найден для элемента "${id}"`);
                // Пытаемся найти напрямую по классу
                const allExpanders = document.querySelectorAll('.expander');
                console.log(`Найдено expanders на странице: ${allExpanders.length}`);
            }
        }
        
        // Экспортируем toggleExpander сразу после определения
        function handleFileSelect(event) {
            const fileInput = event && event.target ? event.target : null;
            const file = fileInput && fileInput.files ? fileInput.files[0] : null;
            if (file) {
                const fileNameEl = document.getElementById('fileName');
                if (fileNameEl) {
                    fileNameEl.textContent = file.name;
                }
                // Автоматически загружаем и парсим файл
                parseSpecFile(file);
            }
        }
        
        function handleTrackFilesSelect(event) {
            const fileInput = event && event.target ? event.target : null;
            const files = fileInput && fileInput.files ? Array.from(fileInput.files) : [];
            if (files.length > 0) {
                const trackFilesNamesEl = document.getElementById('trackFilesNames');
                if (trackFilesNamesEl) {
                    trackFilesNamesEl.textContent = `${files.length} файл(ов) выбрано`;
                }
            }
        }
        
        async function parseSpecFile(file) {
            const reader = new FileReader();
            reader.onload = async (e) => {
                try {
                    let data;
                    if (file.name.endsWith('.json')) {
                        data = JSON.parse(e.target.result);
                    } else if (file.name.endsWith('.xlsx')) {
                        // Для Excel нужен специальный endpoint
                        const formData = new FormData();
                        formData.append('file', file);
                        const response = await fetch(`${API_URL}/parse-excel`, {
                            method: 'POST',
                            body: formData
                        });
                        data = await response.json();
                    }
                    
                    // Заполняем форму данными из файла
                    fillFormFromData(data);
                } catch (error) {
                    alert('Ошибка при чтении файла: ' + error.message);
                }
            };
            reader.readAsText(file);
        }
        
        function fillFormFromData(data) {
            if (data.language) document.getElementById('language').value = data.language;
            if (data.project_type) {
                const projectType = data.project_type === 'индивидуальный' ? 'individual' : 
                                  data.project_type === 'групповой' ? 'group' : data.project_type;
                document.getElementById('projectType').value = projectType;
                toggleGroupSize();
            }
            if (data.thematic_block || data.track) {
                document.getElementById('thematicBlock').value = data.thematic_block || data.track;
            }
            if (data.audience_level) document.getElementById('audienceLevel').value = data.audience_level;
            // Маппинг: project_title -> title_seed для обратной совместимости
            if (data.title_seed || data.project_title) {
                document.getElementById('titleSeed').value = data.title_seed || data.project_title;
            }
            if (data.required_tools) {
                document.getElementById('requiredTools').value = Array.isArray(data.required_tools) 
                    ? data.required_tools.join(', ') 
                    : data.required_tools;
            }
            if (data.sjm) document.getElementById('storytelling').value = data.sjm;
            if (data.methodology_human_review !== undefined) {
                setChecked('methodologyHumanReview', !!data.methodology_human_review);
            }
            if (data.project_description) document.getElementById('projectDescription').value = data.project_description;
            if (data.learning_outcomes) {
                document.getElementById('learningOutcomes').value = Array.isArray(data.learning_outcomes)
                    ? data.learning_outcomes.join('\n')
                    : data.learning_outcomes;
            }
            if (data.skills) {
                document.getElementById('skills').value = Array.isArray(data.skills)
                    ? data.skills.join('\n')
                    : data.skills;
            }
            if (data.group_size) {
                document.getElementById('groupSize').value = data.group_size;
                toggleGroupSize();
            }
            if (data.repo_base_url) document.getElementById('repoBaseUrl').value = data.repo_base_url;
            if (data.repo_path_template) document.getElementById('repoPathTemplate').value = data.repo_path_template;
            if (data.bonus_wish) {
                setChecked('generateBonus', true);
                setValue('bonusWish', data.bonus_wish);
                toggleBonusWish();
            }
        }
        
        async function downloadTemplate() {
            try {
                const response = await fetch(`${API_URL}/template`);
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'project_spec_template.xlsx';
                a.click();
                window.URL.revokeObjectURL(url);
            } catch (error) {
                alert('Ошибка при скачивании шаблона: ' + error.message);
            }
        }
        
        async function addThematicBlock() {
            const name = document.getElementById('newBlockName').value.trim();
            const code = document.getElementById('newBlockCode').value.trim();
            
            if (!name) {
                alert('Введите название направления');
                return;
            }
            
            if (!code) {
                alert('Введите кодовое обозначение');
                return;
            }
            
            if (Object.values(directions).includes(code)) {
                alert(`Кодовое обозначение '${code}' уже используется!`);
                return;
            }
            
            directions[name] = code;
            thematicBlocks = directions; // обратная совместимость
            updateDirectionSelect();
            document.getElementById('direction').value = code;
            document.getElementById('addBlockExpander').style.display = 'none';
            document.getElementById('newBlockName').value = '';
            document.getElementById('newBlockCode').value = '';
            
            // Сохраняем на сервере
            try {
                const token = localStorage.getItem('auth_token');
                await fetch(`${API_URL}/thematic-blocks`, {
                    method: 'POST',
                    headers: { 
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify(thematicBlocks)
                });
            } catch (e) {
                console.log('Не удалось сохранить тематические блоки на сервере');
            }
        }
        
        async function clearForm() {
            // Очищаем состояние генерации при очистке формы
            clearGenerationState();
            
            // Используем модальное окно для подтверждения
            let confirmed = false;
            if (window.modal) {
                confirmed = await window.modal.confirm(
                    'Очистить форму',
                    'Вы уверены, что хотите очистить все поля формы? Это действие нельзя отменить.',
                    'Очистить',
                    'Отмена'
                );
            } else {
                confirmed = confirm('Очистить все поля формы?');
            }
            
            if (!confirmed) return;
            
            {
                // Очищаем все поля формы вручную
                
                // Базовые параметры
                document.getElementById('language').value = 'ru';
                document.getElementById('projectType').value = 'individual';
                document.getElementById('groupSize').value = '3';
                document.getElementById('groupSizeGroup').style.display = 'none';
                
                // Тематический блок
                document.getElementById('thematicBlock').value = 'BSA';
                document.getElementById('newBlockName').value = '';
                document.getElementById('newBlockCode').value = '';
                document.getElementById('addBlockExpander').style.display = 'none';
                
                // Остальные поля
                document.getElementById('audienceLevel').value = '';
                document.getElementById('titleSeed').value = '';
                document.getElementById('requiredTools').value = '';
                document.getElementById('storytelling').value = '';
                document.getElementById('projectDescription').value = '';
                document.getElementById('learningOutcomes').value = '';
                document.getElementById('skills').value = '';
                
                // Настройки репозитория
                document.getElementById('repoBaseUrl').value = '';
                document.getElementById('repoPathTemplate').value = 'repo/part-03/task-{num:02d}/README.md';
                
                // Бонусное задание
                setChecked('generateBonus', false);
                setValue('bonusWish', '');
                setDisplay('bonusWishGroup', 'none');
                
                setChecked('methodologyHumanReview', false);
                
                // Файлы
                const specFileInput = document.getElementById('specFile');
                const fileNameEl = document.getElementById('fileName');
                const trackFilesInput = document.getElementById('trackFiles');
                const trackFilesNamesEl = document.getElementById('trackFilesNames');
                if (specFileInput) specFileInput.value = '';
                if (fileNameEl) fileNameEl.textContent = '';
                if (trackFilesInput) trackFilesInput.value = '';
                if (trackFilesNamesEl) trackFilesNamesEl.textContent = '';
                
                // Закрываем все expanders
                const expanders = ['repoExpander', 'advancedExpander'];
                expanders.forEach(id => {
                    const expander = document.getElementById(id);
                    if (expander) {
                        expander.style.display = 'none';
                    }
                });
                
                console.log('✅ Форма очищена');
                if (window.toast) {
                    window.toast.success('Форма успешно очищена');
                }
            }
        }
        
        async function clearGeneration() {
            // Используем модальное окно для подтверждения
            let confirmed = false;
            if (window.modal) {
                confirmed = await window.modal.confirm(
                    'Очистить генерацию',
                    'Вы уверены, что хотите очистить результаты генерации? Это действие нельзя отменить.',
                    'Очистить',
                    'Отмена'
                );
            } else {
                confirmed = confirm('Очистить результаты генерации?');
            }
            
            if (!confirmed) return;
            
            currentRequestId = null;
            currentMarkdown = null;
            originalMarkdown = null;
            currentResult = null;
            currentSeed = null;
            clearGenerationState(); // Очищаем сохраненное состояние
            document.getElementById('noResults').style.display = 'block';
            document.getElementById('resultsArea').style.display = 'none';
            
            if (window.toast) {
                window.toast.success('Результаты генерации очищены');
            }
        }
        
        function clearRegeneration() {
            document.getElementById('regenerationComments').value = '';
            document.getElementById('regenContent').innerHTML = '';
            document.getElementById('regenerationChanges').style.display = 'none';
            // Сбрасываем версии на оригинальные
            currentMetricsVersion = 'original';
            currentReportVersion = 'original';
            if (originalRubric) {
                window.currentRubric = originalRubric;
                displayMetrics(originalRubric, 'metricsContentOriginal');
                switchMetricsVersion('original');
            }
            if (originalTextStats) {
                displayReport({ text_stats: originalTextStats }, 'reportContentOriginal');
                switchReportVersion('original');
            }
            // Обновляем переключатели
            updateVersionButtons();
        }
        
        function switchMetricsVersion(version, clickedElement = null) {
            currentMetricsVersion = version;
            window.currentMetricsVersion = version; // Обновляем глобальную переменную
            
            // Переключаем вкладки
            const tabOriginal = document.getElementById('metricsTabOriginal');
            const tabRegen = document.getElementById('metricsTabRegen');
            if (tabOriginal && tabRegen) {
                tabOriginal.classList.remove('active');
                tabRegen.classList.remove('active');
                if (version === 'original') {
                    tabOriginal.classList.add('active');
                } else {
                    tabRegen.classList.add('active');
                }
            }
            
            // Переключаем контейнеры
            const containerOriginal = document.getElementById('metricsContentOriginal');
            const containerRegen = document.getElementById('metricsContentRegen');
            if (containerOriginal && containerRegen) {
                if (version === 'original') {
                    containerOriginal.style.display = 'block';
                    containerRegen.style.display = 'none';
                    if (originalRubric) {
                        window.currentRubric = originalRubric;
                        displayMetrics(originalRubric, 'metricsContentOriginal');
                        console.log('✅ Переключено на оригинальные метрики, отображено:', originalRubric.items?.length || 0, 'критериев');
                    } else {
                        console.warn('⚠️ originalRubric отсутствует, контейнер пуст');
                        containerOriginal.innerHTML = '<div class="info-box">Оригинальные метрики недоступны</div>';
                    }
                } else {
                    containerOriginal.style.display = 'none';
                    containerRegen.style.display = 'block';
                    if (regeneratedRubric) {
                        window.currentRubric = regeneratedRubric;
                        displayMetrics(regeneratedRubric, 'metricsContentRegen');
                        console.log('✅ Переключено на перегенерированные метрики, отображено:', regeneratedRubric.items?.length || 0, 'критериев');
                    } else {
                        console.warn('⚠️ regeneratedRubric отсутствует, контейнер пуст');
                        containerRegen.innerHTML = '<div class="info-box">Перегенерированные метрики недоступны</div>';
                    }
                }
            } else {
                console.error('❌ Контейнеры метрик не найдены:', {
                    original: !!containerOriginal,
                    regen: !!containerRegen
                });
            }
        }
        
        function switchReportVersion(version, clickedElement = null) {
            currentReportVersion = version;
            window.currentReportVersion = version; // Обновляем глобальную переменную
            
            // Переключаем вкладки
            const tabOriginal = document.getElementById('reportTabOriginal');
            const tabRegen = document.getElementById('reportTabRegen');
            if (tabOriginal && tabRegen) {
                tabOriginal.classList.remove('active');
                tabRegen.classList.remove('active');
                if (version === 'original') {
                    tabOriginal.classList.add('active');
                } else {
                    tabRegen.classList.add('active');
                }
            }
            
            // Переключаем контейнеры
            const containerOriginal = document.getElementById('reportContentOriginal');
            const containerRegen = document.getElementById('reportContentRegen');
            if (containerOriginal && containerRegen) {
                if (version === 'original') {
                    containerOriginal.style.display = 'block';
                    containerRegen.style.display = 'none';
                    if (originalTextStats) {
                        displayReport({ text_stats: originalTextStats }, 'reportContentOriginal');
                    }
                } else {
                    containerOriginal.style.display = 'none';
                    containerRegen.style.display = 'block';
                    if (regeneratedTextStats) {
                        displayReport({ text_stats: regeneratedTextStats }, 'reportContentRegen');
                    }
                }
            }
        }
        
        function updateVersionButtons() {
            console.log('updateVersionButtons вызвана', { 
                regeneratedRubric: !!regeneratedRubric,
                regeneratedRubricItems: regeneratedRubric?.items?.length || 0,
                regeneratedTextStats: !!regeneratedTextStats,
                originalRubric: !!originalRubric,
                originalRubricItems: originalRubric?.items?.length || 0
            });
            
            // Показываем/скрываем переключатель метрик (вкладки)
            const metricsSwitcher = document.getElementById('metricsVersionSwitcher');
            if (metricsSwitcher) {
                if (regeneratedRubric && regeneratedRubric.items && regeneratedRubric.items.length > 0) {
                    metricsSwitcher.style.display = 'block';
                    console.log('✅ Переключатель метрик показан (есть перегенерированные метрики)');
                } else {
                    metricsSwitcher.style.display = 'none';
                    console.log('❌ Переключатель метрик скрыт (нет regeneratedRubric или он пуст)', {
                        hasRegeneratedRubric: !!regeneratedRubric,
                        itemsCount: regeneratedRubric?.items?.length || 0
                    });
                }
            } else {
                console.error('❌ Элемент metricsVersionSwitcher не найден в DOM');
            }
            
            // Показываем/скрываем переключатель отчета (вкладки)
            const reportSwitcher = document.getElementById('reportVersionSwitcher');
            if (reportSwitcher) {
                if (regeneratedTextStats) {
                    reportSwitcher.style.display = 'block';
                    console.log('✅ Переключатель отчета показан');
                } else {
                    reportSwitcher.style.display = 'none';
                    console.log('❌ Переключатель отчета скрыт (нет regeneratedTextStats)');
                }
            } else {
                console.error('❌ Элемент reportVersionSwitcher не найден в DOM');
            }
        }
        
        // Функция для форматирования времени
        function formatTime(seconds) {
            const mins = Math.floor(seconds / 60);
            const secs = seconds % 60;
            return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        }

        // Функция для обновления таймера
        function updateTimer() {
            if (!generationStartTime) return;
            const elapsed = Math.floor((Date.now() - generationStartTime) / 1000);
            const timerElement = document.getElementById('generationTimer');
            if (timerElement) {
                timerElement.textContent = formatTime(elapsed);
            }
        }
        
        // Функция для запуска таймера с использованием requestAnimationFrame для надежности
        function startTimer() {
            if (generationTimer) {
                clearInterval(generationTimer);
            }
            
            // Если время начала не установлено, пытаемся восстановить из sessionStorage
            if (!generationStartTime) {
                try {
                    const saved = sessionStorage.getItem('generation_state');
                    if (saved) {
                        const state = JSON.parse(saved);
                        if (state.generationStartTime) {
                            generationStartTime = state.generationStartTime;
                        }
                    }
                } catch (error) {
                    console.debug('Не удалось восстановить время начала генерации:', error);
                }
            }
            
            // Если время начала все еще не установлено, устанавливаем текущее время
            if (!generationStartTime) {
                generationStartTime = Date.now();
            }
            
            // Используем комбинацию setInterval и requestAnimationFrame для надежности
            let lastUpdate = Date.now();
            generationTimer = setInterval(() => {
                const now = Date.now();
                // Обновляем только если прошла хотя бы секунда
                if (now - lastUpdate >= 1000) {
                    updateTimer();
                    lastUpdate = now;
                }
                // Также используем requestAnimationFrame для гарантированного обновления UI
                requestAnimationFrame(() => {
                    if (generationStartTime) {
                        updateTimer();
                    }
                });
            }, 100);
        }

        function showCompactGenerationProgress(message = 'Генерация проекта...', options = {}) {
            const generationLogs = document.getElementById('generationLogs');
            const logContent = document.getElementById('logContent');
            if (generationLogs) {
                generationLogs.style.display = 'block';
            }
            if (!logContent) return;

            logContent.innerHTML = '';
            let progressBarId = null;
            let spinnerId = null;
            if (window.loading) {
                progressBarId = window.loading.createProgressBar('logContent', 'Прогресс генерации');
                spinnerId = window.loading.showSpinner('logContent', message);
            } else {
                logContent.innerHTML = `<div class="generation-activity"><span class="generation-activity-dot"></span><span>${message}</span></div>`;
            }

            window.currentProgressBarId = progressBarId;
            window.currentSpinnerId = spinnerId;
            if (options.agent) {
                const agentElement = document.getElementById('currentAgent');
                if (agentElement) {
                    agentElement.textContent = options.agent;
                }
            }
            if (window.loading && progressBarId && Number(options.progress || 0) > 0) {
                window.loading.updateProgress(progressBarId, options.progress);
            }
        }

        /**
         * Вычисляет процент прогресса на основе фазы генерации
         */
        function calculateProgressFromPhase(phase) {
            const phaseProgressMap = {
                'initialization': 5,
                'context': 15,
                'task_planning': 25,
                'title': 30,
                'title_annotation': 30,
                'skeleton': 35,
                'intro_rules': 38,
                'structural_preflight': 42,
                'theory': 50,
                'definitions': 55,
                'theory_checks': 58,
                'practice': 65,
                'dataset_generation': 72,
                'quality': 75,
                'global_quality': 80,
                'translate': 85,
                'evaluation': 90,
                'finalize': 95,
                'readme_check': 98,
                'completion': 100,
                'validation': 92,
                'methodology_review': 0,
            };
            
            return phaseProgressMap[phase] || 0;
        }

        function progressFromCheckpointStage(stage) {
            const normalized = {
                title: 'title_annotation',
                annotation: 'title_annotation',
                structure: 'skeleton',
                skeleton: 'skeleton',
                theory: 'theory_checks',
                practice: 'practice',
                dataset: 'dataset_generation',
                materials: 'dataset_generation',
                quality: 'global_quality',
                evaluation: 'evaluation',
                final: 'global_quality'
            }[String(stage || '').trim()] || String(stage || '').trim();
            return calculateProgressFromPhase(normalized);
        }

        // Функция для получения текущего агента из логов
        async function updateCurrentAgent(requestId, options = {}) {
            if (!requestId) return;
            
            try {
                const token = localStorage.getItem('auth_token');
                const response = await fetch(`${API_URL}/metrics/${requestId}`, {
                    headers: getAuthHeaders()
                });
                
                if (response.ok) {
                    const data = await response.json();
                    const logs = data.logs || [];
                    
                    // Ищем последний лог с информацией об агенте или фазе.
                    // Service-фаза methodology_review не должна откатывать прогресс к началу:
                    // берем ближайший реальный этап генерации и сохраняем монотонность.
                    let currentAgent = 'Инициализация...';
                    let currentPhase = null;
                    let progress = 0;
                    let sawMethodologyReview = false;
                    
                    for (let i = logs.length - 1; i >= 0; i--) {
                        const log = logs[i];
                        if (log.phase) {
                            // Пытаемся извлечь имя агента из phase или message
                            const phase = log.phase;
                            if (phase === 'methodology_review') {
                                sawMethodologyReview = true;
                                continue;
                            }
                            currentPhase = phase;
                            progress = calculateProgressFromPhase(phase);
                            const message = log.message || '';
                            
                            // Маппинг фаз на понятные названия агентов
                            const phaseMap = {
                                'initialization': 'Инициализация',
                                'context': 'Контекст проекта',
                                'task_planning': 'Планирование задач',
                                'title': 'Название',
                                'title_annotation': 'Название и аннотация',
                                'skeleton': 'Агент каркаса',
                                'intro_rules': 'Введение и инструкция',
                                'structural_preflight': 'Проверка структуры',
                                'theory': 'Теоретический агент',
                                'definitions': 'Определения',
                                'theory_checks': 'Проверка теории',
                                'practice': 'Практический агент',
                                'dataset_generation': 'Материалы практики',
                                'quality': 'Агент качества',
                                'global_quality': 'Агент качества',
                                'translate': 'Агент перевода',
                                'evaluation': 'Агент оценки',
                                'finalize': 'Финальная обработка',
                                'readme_check': 'Проверка README',
                                'completion': 'Завершение',
                                'validation': 'Валидация',
                                'validation_error': 'Ошибка валидации',
                                'generation_error': 'Ошибка генерации',
                                'unexpected_error': 'Неожиданная ошибка',
                                'methodology_review': 'Ожидание методолога'
                            };
                            
                            if (phaseMap[phase]) {
                                currentAgent = phaseMap[phase];
                            } else if (message.includes('агент') || message.includes('Agent')) {
                                // Пытаемся извлечь имя агента из сообщения
                                const agentMatch = message.match(/(\w+Agent|\w+ агент)/i);
                                if (agentMatch) {
                                    currentAgent = agentMatch[1];
                                } else {
                                    currentAgent = phase;
                                }
                            } else {
                                currentAgent = phase;
                            }
                            break;
                        }
                    }

                    const checkpointProgress = progressFromCheckpointStage(
                        options.methodology?.checkpoint?.stage
                        || options.methodology?.checkpoint?.id
                    );
                    const phaseProgress = progress;
                    progress = Math.max(progress, checkpointProgress, lastKnownGenerationProgress || 0);
                    if (currentPhase) {
                        const movedBack = (lastKnownGenerationProgress || 0) > phaseProgress
                            && phaseProgress > 0
                            && options.status !== 'completed';
                        if (movedBack && lastKnownGenerationAgent) {
                            currentAgent = lastKnownGenerationAgent;
                        } else {
                            lastKnownGenerationPhase = currentPhase;
                            lastKnownGenerationAgent = currentAgent;
                        }
                        lastKnownGenerationProgress = progress;
                    } else if (sawMethodologyReview) {
                        currentAgent = options.status === 'needs_review'
                            ? 'Ожидание методолога'
                            : (lastKnownGenerationAgent || 'Продолжение генерации');
                        progress = Math.max(progress, lastKnownGenerationProgress || checkpointProgress || 0);
                    }
                    
                    const agentElement = document.getElementById('currentAgent');
                    if (agentElement) {
                        agentElement.textContent = currentAgent;
                    }
                    
                    // Обновляем прогресс-бар
                    if (window.loading && window.currentProgressBarId && progress > 0) {
                        window.loading.updateProgress(window.currentProgressBarId, progress);
                    }
                }
            } catch (error) {
                // Игнорируем ошибки при получении логов
                console.debug('Не удалось получить логи:', error);
            }
        }

        // Функция для остановки таймера и polling
        function stopGenerationTracking(options = {}) {
            if (generationTimer) {
                clearInterval(generationTimer);
                generationTimer = null;
            }
            if (agentPollInterval) {
                clearInterval(agentPollInterval);
                agentPollInterval = null;
            }
            if (statusPollInterval) {
                clearInterval(statusPollInterval);
                statusPollInterval = null;
            }
            if (!options.preserveStartTime) {
                generationStartTime = null;
            }
        }
        
        // Функция для скрытия кнопки остановки
        function hideCancelButton() {
            const cancelBtn = document.getElementById('cancelGenerationBtn');
            if (cancelBtn) {
                cancelBtn.style.display = 'none';
                cancelBtn.disabled = false;
                cancelBtn.textContent = '🛑 Аварийная остановка генерации';
            }
        }
        
        // Функция для показа кнопки остановки
        function showCancelButton() {
            console.log('🔵 showCancelButton() вызвана');
            const cancelBtn = document.getElementById('cancelGenerationBtn');
            if (!cancelBtn) {
                console.error('❌ Кнопка cancelGenerationBtn не найдена в DOM!');
                return;
            }
            
            console.log('🔵 Кнопка найдена, показываем...', {
                before: {
                    display: cancelBtn.style.display,
                    computedDisplay: window.getComputedStyle(cancelBtn).display
                }
            });
            
            // Убираем все скрывающие стили ПРИНУДИТЕЛЬНО
            cancelBtn.style.setProperty('display', 'block', 'important');
            cancelBtn.style.setProperty('visibility', 'visible', 'important');
            cancelBtn.style.setProperty('opacity', '1', 'important');
            cancelBtn.style.setProperty('width', '100%', 'important');
            cancelBtn.style.setProperty('margin-top', '0.5rem', 'important');
            cancelBtn.disabled = false;
            cancelBtn.textContent = '🛑 Аварийная остановка генерации';
            
            // Проверяем сразу
            const rect = cancelBtn.getBoundingClientRect();
            const computedStyle = window.getComputedStyle(cancelBtn);
            console.log('🔵 Кнопка после установки стилей:', {
                display: cancelBtn.style.display,
                computedDisplay: computedStyle.display,
                computedVisibility: computedStyle.visibility,
                rect: { width: rect.width, height: rect.height, top: rect.top },
                isVisible: rect.width > 0 && rect.height > 0 && computedStyle.display !== 'none'
            });
            
            // Принудительно показываем кнопку через несколько кадров для гарантии
            setTimeout(() => {
                if (cancelBtn) {
                    cancelBtn.style.setProperty('display', 'block', 'important');
                    cancelBtn.style.setProperty('visibility', 'visible', 'important');
                    const rect2 = cancelBtn.getBoundingClientRect();
                    const computedStyle2 = window.getComputedStyle(cancelBtn);
                    const isVisible = rect2.width > 0 && rect2.height > 0 && 
                                    computedStyle2.display !== 'none' &&
                                    computedStyle2.visibility !== 'hidden';
                    console.log('✅ Кнопка остановки (после таймаута):', {
                        display: cancelBtn.style.display,
                        computedDisplay: computedStyle2.display,
                        computedVisibility: computedStyle2.visibility,
                        rect: { width: rect2.width, height: rect2.height },
                        isVisible: isVisible
                    });
                    
                    if (!isVisible) {
                        console.error('❌ КРИТИЧЕСКАЯ ОШИБКА: Кнопка не видна!', {
                            element: cancelBtn,
                            parent: cancelBtn.parentElement,
                            parentDisplay: cancelBtn.parentElement ? window.getComputedStyle(cancelBtn.parentElement).display : 'no parent',
                            styles: {
                                display: cancelBtn.style.display,
                                visibility: cancelBtn.style.visibility,
                                computed: {
                                    display: computedStyle2.display,
                                    visibility: computedStyle2.visibility,
                                    opacity: computedStyle2.opacity
                                }
                            }
                        });
                    }
                }
            }, 50);
        }

        // Polling статуса генерации
        let statusPollInterval = null;

        async function pollGenerationStatus(requestId) {
            if (!requestId) return;
            
            // Останавливаем предыдущий polling, если есть
            if (statusPollInterval) {
                clearInterval(statusPollInterval);
            }
            
            // Начинаем polling каждые 1.5 секунды
            statusPollInterval = setInterval(async () => {
                try {
                    const response = await fetch(`${API_URL}/generate/status/${requestId}`, {
                        headers: getAuthHeaders()
                    });
                    
                    if (!response.ok) {
                        if (response.status === 404) {
                            // Запрос не найден - останавливаем polling
                            stopGenerationTracking();
                            if (statusPollInterval) {
                                clearInterval(statusPollInterval);
                                statusPollInterval = null;
                            }
                            const logContent = document.getElementById('logContent');
                            if (logContent) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetErrorMessage(logContent, 'Запрос генерации не найден (404)');
                                } else {
                                    logContent.textContent = '❌ Запрос генерации не найден (404)';
                                }
                            }
                            const btn = document.getElementById('generateBtn');
                            if (btn) {
                                btn.disabled = false;
                                btn.textContent = '🚀 Сгенерировать';
                            }
                            return;
                        }
                        // Пытаемся получить текст ошибки
                        let errorText = `Ошибка ${response.status}`;
                        try {
                            const errorData = await response.json();
                            errorText = errorData.detail || errorData.message || errorText;
                        } catch {
                            try {
                                errorText = await response.text();
                            } catch {
                                // Игнорируем ошибки парсинга
                            }
                        }
                        console.error('Ошибка при проверке статуса:', errorText);
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            if (window.sanitize) {
                                window.sanitize.safeSetErrorMessage(logContent, `Ошибка сервера: ${errorText}`);
                            } else {
                                logContent.textContent = `❌ Ошибка сервера: ${errorText}`;
                            }
                        }
                        return;
                    }
                    
                    // Проверяем, что ответ - это JSON
                    let data;
                    try {
                        const contentType = response.headers.get('content-type');
                        if (!contentType || !contentType.includes('application/json')) {
                            console.error('⚠️ Сервер вернул не JSON ответ:', contentType);
                            const text = await response.text();
                            console.error('Ответ сервера:', text.substring(0, 200));
                            const logContent = document.getElementById('logContent');
                            if (logContent) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetErrorMessage(logContent, 'Сервер вернул неожиданный формат ответа. Проверьте консоль браузера.');
                                } else {
                                    logContent.textContent = '❌ Сервер вернул неожиданный формат ответа. Проверьте консоль браузера.';
                                }
                            }
                            return;
                        }
                        data = await response.json();
                    } catch (parseError) {
                        console.error('❌ Ошибка парсинга JSON ответа:', parseError);
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            if (window.sanitize) {
                                window.sanitize.safeSetErrorMessage(logContent, 'Ошибка парсинга ответа сервера. Проверьте консоль браузера.');
                            } else {
                                logContent.textContent = '❌ Ошибка парсинга ответа сервера. Проверьте консоль браузера.';
                            }
                        }
                        return;
                    }
                    
                    // Проверяем структуру ответа
                    if (!data || typeof data !== 'object') {
                        console.error('❌ Неожиданная структура ответа:', data);
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            if (window.sanitize) {
                                window.sanitize.safeSetErrorMessage(logContent, 'Сервер вернул неожиданный ответ. Проверьте консоль браузера.');
                            } else {
                                logContent.textContent = '❌ Сервер вернул неожиданный ответ. Проверьте консоль браузера.';
                            }
                        }
                        return;
                    }
                    
                    const status = data.status;
                    if (!status) {
                        console.error('❌ Отсутствует поле status в ответе:', data);
                        return;
                    }
                    
                    // Логируем для отладки
                    console.debug('Polling status:', { status, hasResult: !!data.result, requestId });
                    
                    if (data.methodology) {
                        renderMethodologyPanel(data.methodology, 'methodologyLiveStatus', { compact: true });
                    }

                    // Обновляем текущего агента
                    await updateCurrentAgent(requestId, {
                        status,
                        methodology: data.methodology || null
                    });
                    
                    // Убеждаемся, что кнопка остановки видна при активной генерации
                    if (status === 'pending' || status === 'in_progress') {
                        const cancelBtn = document.getElementById('cancelGenerationBtn');
                        if (cancelBtn) {
                            cancelBtn.style.setProperty('display', 'block', 'important');
                            cancelBtn.disabled = false;
                        }
                    }
                    
                    if (status === 'cancelled') {
                        // Генерация была остановлена
                        stopGenerationTracking();
                        if (statusPollInterval) {
                            clearInterval(statusPollInterval);
                            statusPollInterval = null;
                        }
                        
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            if (window.sanitize) {
                                logContent.innerHTML = '<div class="warning-msg">🛑 Генерация остановлена пользователем</div>';
                            } else {
                                logContent.textContent = '🛑 Генерация остановлена пользователем';
                            }
                        }
                        
                        const btn = document.getElementById('generateBtn');
                        if (btn) {
                            btn.disabled = false;
                            btn.textContent = '🚀 Сгенерировать';
                        }
                        
                        hideCancelButton();
                        hideMethodologyReviewActions();
                        
                        return;
                    } else if (status === 'needs_review') {
                        stopGenerationTracking({ preserveStartTime: true });
                        if (statusPollInterval) {
                            clearInterval(statusPollInterval);
                            statusPollInterval = null;
                        }

                        hideCancelButton();
                        const errorMsg = data.error || 'Требуется ручная методологическая проверка';
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            const text = `⚠️ ${errorMsg}`;
                            logContent.innerHTML = `<div class="warning-msg">${window.sanitize ? window.sanitize.escapeHtml(text) : text}</div>`;
                        }
                        if (data.methodology) {
                            renderMethodologyPanel(data.methodology, 'methodologyLiveStatus', { compact: true });
                        }
                        showMethodologyReviewActions(requestId, errorMsg);
                        const noResults = document.getElementById('noResults');
                        if (noResults) {
                            noResults.style.display = 'none';
                        }
                        document.getElementById('methodologyReviewWorkspace')?.scrollIntoView({
                            behavior: 'smooth',
                            block: 'start'
                        });
                        const btn = document.getElementById('generateBtn');
                        if (btn) {
                            btn.disabled = false;
                            btn.textContent = '🚀 Сгенерировать';
                        }
                        return;
                    } else if (status === 'completed') {
                        // Проверяем наличие результата
                        if (!data.result) {
                            // Возможна race condition - результат еще не сохранен в кэш
                            // Продолжаем polling, чтобы дождаться результата
                            console.warn('⚠️ Статус completed, но результат отсутствует. Продолжаем polling...', { requestId });
                            return; // Продолжаем polling в следующей итерации
                        }
                        
                        // Генерация завершена и результат есть
                        stopGenerationTracking();
                        if (statusPollInterval) {
                            clearInterval(statusPollInterval);
                            statusPollInterval = null;
                        }
                        
                        // Скрываем кнопку остановки
                        const cancelBtn = document.getElementById('cancelGenerationBtn');
                        if (cancelBtn) {
                            cancelBtn.style.display = 'none';
                        }
                        hideMethodologyReviewActions();
                        
                        // Сначала проверяем структуру результата
                        if (!data.result || typeof data.result !== 'object') {
                            console.error('❌ Результат имеет неожиданную структуру:', data.result);
                            const logContent = document.getElementById('logContent');
                            if (logContent) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetErrorMessage(logContent, 'Результат генерации имеет неожиданную структуру. Проверьте консоль браузера.');
                                } else {
                                    logContent.textContent = '❌ Результат генерации имеет неожиданную структуру. Проверьте консоль браузера.';
                                }
                            }
                            const btn = document.getElementById('generateBtn');
                            if (btn) {
                                btn.disabled = false;
                                btn.textContent = '🚀 Сгенерировать';
                            }
                            return;
                        }
                        
                        // Проверяем наличие markdown
                        if (typeof data.result.markdown !== 'string') {
                            console.error('❌ Отсутствует или неверный тип поля markdown:', typeof data.result.markdown, data.result);
                            const logContent = document.getElementById('logContent');
                            if (logContent) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetErrorMessage(logContent, 'Результат генерации не содержит markdown. Проверьте консоль браузера.');
                                } else {
                                    logContent.textContent = '❌ Результат генерации не содержит markdown. Проверьте консоль браузера.';
                                }
                            }
                            const btn = document.getElementById('generateBtn');
                            if (btn) {
                                btn.disabled = false;
                                btn.textContent = '🚀 Сгенерировать';
                            }
                            return;
                        }
                        
                        // Логируем структуру результата для отладки
                        console.log('✅ Результат получен:', {
                            hasMarkdown: !!data.result.markdown,
                            hasRubric: !!data.result.rubric,
                            keys: Object.keys(data.result || {})
                        });
                        
                        // Загружаем результат
                        currentRequestId = data.request_id;
                        currentResult = data.result;
                        currentMarkdown = data.result.markdown; // Уже проверили, что это строка
                        originalMarkdown = currentMarkdown;
                        
                        // Извлекаем originalRubric и originalTextStats из результата
                        if (data.result?.rubric) {
                            originalRubric = data.result.rubric;
                            window.currentRubric = data.result.rubric;
                        }
                        if (data.result?.text_stats) {
                            originalTextStats = data.result.text_stats;
                        }
                        
                        // Сохраняем состояние
                        saveGenerationState();
                        
                        // Удаляем spinner и progress bar
                        if (window.loading) {
                            if (window.currentSpinnerId) {
                                window.loading.hideSpinner(window.currentSpinnerId);
                            }
                            if (window.currentProgressBarId) {
                                window.loading.removeProgressBar(window.currentProgressBarId);
                            }
                        }
                        
                        // Очищаем logContent от любых предыдущих ошибок
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            logContent.innerHTML = ''; // Очищаем ошибки
                        }
                        
                        // Скрываем загрузчик
                        const generationLogs = document.getElementById('generationLogs');
                        if (generationLogs) {
                            generationLogs.style.display = 'none';
                        }
                        
                        // Показываем toast об успешной генерации
                        if (window.toast) {
                            window.toast.success('Генерация успешно завершена!');
                        }
                        
                        // Отображаем результаты с обработкой ошибок
                        try {
                            displayResults({
                                request_id: data.request_id,
                                result: data.result,
                                warnings: data.warnings || [],
                                methodology: data.methodology || data.result.methodology_gate || null
                            });
                        } catch (displayError) {
                            console.error('❌ Ошибка при отображении результатов:', displayError);
                            // Показываем ошибку в logContent
                            if (logContent) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetErrorMessage(logContent, `Ошибка отображения результатов: ${displayError.message}. Проверьте консоль браузера (F12).`);
                                } else {
                                    logContent.textContent = `❌ Ошибка отображения результатов: ${displayError.message}. Проверьте консоль браузера (F12).`;
                                }
                            }
                            // Показываем generationLogs обратно, чтобы пользователь увидел ошибку
                            if (generationLogs) {
                                generationLogs.style.display = 'block';
                            }
                        }
                        
                        // Восстанавливаем кнопку
                        const btn = document.getElementById('generateBtn');
                        if (btn) {
                            if (window.loading) {
                                window.loading.setButtonLoading(btn, false, '🚀 Сгенерировать');
                            } else {
                                btn.disabled = false;
                                btn.textContent = '🚀 Сгенерировать';
                            }
                        }
                        
                    } else if (status === 'failed') {
                        // Генерация завершилась с ошибкой
                        stopGenerationTracking();
                        
                        // Скрываем кнопку остановки
                        const cancelBtn = document.getElementById('cancelGenerationBtn');
                        if (cancelBtn) {
                            cancelBtn.style.display = 'none';
                        }
                        if (statusPollInterval) {
                            clearInterval(statusPollInterval);
                            statusPollInterval = null;
                        }
                        
                        const errorMsg = data.error || 'Неизвестная ошибка';
                        const logContent = document.getElementById('logContent');
                        if (logContent) {
                            if (window.sanitize) {
                                window.sanitize.safeSetErrorMessage(logContent, `Ошибка генерации: ${errorMsg}`);
                            } else {
                                logContent.textContent = `❌ Ошибка генерации: ${errorMsg}`;
                            }
                        }
                        
                        // Восстанавливаем кнопку
                        const btn = document.getElementById('generateBtn');
                        if (btn) {
                            btn.disabled = false;
                            btn.textContent = '🚀 Сгенерировать';
                        }
                    }
                    // Если status === 'pending' или 'in_progress', продолжаем polling
                    
                } catch (error) {
                    console.error('Ошибка при проверке статуса генерации:', error);
                    // Не останавливаем polling при ошибке сети, продолжаем попытки
                }
            }, 1500); // Polling каждые 1.5 секунды
        }
        
        async function generateContent() {
            // Валидация формы
            if (!window.validator || !window.validator.validateGenerationForm()) {
                if (window.toast) {
                    window.toast.error('Пожалуйста, исправьте ошибки в форме перед генерацией');
                }
                return;
            }

            const btn = document.getElementById('generateBtn');
            
            // Используем loading manager для кнопки
            if (window.loading) {
                window.loading.setButtonLoading(btn, true, '🚀 Сгенерировать');
            } else {
                btn.disabled = true;
                btn.textContent = '⏳ Генерация...';
            }
            
            // Показываем кнопку остановки СРАЗУ при нажатии на "Сгенерировать" - ПРЯМО ЗДЕСЬ
            const cancelBtn = document.getElementById('cancelGenerationBtn');
            if (cancelBtn) {
                // Принудительно показываем кнопку
                cancelBtn.style.setProperty('display', 'block', 'important');
                cancelBtn.style.setProperty('visibility', 'visible', 'important');
                cancelBtn.style.setProperty('opacity', '1', 'important');
                cancelBtn.style.setProperty('width', '100%', 'important');
                cancelBtn.style.setProperty('margin-top', '0.5rem', 'important');
                cancelBtn.style.setProperty('height', 'auto', 'important');
                cancelBtn.disabled = false;
                
                // Проверяем через небольшую задержку
                setTimeout(() => {
                    const computed = window.getComputedStyle(cancelBtn);
                    const rect = cancelBtn.getBoundingClientRect();
                    const isVisible = computed.display !== 'none' && 
                                    computed.visibility !== 'hidden' && 
                                    rect.width > 0 && 
                                    rect.height > 0;
                    console.log('✅ Кнопка остановки (проверка через 100ms):', {
                        inlineDisplay: cancelBtn.style.display,
                        computedDisplay: computed.display,
                        computedVisibility: computed.visibility,
                        rect: { width: rect.width, height: rect.height, top: rect.top },
                        isVisible: isVisible
                    });
                    if (!isVisible) {
                        console.error('❌ КРИТИЧЕСКАЯ ОШИБКА: Кнопка не видна после установки стилей!');
                    }
                }, 100);
            } else {
                console.error('❌ КРИТИЧЕСКАЯ ОШИБКА: Кнопка cancelGenerationBtn не найдена в DOM!');
            }
            
            // Останавливаем предыдущий таймер, если есть
            stopGenerationTracking();
            lastKnownGenerationPhase = null;
            lastKnownGenerationProgress = 0;
            lastKnownGenerationAgent = 'Инициализация...';
            
            // Запускаем таймер
            generationStartTime = Date.now();
            updateTimer(); // Обновляем сразу
            
            // Запускаем таймер с улучшенным механизмом обновления
            startTimer();
            
            // Показываем область логов
            const generationLogs = document.getElementById('generationLogs');
            const logContent = document.getElementById('logContent');
            if (generationLogs && logContent) {
                generationLogs.style.display = 'block';
                const methodologyLiveStatus = document.getElementById('methodologyLiveStatus');
                if (methodologyLiveStatus) {
                    methodologyLiveStatus.style.display = 'none';
                    methodologyLiveStatus.innerHTML = '';
                }
                hideMethodologyReviewActions();
                logContent.innerHTML = '';
                
                // Создаем прогресс-бар
                let progressBarId = null;
                if (window.loading) {
                    progressBarId = window.loading.createProgressBar('logContent', 'Прогресс генерации');
                }
                
                // Добавляем spinner
                const spinnerId = window.loading ? window.loading.showSpinner('logContent', 'Генерация проекта...') : null;
                
                if (!window.loading) {
                    logContent.innerHTML = '<div class="generation-activity"><span class="generation-activity-dot"></span><span>Генерация проекта...</span></div>';
                }
                
                // Сохраняем ID для последующего обновления
                window.currentProgressBarId = progressBarId;
                window.currentSpinnerId = spinnerId;
            }
            
            // Сбрасываем отображение агента
            const agentElement = document.getElementById('currentAgent');
            if (agentElement) {
                agentElement.textContent = 'Инициализация...';
            }
            
            try {
                // Собираем данные формы
                const directionValue = document.getElementById('direction')?.value || '';
                const thematicBlockValue = document.getElementById('thematicBlock')?.value || document.getElementById('curriculumBlock')?.value || '';
                
                const seed = {
                    language: document.getElementById('language').value,
                    project_type: document.getElementById('projectType').value,
                    // Новое поле direction
                    direction: directionValue !== 'ADD' ? directionValue : '',
                    // thematic_block теперь берется из УП или из direction для обратной совместимости
                    thematic_block: thematicBlockValue || directionValue,
                    audience_level: document.getElementById('audienceLevel').value,
                    required_tools: document.getElementById('requiredTools').value.split(',').map(s => s.trim()).filter(s => s),
                    title_seed: document.getElementById('titleSeed').value,
                    project_description: document.getElementById('projectDescription').value,
                    learning_outcomes: document.getElementById('learningOutcomes').value.split('\n').map(s => s.trim()).filter(s => s),
                    skills: document.getElementById('skills').value.split('\n').map(s => s.trim()).filter(s => s),
                    sjm: document.getElementById('storytelling')?.value.trim() || null,
                    methodology_human_review: getChecked('methodologyHumanReview'),
                };
                
                // === НОВЫЕ ПОЛЯ ИЗ УП ===
                
                // Контекст из УП (если есть)
                if (currentCurriculumContext) {
                    seed.curriculum_context = currentCurriculumContext;
                } else {
                    // Пробуем восстановить из sessionStorage
                    try {
                        const savedContext = sessionStorage.getItem('curriculum_context');
                        if (savedContext) {
                            seed.curriculum_context = JSON.parse(savedContext);
                        }
                    } catch (e) {
                        console.warn('Не удалось восстановить curriculum_context');
                    }
                }
                
                // Если есть выбранный проект из УП, добавляем его метаданные
                const curriculumProjectSelect = document.getElementById('curriculumProject');
                if (curriculumProjectSelect && curriculumProjectSelect.value) {
                    const selectedOption = curriculumProjectSelect.selectedOptions[0];
                    if (selectedOption && selectedOption.dataset.project) {
                        try {
                            const projectData = JSON.parse(selectedOption.dataset.project);
                            
                            // Название на платформе
                            if (projectData.platform_name) {
                                seed.platform_name = projectData.platform_name;
                            }
                            
                            // Ссылка на GitLab
                            if (projectData.gitlab_link) {
                                seed.gitlab_link = projectData.gitlab_link;
                            }
                            
                            // Трудоемкость
                            if (projectData.workload_hours) {
                                seed.workload_hours = projectData.workload_hours;
                            }
                            if (projectData.workload_days) {
                                seed.workload_days = projectData.workload_days;
                            }
                            
                            // XP
                            if (projectData.xp) {
                                seed.xp_reward = projectData.xp;
                            }
                            
                            // Дополнительные материалы
                            if (projectData.additional_materials) {
                                seed.additional_materials = projectData.additional_materials;
                            }
                            
                            // Подсказки для эксперта
                            if (projectData.expert_notes) {
                                seed.expert_notes = projectData.expert_notes;
                            }

                            // Сторителлинг из УП, если поле формы не заполнено вручную
                            if (!seed.sjm && projectData.sjm) {
                                seed.sjm = projectData.sjm;
                            }
                        } catch (e) {
                            console.warn('Ошибка парсинга данных проекта из УП:', e);
                        }
                    }
                }
                
                if (seed.project_type === 'group') {
                    seed.group_size = parseInt(document.getElementById('groupSize').value);
                }
                
                const repoBaseUrl = document.getElementById('repoBaseUrl').value.trim();
                if (repoBaseUrl) {
                    seed.repo_base_url = repoBaseUrl;
                }
                
                const repoPathTemplate = document.getElementById('repoPathTemplate').value.trim();
                if (repoPathTemplate) {
                    seed.repo_path_template = repoPathTemplate;
                }
                
                if (getChecked('generateBonus')) {
                    const bonusWishValue = document.getElementById('bonusWish')?.value.trim() || '';
                    seed.bonus_wish = bonusWishValue || ""; // Пустая строка вместо null, чтобы генерация работала
                } else {
                    seed.bonus_wish = null; // Если чекбокс не включен, устанавливаем null
                }
                
                // Загружаем файлы трека
                const trackFilesInput = document.getElementById('trackFiles');
                const formData = new FormData();
                formData.append('seed', JSON.stringify(seed));
                
                if (trackFilesInput && trackFilesInput.files.length > 0) {
                    for (const file of trackFilesInput.files) {
                        formData.append('track_files', file);
                    }
                }
                
                const token = localStorage.getItem('auth_token');
                
                // Запускаем генерацию
                // Таймер уже работает в setInterval
                // Используем AbortController для возможности отмены (на будущее)
                const controller = new AbortController();
                
                const response = await fetch(`${API_URL}/generate`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData,
                    signal: controller.signal
                });
                
                if (!response.ok) {
                    if (response.status === 401) {
                        // Токен истек или невалиден - перенаправляем на страницу входа
                        localStorage.removeItem('auth_token');
                        localStorage.removeItem('user_id');
                        localStorage.removeItem('username');
                        localStorage.removeItem('session_id');
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json().catch(() => ({ detail: 'Ошибка генерации' }));
                    throw new Error(error.detail || `Ошибка ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                currentRequestId = data.request_id;
                currentSeed = seed; // Сохраняем данные формы
                
                // Сохраняем исходное время старта, чтобы таймер не прыгал после ответа API.
                if (!generationStartTime) {
                    generationStartTime = Date.now();
                }
                saveGenerationState();
                
                // Показываем кнопку остановки СРАЗУ после получения request_id
                showCancelButton();
                
                // Обновляем текущего агента сразу после начала генерации
                await updateCurrentAgent(currentRequestId);
                
                // Начинаем polling статуса генерации
                pollGenerationStatus(currentRequestId);
                
            } catch (error) {
                // Останавливаем таймер при ошибке
                stopGenerationTracking();
                
                if (statusPollInterval) {
                    clearInterval(statusPollInterval);
                    statusPollInterval = null;
                }
                
                if (logContent) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(logContent, `Ошибка: ${error.message}`);
                    } else {
                        logContent.textContent = `❌ Ошибка: ${error.message}`;
                    }
                }
                
                // Восстанавливаем кнопку и скрываем кнопку остановки
                const btn = document.getElementById('generateBtn');
                if (btn) {
                    if (window.loading) {
                        window.loading.setButtonLoading(btn, false, '🚀 Сгенерировать');
                    } else {
                        btn.disabled = false;
                        btn.textContent = '🚀 Сгенерировать';
                    }
                }
                hideCancelButton();
                
                // Удаляем spinner и progress bar
                if (window.loading) {
                    if (window.currentSpinnerId) {
                        window.loading.hideSpinner(window.currentSpinnerId);
                    }
                    if (window.currentProgressBarId) {
                        window.loading.removeProgressBar(window.currentProgressBarId);
                    }
                }
                
                // Показываем toast с ошибкой
                if (window.toast) {
                    window.toast.error(`Ошибка генерации: ${error.message}`);
                }
                // Не скрываем загрузчик при ошибке, чтобы пользователь видел сообщение об ошибке
            }
        }
        
        async function cancelGeneration() {
            if (window.modal) {
                const confirmed = await window.modal.confirm(
                    'Аварийная остановка',
                    'Вы уверены, что хотите остановить генерацию? Текущий процесс будет прерван.',
                    'Остановить',
                    'Отмена'
                );
                if (!confirmed) return;
            }
            if (!currentRequestId) {
                alert('Нет активной генерации для остановки');
                return;
            }
            
            const cancelBtn = document.getElementById('cancelGenerationBtn');
            if (cancelBtn) {
                cancelBtn.disabled = true;
                cancelBtn.textContent = '⏳ Остановка...';
            }
            
            try {
                const token = localStorage.getItem('auth_token');
                const response = await fetch(`${API_URL}/generate/cancel/${currentRequestId}`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                
                if (!response.ok) {
                    if (response.status === 401) {
                        localStorage.removeItem('auth_token');
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json().catch(() => ({ detail: 'Ошибка остановки' }));
                    throw new Error(error.detail || `Ошибка ${response.status}`);
                }
                
                const data = await response.json();
                if (data.success) {
                    // Останавливаем отслеживание
                    stopGenerationTracking();
                    
                    // Обновляем UI
                    const logContent = document.getElementById('logContent');
                    if (logContent) {
                        logContent.innerHTML = '<div class="warning-msg">🛑 Генерация остановлена пользователем</div>';
                    }
                    
                    const btn = document.getElementById('generateBtn');
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = '🚀 Сгенерировать';
                    }
                    
                    hideCancelButton();
                    
                    // Останавливаем polling
                    if (statusPollInterval) {
                        clearInterval(statusPollInterval);
                        statusPollInterval = null;
                    }
                    
                    alert('Генерация успешно остановлена');
                }
            } catch (error) {
                console.error('Ошибка при остановке генерации:', error);
                alert(`Ошибка при остановке генерации: ${error.message}`);
                
                if (cancelBtn) {
                    cancelBtn.disabled = false;
                    cancelBtn.textContent = '🛑 Аварийная остановка генерации';
                }
            }
        }

        async function handleReadmeFileSelect(event) {
            const fileInput = event.target;
            const file = fileInput.files && fileInput.files[0];
            // Ищем элемент для отображения имени файла (может быть на разных страницах)
            const label = document.getElementById('readmeFileNameChecker') || 
                         document.getElementById('readmeFileName');
            if (!file) {
                if (label) label.textContent = '';
                return;
            }
            if (label) {
                label.textContent = `Выбран файл: ${file.name}`;
            }
        }

        async function checkReadme() {
            const checkBtn = document.getElementById('checkBtn');
            const noResults = document.getElementById('noResults');
            const resultsArea = document.getElementById('resultsArea');
            
            try {
                const fileInput = document.getElementById('readmeFile');
                if (!fileInput || !fileInput.files || !fileInput.files[0]) {
                    alert('Пожалуйста, выберите файл README.md для проверки.');
                    return;
                }
                const file = fileInput.files[0];
                const text = await file.text();
                const markdown = text.trim();
                if (!markdown) {
                    alert('Файл README пуст. Загрузите непустой файл.');
                    return;
                }

                // Показываем индикатор загрузки
                if (checkBtn) {
                    checkBtn.disabled = true;
                    const spinnerHtml = '<span style="display: inline-block; width: 16px; height: 16px; margin-right: 8px; vertical-align: middle; border: 2px solid rgba(118, 75, 162, 0.3); border-top: 2px solid #64ffda; border-radius: 50%; animation: spin 1s linear infinite;"></span>';
                    checkBtn.innerHTML = spinnerHtml + ' Проверка...';
                }
                
                // Скрываем результаты
                if (resultsArea) {
                    resultsArea.style.display = 'none';
                }
                
                // Показываем индикатор загрузки в noResults
                if (noResults) {
                    // Убеждаемся, что элемент видим
                    noResults.style.display = 'block';
                    noResults.style.visibility = 'visible';
                    noResults.style.opacity = '1';
                    noResults.className = 'info-box';
                    // Устанавливаем содержимое с индикатором загрузки
                    noResults.innerHTML = `
                        <div style="text-align: center; padding: 2rem; color: #64ffda;">
                            <div class="spinner" style="border: 4px solid rgba(118, 75, 162, 0.3); border-top: 4px solid #64ffda; border-radius: 50%; width: 50px; height: 50px; animation: spin 1s linear infinite; margin: 0 auto 1rem;"></div>
                            <p style="margin-top: 1rem; font-size: 1.1rem; color: #64ffda;">🔄 Проверка критериев...</p>
                        </div>
                    `;
                    // Принудительно обновляем отображение
                    noResults.offsetHeight; // Trigger reflow
                }

                // Язык всегда русский для проверки README
                const language = 'ru';

                const loTextarea = document.getElementById('learningOutcomes');
                const loRaw = loTextarea ? loTextarea.value : '';
                const learningOutcomes = loRaw
                    .split('\n')
                    .map(s => s.trim())
                    .filter(Boolean);

                const body = {
                    markdown,
                    language,
                    learning_outcomes: learningOutcomes.length ? learningOutcomes : null,
                };

                const response = await fetch(`${API_URL}/readme/check`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify(body),
                });

                if (!response.ok) {
                    if (response.status === 401) {
                        // Токен истек или невалиден - перенаправляем на страницу входа
                        localStorage.removeItem('auth_token');
                        localStorage.removeItem('user_id');
                        localStorage.removeItem('username');
                        localStorage.removeItem('session_id');
                        alert('Ваша сессия истекла. Пожалуйста, войдите в систему снова.');
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json().catch(() => ({ detail: 'Ошибка проверки README' }));
                    throw new Error(error.detail || `Ошибка ${response.status}: ${response.statusText}`);
                }

                const data = await response.json();

                // Скрываем индикатор загрузки и показываем результаты
                if (checkBtn) {
                    checkBtn.disabled = false;
                    checkBtn.innerHTML = '✅ Проверить README';
                }
                
                // Скрываем индикатор загрузки
                if (noResults) {
                    noResults.style.display = 'none';
                }
                
                // Показываем результаты
                if (resultsArea) {
                    resultsArea.style.display = 'block';
                }

                const warningsArea = document.getElementById('warningsArea');
                if (warningsArea) {
                    if (window.sanitize) {
                        warningsArea.innerHTML = '<div class="success-msg">✅ Проверка выполнена успешно</div>';
                    } else {
                        warningsArea.textContent = '✅ Проверка выполнена успешно';
                    }
                }

                // Сохраняем результаты в sessionStorage
                const checkerResults = {
                    rubric: data.rubric,
                    text_stats: data.text_stats,
                    markdown: markdown,
                    timestamp: Date.now()
                };
                sessionStorage.setItem('checker_results', JSON.stringify(checkerResults));
                
                // Показываем кнопку очистки
                const clearBtn = document.getElementById('clearResultsBtn');
                if (clearBtn) {
                    clearBtn.style.display = 'inline-block';
                }

                if (data.rubric) {
                    // Сохраняем rubric для фильтров
                    window.checkerRubric = data.rubric;
                    // Используем новый контейнер для исходных критериев
                    displayMetrics(data.rubric, 'checkerMetricsOriginal');
                    // Обновляем отображение, если есть переключатель версий
                    if (typeof window.updateCheckerMetricsDisplay === 'function') {
                        window.updateCheckerMetricsDisplay();
                    }
                }
                if (data.text_stats) {
                    displayReport({ text_stats: data.text_stats }, 'checkerReport');
                }

                // Превью README
                displayMarkdown(markdown, 'readmePreview');

                // Активируем вкладку "Критерии" по умолчанию
                const metricsTab = Array.from(document.querySelectorAll('.tab')).find(btn =>
                    btn.textContent.includes('Критерии'),
                );
                showTab('metrics', metricsTab || null);
                
                // Показываем кнопку улучшения README всегда, предупреждение - только при оценке < 70%
                const improveSection = document.getElementById('improveReadmeSection');
                const improveWarning = document.getElementById('improveReadmeWarning');
                
                if (improveSection) {
                    // Кнопка всегда показывается
                    improveSection.style.display = 'block';
                    // Сохраняем markdown для улучшения
                    window.originalReadmeForImprovement = markdown;
                    
                    // Предупреждение показывается только при оценке < 70%
                    if (improveWarning && data.rubric) {
                        const totalScore = data.rubric.total || 0;
                        const maxScore = data.rubric.max_score || 100;
                        const percentage = maxScore > 0 ? (totalScore / maxScore) * 100 : 0;
                        
                        if (percentage < 70) {
                            improveWarning.style.display = 'block';
                        } else {
                            improveWarning.style.display = 'none';
                        }
                    } else if (improveWarning) {
                        improveWarning.style.display = 'none';
                    }
                }
            } catch (error) {
                console.error('Ошибка проверки README:', error);
                
                // Восстанавливаем кнопку при ошибке
                if (checkBtn) {
                    checkBtn.disabled = false;
                    checkBtn.innerHTML = '✅ Проверить README';
                }
                if (noResults) {
                    noResults.style.display = 'block';
                    noResults.innerHTML = '<p>Загрузите README и нажмите «Проверить», чтобы увидеть результаты.</p>';
                }
                
                alert(`Ошибка проверки README: ${error.message}`);
            }
        }
        
        function renderMethodologyPanel(payload, containerId = 'methodologyContent', options = {}) {
            window.methodologyPanel?.render(payload, containerId, options);
        }

        function showMethodologyReviewActions(requestId, message = '') {
            window.methodologyPanel?.showActions({ requestId, message });
        }

        function hideMethodologyReviewActions() {
            window.methodologyPanel?.hideActions();
        }

        function displayResults(data) {
            // Проверяем наличие результата
            if (!data || !data.result) {
                console.error('❌ displayResults: отсутствует результат', data);
                const noResults = document.getElementById('noResults');
                if (noResults) {
                    noResults.style.display = 'block';
                    noResults.textContent = 'Ошибка: результат генерации отсутствует';
                }
                const logContent = document.getElementById('logContent');
                if (logContent) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(logContent, 'Результат генерации отсутствует в ответе сервера');
                    } else {
                        logContent.textContent = '❌ Результат генерации отсутствует в ответе сервера';
                    }
                }
                return;
            }
            
            // Проверяем тип результата
            if (typeof data.result !== 'object') {
                console.error('❌ displayResults: результат не является объектом', typeof data.result, data.result);
                const noResults = document.getElementById('noResults');
                if (noResults) {
                    noResults.style.display = 'block';
                    noResults.textContent = 'Ошибка: неверный формат результата';
                }
                return;
            }
            
            // Проверяем наличие markdown
            if (typeof data.result.markdown !== 'string') {
                console.error('❌ displayResults: markdown отсутствует или имеет неверный тип', typeof data.result.markdown, data.result);
                const noResults = document.getElementById('noResults');
                if (noResults) {
                    noResults.style.display = 'block';
                    noResults.textContent = 'Ошибка: результат не содержит markdown';
                }
                return;
            }
            
            document.getElementById('noResults').style.display = 'none';
            document.getElementById('resultsArea').style.display = 'block';
            
            // Предупреждения
            const warningsArea = document.getElementById('warningsArea');
            const filteredWarnings = (data.warnings || []).filter(w => !w.startsWith('ℹ️ План практики'));
            if (filteredWarnings.length > 0) {
                // Экранируем предупреждения перед вставкой
                const escapedWarnings = filteredWarnings.map(w => {
                    const escaped = window.sanitize ? window.sanitize.escapeHtml(w) : w;
                    return `<li>${escaped}</li>`;
                }).join('');
                const warningsHtml = `
                    <div class="warnings">
                        <strong>⚠️ Предупреждения:</strong>
                        <ul>
                            ${escapedWarnings}
                        </ul>
                    </div>
                `;
                if (window.sanitize) {
                    window.sanitize.safeSetHTML(warningsArea, warningsHtml);
                } else {
                    warningsArea.innerHTML = warningsHtml;
                }
            } else {
                if (window.sanitize) {
                    warningsArea.innerHTML = '<div class="success-msg">✅ Генерация завершена успешно!</div>';
                } else {
                    warningsArea.textContent = '✅ Генерация завершена успешно!';
                }
            }

            const plan = data.result && data.result.task_plan ? data.result.task_plan : null;
            if (plan) {
                const complexityCopy = {
                    easy: 'лёгкий уровень',
                    medium: 'средний уровень',
                    hard: 'повышенный уровень'
                };
                const complexityText = complexityCopy[plan.complexity] || plan.complexity || 'автоматически подобранный уровень';
                const planText = `📊 План практики подготовлен: ${plan.tasks_count} задач, ${complexityText}. Подробности во вкладке «Практика».`;
                const escapedPlanText = window.sanitize ? window.sanitize.escapeHtml(planText) : planText;
                const planHtml = `<div class="info-box">${escapedPlanText}</div>`;
                if (window.sanitize) {
                    warningsArea.insertAdjacentHTML('beforeend', planHtml);
                } else {
                    warningsArea.innerHTML += planHtml;
                }
            }
            
            // README - с дополнительной проверкой
            const markdown = data.result?.markdown;
            if (typeof markdown !== 'string') {
                console.error('❌ displayResults: markdown отсутствует или не является строкой', typeof markdown, data.result);
                const readmeContainer = document.getElementById('readmeContent');
                if (readmeContainer) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(readmeContainer, 'Ошибка: markdown отсутствует в результате генерации');
                    } else {
                        readmeContainer.textContent = '❌ Ошибка: markdown отсутствует в результате генерации';
                    }
                }
            } else {
                displayMarkdown(markdown, 'readmeContent');
            }
            
            // Переведенный README - проверяем наличие translated_markdown
            const translatedMarkdown = data.result?.translated_markdown || data.result?.report_json?.translated_markdown || null;
            currentTranslatedMarkdown = translatedMarkdown; // Сохраняем в глобальную переменную
            if (translatedMarkdown && translatedMarkdown !== markdown) {
                const translatedTab = document.getElementById('translatedTab');
                const translatedContainer = document.getElementById('translatedContent');
                if (translatedTab && translatedContainer) {
                    translatedTab.style.display = 'inline-block';
                    displayMarkdown(translatedMarkdown, 'translatedContent');
                }
            } else {
                const translatedTab = document.getElementById('translatedTab');
                if (translatedTab) {
                    translatedTab.style.display = 'none';
                }
            }
            
            // Метрики - проверяем разные возможные пути к данным
            const rubric = data.result?.rubric || data.result?.report_json?.rubric || null;
            if (rubric) {
                window.currentRubric = rubric;
                originalRubric = rubric; // Сохраняем оригинальные метрики
                displayMetrics(rubric, 'metricsContentOriginal');
                // Скрываем переключатель, так как еще нет перегенерированной версии
                const metricsSwitcher = document.getElementById('metricsVersionSwitcher');
                if (metricsSwitcher) {
                    metricsSwitcher.style.display = 'none';
                }
            } else {
                // Если метрики отсутствуют, показываем сообщение
                const metricsContainer = document.getElementById('metricsContentOriginal');
                if (metricsContainer) {
                    metricsContainer.innerHTML = '<div class="info-box">Метрики будут доступны после завершения генерации</div>';
                }
            }
            
            // Отчет - проверяем разные возможные пути к данным
            const textStats = data.result?.text_stats || data.result?.report_json?.text_stats || {};
            if (data.result && (textStats && Object.keys(textStats).length > 0)) {
                originalTextStats = textStats; // Сохраняем оригинальную статистику
                displayReport({ text_stats: textStats }, 'reportContentOriginal');
                // Скрываем переключатель, так как еще нет перегенерированной версии
                const reportSwitcher = document.getElementById('reportVersionSwitcher');
                if (reportSwitcher) {
                    reportSwitcher.style.display = 'none';
                }
            } else {
                // Если статистика отсутствует, показываем сообщение
                const reportContainer = document.getElementById('reportContentOriginal');
                if (reportContainer) {
                    reportContainer.innerHTML = '<div class="info-box">Отчет будет доступен после завершения генерации</div>';
                }
            }
            
            // Context analysis - проверяем разные возможные пути к данным
            const contextAnalysis = data.result?.context_analysis || data.result?.report_json?.context_analysis || null;
            const contextContainer = document.getElementById('contextContent');
            if (contextAnalysis && contextContainer) {
                displayContextAnalysis(contextAnalysis);
            } else if (contextContainer) {
                contextContainer.innerHTML = '<div class="info-box">Анализ контекста будет доступен после завершения генерации</div>';
            }
            
            // Обновляем кнопку скачивания
            document.getElementById('downloadBtn').onclick = () => downloadResults();
            
            // Вкладка Практика: подробный вывод плана и CriticAgent
            renderPracticeTab(data.result);
            renderGeneratedDataTab(data.result);

            // Вкладка Методолог: gate decisions и per-phase замечания
            const methodologyPayload = data.methodology || data.result?.methodology_gate || {
                summary: data.result?.methodology_gate_summary,
                decisions: data.result?.methodology_gate_decisions
            };
            if (data.result?.methodology_revision_results) {
                methodologyPayload.methodology_revision_results = data.result.methodology_revision_results;
            }
            renderMethodologyPanel(methodologyPayload, 'methodologyContent');
            activateResultTab('readme');
        }

        function activateResultTab(tabName) {
            const tabButton = [...document.querySelectorAll('#resultsArea > .tabs .tab')]
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

        function renderPracticeTab(result) {
            const planContainer = document.getElementById('practicePlanDetails');
            const criticContainer = document.getElementById('practiceCriticIssues');
            if (!planContainer && !criticContainer) return;

            const plan = result && result.task_plan ? result.task_plan : null;
            if (planContainer) {
                if (!plan) {
                    planContainer.innerHTML = '<div>План практики отсутствует.</div>';
                } else {
                    const ctx = plan.curriculum_context || {};
                    const prevTitles = (ctx.previous_nodes || []).map(n => n.title).slice(0, 2);
                    const nextTitles = (ctx.next_nodes || []).map(n => n.title).slice(0, 2);
                    const skillsToPrepare = (ctx.skills_to_prepare || []).slice(0, 4);
                    const progress = typeof ctx.progress_ratio === 'number'
                        ? Math.round(ctx.progress_ratio * 100)
                        : null;
                    const complexityCopy = {
                        easy: 'мягкий вход',
                        medium: 'сбалансированная нагрузка',
                        hard: 'интенсивный уровень'
                    };
                    const complexityText = complexityCopy[plan.complexity] || 'автоподбор сложности';
                    const tasksWord = plan.tasks_count === 1 ? 'задача' : (plan.tasks_count >= 5 ? 'задач' : 'задачи');

                    const lines = [
                        `Запланировано ${plan.tasks_count} ${tasksWord}: ${complexityText}.`,
                    ];
                    if (plan.explanation) {
                        lines.push(plan.explanation);
                    } else if (plan.rationale) {
                        lines.push(plan.rationale);
                    } else {
                        lines.push('Уровень рассчитан по истории трека и уровню аудитории.');
                    }

                    if (ctx.graph_available) {
                        if (prevTitles.length) {
                            lines.push(`Учли предыдущие проекты: ${prevTitles.join(', ')}.`);
                        }
                        if (skillsToPrepare.length) {
                            lines.push(`Проект подготавливает навыки: ${skillsToPrepare.join(', ')}.`);
                        }
                        if (nextTitles.length) {
                            lines.push(`Следующий шаг после проекта: ${nextTitles.join(', ')}.`);
                        }
                        if (progress !== null) {
                            lines.push(`Прогресс по треку ≈ ${progress}%.`);
                        }
                    }

                    let html = lines.map(text => {
                        const escaped = window.sanitize ? window.sanitize.escapeHtml(text) : text;
                        return `<p>${escaped}</p>`;
                    }).join('');
                    const stubFiles = result && result.assets && Array.isArray(result.assets.files) && result.assets.files.length;
                    if (stubFiles) {
                        const stubText = `Для ссылок из заданий автоматически добавлены ${stubFiles} заготовок файлов в архив.`;
                        const escapedStub = window.sanitize ? window.sanitize.escapeHtml(stubText) : stubText;
                        html += `<p>${escapedStub}</p>`;
                    }
                    if (window.sanitize) {
                        window.sanitize.safeSetHTML(planContainer, html);
                    } else {
                        planContainer.innerHTML = html;
                    }
                }
            }


            if (criticContainer) {
                const issues = result && Array.isArray(result.practice_critic_issues)
                    ? result.practice_critic_issues
                    : [];
                if (!issues.length) {
                    if (window.sanitize) {
                        criticContainer.textContent = 'Критичных замечаний CriticAgent не найдено.';
                    } else {
                        criticContainer.innerHTML = '<div>Критичных замечаний CriticAgent не найдено.</div>';
                    }
                } else {
                    const items = issues.map(issue => {
                        const sev = (issue.severity || 'warning').toLowerCase();
                        const cls = `severity-${sev}`;
                        const taskIndex = typeof issue.task_index === 'number' && issue.task_index > 0
                            ? `Задача ${issue.task_index}`
                            : 'Global';
                        // Экранируем все пользовательские данные
                        const escapedTaskIndex = window.sanitize ? window.sanitize.escapeHtml(taskIndex) : taskIndex;
                        const escapedKind = window.sanitize ? window.sanitize.escapeHtml(issue.kind || '') : (issue.kind || '');
                        const escapedSeverity = window.sanitize ? window.sanitize.escapeHtml(issue.severity || '') : (issue.severity || '');
                        const escapedMessage = window.sanitize ? window.sanitize.escapeHtml(issue.message || '') : (issue.message || '');
                        const escapedSuggestion = issue.suggestion ? (window.sanitize ? window.sanitize.escapeHtml(issue.suggestion) : issue.suggestion) : '';
                        return `
                            <li class="${cls}">
                                <div class="issue-header">
                                    <span>${escapedTaskIndex}</span>
                                    <span>${escapedKind} · ${escapedSeverity}</span>
                                </div>
                                <div class="issue-message">${escapedMessage}</div>
                                ${escapedSuggestion ? `<div class="issue-suggestion">💡 ${escapedSuggestion}</div>` : ''}
                            </li>
                        `;
                    }).join('');
                    if (window.sanitize) {
                        window.sanitize.safeSetHTML(criticContainer, `<ul>${items}</ul>`);
                    } else {
                        criticContainer.innerHTML = `<ul>${items}</ul>`;
                    }
                }
            }
        }
        
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
                    container.textContent = '❌ Ошибка: библиотека marked.js не загружена';
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
            hydrateLocalImages(container);
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

        function hydrateLocalImages(root) {
            if (!root || !currentResult || !currentResult.assets) {
                return;
            }
            const assets = currentResult.assets;
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
        
        function displayMetrics(rubric, containerId = null) {
            // Определяем контейнер: если не указан, используем текущую активную версию
            let container;
            if (containerId) {
                container = document.getElementById(containerId);
            } else {
                // Используем контейнер в зависимости от текущей версии
                if (currentMetricsVersion === 'original') {
                    container = document.getElementById('metricsContentOriginal');
                } else {
                    container = document.getElementById('metricsContentRegen');
                }
            }
            if (!container) {
                console.error('Контейнер не найден для displayMetrics:', containerId);
                return;
            }
            
            // Убеждаемся, что контейнер видим (если он внутри видимой вкладки)
            const containerStyle = window.getComputedStyle(container);
            const parentTab = container.closest('.tab-content');
            const parentTabStyle = parentTab ? window.getComputedStyle(parentTab) : null;
            console.log(`displayMetrics: состояние контейнера ${containerId}:`, {
                containerDisplay: containerStyle.display,
                containerVisibility: containerStyle.visibility,
                parentTabDisplay: parentTabStyle?.display || 'no parent',
                parentTabVisibility: parentTabStyle?.visibility || 'no parent',
                containerInDOM: container.isConnected
            });
            
            // Проверяем наличие данных
            const hasItems = rubric && rubric.items && Array.isArray(rubric.items) && rubric.items.length > 0;
            
            const total = rubric?.total || 0;
            const max = rubric?.max_score || (hasItems ? rubric.items.length : 0);
            const percent = max > 0 ? (total / max * 100).toFixed(1) : 0;
            
            console.log(`displayMetrics вызвана для контейнера ${containerId}:`, {
                total,
                max,
                percent,
                itemsCount: hasItems ? rubric.items.length : 0,
                hasItems,
                rubricType: typeof rubric,
                itemsType: typeof rubric?.items,
                isArray: Array.isArray(rubric?.items),
                rubricKeys: rubric ? Object.keys(rubric) : null
            });
            
            let html = '';
            
            // Отображаем карточку с итоговым баллом только если есть данные
            if (hasItems) {
                html += `
                    <div class="metric-card">
                        <div class="metric-value">${total} / ${max}</div>
                        <div class="metric-label">Итоговый балл (${percent}%)</div>
                    </div>
                `;
            }
            
            // Фильтр (с уникальным ID для каждого контейнера) - всегда отображаем, если есть данные
            const filterId = containerId ? containerId.replace('Content', 'Filter') : 'metricsFilter';
            const activeFilter = window.currentFilter || currentFilter || 'all';
            
            console.log(`displayMetrics: создание фильтров для ${containerId}, hasItems: ${hasItems}, filterId: ${filterId}, activeFilter: ${activeFilter}`);
            
            if (hasItems) {
                const filterHtml = `
                    <div id="${filterId}" style="margin: 1.5rem 0; display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
                        <label style="color: #b8c5d6; font-weight: 600;">Фильтр:</label>
                        <button type="button" class="btn metrics-filter-btn" data-filter="all" style="cursor: pointer; width: auto; padding: 0.5rem 1rem; ${activeFilter === 'all' ? 'opacity: 1; font-weight: 600;' : 'opacity: 0.6;'}">Все</button>
                        <button type="button" class="btn metrics-filter-btn" data-filter="passed" style="cursor: pointer; width: auto; padding: 0.5rem 1rem; ${activeFilter === 'passed' ? 'opacity: 1; font-weight: 600;' : 'opacity: 0.6;'}">✅ Пройдено</button>
                        <button type="button" class="btn metrics-filter-btn" data-filter="failed" style="cursor: pointer; width: auto; padding: 0.5rem 1rem; ${activeFilter === 'failed' ? 'opacity: 1; font-weight: 600;' : 'opacity: 0.6;'}">❌ Не пройдено</button>
                    </div>
                `;
                html += filterHtml;
                console.log(`displayMetrics: фильтры добавлены в HTML, длина filterHtml: ${filterHtml.length}`);
            } else {
                console.warn(`displayMetrics: фильтры НЕ добавлены, так как hasItems = false для контейнера ${containerId}`);
            }
            
            if (hasItems) {
                // Фильтруем элементы используя activeFilter, устойчиво к типам score
                let filteredItems = rubric.items;
                const byFilter = (item) => {
                    const scoreVal = Number(item && typeof item.score !== 'undefined' ? item.score : 0);
                    if (activeFilter === 'passed') {
                        return scoreVal === 1;
                    }
                    if (activeFilter === 'failed') {
                        return scoreVal !== 1;
                    }
                    return true;
                };
                filteredItems = filteredItems.filter(byFilter);
                
                html += '<div class="table-container">';
                html += '<div style="margin-bottom: 0.5rem; display: flex; justify-content: flex-end;">';
                html += '<label style="display: flex; align-items: center; gap: 0.5rem; cursor: pointer; font-size: 0.9rem; color: #b8c5d6;">';
                html += '<input type="checkbox" id="toggleDescription" style="cursor: pointer;">';
                html += '<span>Показать описание</span>';
                html += '</label>';
                html += '</div>';
                html += '<table><thead><tr><th>№</th><th>Критерий</th><th class="description-column" style="display: none;">Описание</th><th>Оценка</th><th>Комментарии</th></tr></thead><tbody>';
                
                if (filteredItems.length === 0) {
                    html += '<tr><td colspan="5" style="text-align: center; padding: 2rem; color: #b8c5d6;">Нет критериев для отображения</td></tr>';
                } else {
                    filteredItems.forEach((item, idx) => {
                        const score = item.score === 1 ? '✅' : '❌';
                        
                        // Форматируем комментарии: для непройденных критериев используем список
                        let comments = '✅ Нет замечаний';
                        if (item.comments && item.comments.length > 0) {
                            if (item.score !== 1) {
                                // Для непройденных критериев - список с переносами строк
                                // Экранируем комментарии перед вставкой
                                const escapedComments = item.comments.map(c => {
                                    const escaped = window.sanitize ? window.sanitize.escapeHtml(c) : c;
                                    return `<li style="margin: 0.25rem 0;">${escaped}</li>`;
                                }).join('');
                                comments = '<ul style="margin: 0; padding-left: 1.5rem; text-align: left;">' + escapedComments + '</ul>';
                            } else {
                                // Для пройденных - просто через разделитель
                                // Экранируем комментарии
                                const escapedComments = item.comments.map(c => 
                                    window.sanitize ? window.sanitize.escapeHtml(c) : c
                                );
                                comments = escapedComments.join(' • ');
                            }
                        }
                        
                        // Экранируем пользовательские данные
                        const escapedTitle = window.sanitize ? window.sanitize.escapeHtml(item.title || '') : (item.title || '');
                        const escapedDescription = window.sanitize ? window.sanitize.escapeHtml(item.description || '—') : (item.description || '—');
                        
                        html += `
                            <tr>
                                <td>${item.id || idx + 1}</td>
                                <td><strong>${escapedTitle}</strong></td>
                                <td class="description-column" style="display: none;">${escapedDescription}</td>
                                <td>${score}</td>
                                <td>${comments}</td>
                            </tr>
                        `;
                    });
                }
                
                html += '</tbody></table></div>';
            } else {
                html += '<div class="info-box">Метрики недоступны (данные отсутствуют)</div>';
            }
            
            // Используем санитизацию для HTML контента
            console.log(`displayMetrics: вставляем HTML в контейнер ${containerId}, длина HTML: ${html.length}, hasItems: ${hasItems}`);
            console.log(`displayMetrics: HTML содержит фильтры: ${html.includes('metrics-filter-btn')}, содержит filterId ${filterId}: ${html.includes(filterId)}`);
            
            if (window.sanitize) {
                window.sanitize.safeSetHTML(container, html);
            } else {
                container.innerHTML = html;
            }
            
            // Проверяем, что кнопки фильтров действительно вставлены (с небольшой задержкой для DOM)
            setTimeout(() => {
                const filterContainer = document.getElementById(filterId);
                if (hasItems && filterContainer) {
                    const buttons = filterContainer.querySelectorAll('.metrics-filter-btn');
                    console.log(`✅ Контейнер фильтров найден: ${filterId}, найдено кнопок: ${buttons.length}`);
                    console.log(`Содержимое контейнера фильтров:`, filterContainer.innerHTML);
                    console.log(`Все дочерние элементы:`, Array.from(filterContainer.children).map(el => el.tagName + '.' + el.className));
                    
                    if (buttons.length === 0) {
                        console.error(`❌ Кнопки фильтров НЕ найдены в контейнере ${filterId}!`);
                        console.error(`Проверяем, не была ли удалена разметка санитизацией...`);
                        // Проверяем, есть ли вообще кнопки в контейнере
                        const allButtons = filterContainer.querySelectorAll('button');
                        console.log(`Всего кнопок в контейнере: ${allButtons.length}`);
                        allButtons.forEach((btn, idx) => {
                            console.log(`Кнопка ${idx}:`, {
                                className: btn.className,
                                hasMetricsFilterBtn: btn.classList.contains('metrics-filter-btn'),
                                dataFilter: btn.getAttribute('data-filter'),
                                text: btn.textContent
                            });
                        });
                    }
                } else if (hasItems && !filterContainer) {
                    console.error(`❌ Контейнер фильтров НЕ найден в DOM после вставки! filterId: ${filterId}, containerId: ${containerId}`);
                    console.error(`Контейнер ${containerId} содержимое (первые 1000 символов):`, container.innerHTML.substring(0, 1000));
                    // Ищем контейнер фильтров вручную
                    const allDivs = container.querySelectorAll('div');
                    console.log(`Всего div элементов в контейнере: ${allDivs.length}`);
                    allDivs.forEach((div, idx) => {
                        if (div.id && div.id.includes('Filter')) {
                            console.log(`Найден div с Filter в ID: ${div.id}`, div.innerHTML.substring(0, 200));
                        }
                    });
                }
            }, 100);
            
            // Обработчики событий для кнопок фильтров добавляются через делегирование событий
            // на уровне документа (см. код после функции loadGenerationState)
        }
        
        function toggleDescriptionColumn() {
            const checkbox = document.getElementById('toggleDescription');
            const columns = document.querySelectorAll('.description-column');
            if (checkbox && columns.length > 0) {
                const isVisible = checkbox.checked;
                columns.forEach(col => {
                    col.style.display = isVisible ? '' : 'none';
                });
            }
        }
        
        function displayReport(result, containerId = null) {
            // Определяем контейнер: если не указан, используем текущую активную версию
            let container;
            if (containerId) {
                container = document.getElementById(containerId);
            } else {
                // Используем контейнер в зависимости от текущей версии
                if (currentReportVersion === 'original') {
                    container = document.getElementById('reportContentOriginal');
                } else {
                    container = document.getElementById('reportContentRegen');
                }
            }
            if (!container) return;
            
            // Пытаемся получить статистику из разных мест
            const stats = result.text_stats || result.report_json?.text_stats || {};
            
            let html = '<h3>📝 Статистика по тексту</h3><div class="metrics-grid">';
            html += `<div class="metric-card"><div class="metric-value">${(stats.chars_total || stats.chars || 0).toLocaleString()}</div><div class="metric-label">Символов</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${(stats.words || 0).toLocaleString()}</div><div class="metric-label">Слов</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${(stats.sentences || 0).toLocaleString()}</div><div class="metric-label">Предложений</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${(stats.lines || 0).toLocaleString()}</div><div class="metric-label">Строк</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${(stats.tokens || 0).toLocaleString()}</div><div class="metric-label">Токенов</div></div>`;
            html += '</div>';
            
            // Дополнительная статистика, если есть
            if (stats.readability_index) {
                html += `<div class="metric-card" style="margin-top: 1rem;"><div class="metric-value">${stats.readability_index.toFixed(1)}</div><div class="metric-label">Индекс читаемости</div></div>`;
            }
            
            // Используем санитизацию для HTML контента
            if (window.sanitize) {
                window.sanitize.safeSetHTML(container, html);
            } else {
                container.innerHTML = html;
            }
        }
        
        function ensureRegenerationTemplate() {
            const field = document.getElementById('regenerationComments');
            if (!field) {
                return null;
            }
            const current = field.value.trim();
            if (!current.startsWith(REGENERATION_TEMPLATE)) {
                field.value = REGENERATION_TEMPLATE + (current ? `\n\n${current}` : '\n\n');
            }
            return field;
        }

        function insertRegenerationTemplate() {
            const field = ensureRegenerationTemplate();
            if (field) {
                field.focus();
                const len = field.value.length;
                field.setSelectionRange(len, len);
            }
        }

        function fillCommentsFromFailedCriteria() {
            try {
                // Получаем текущую активную версию метрик
                const metricsVersion = window.currentMetricsVersion || currentMetricsVersion || 'original';
                let rubric;
                if (metricsVersion === 'original' && originalRubric) {
                    rubric = originalRubric;
                } else if (metricsVersion === 'regenerated' && regeneratedRubric) {
                    rubric = regeneratedRubric;
                } else {
                    rubric = window.currentRubric || {};
                }
                
                if (!rubric || !rubric.items || rubric.items.length === 0) {
                    alert('⚠️ Нет данных критериев для заполнения. Сначала сгенерируйте контент.');
                    return;
                }
                
                // Собираем все комментарии из непройденных критериев
                const failedItems = rubric.items.filter(item => {
                    const score = item.score;
                    return score !== 1 && score !== '1' && score !== true;
                });
                const comments = [];
                
                failedItems.forEach((item) => {
                    if (item.comments && item.comments.length > 0) {
                        item.comments.forEach(comment => {
                            const titlePrefix = item.title ? `${item.title}: ` : '';
                            comments.push(`${titlePrefix}${comment}`);
                        });
                    }
                });
                
                if (comments.length === 0) {
                    alert('✅ Все критерии пройдены! Нет замечаний для заполнения.');
                    return;
                }
                
                // Заполняем поле комментариев (только комментарии, без нумерации)
                const commentsField = ensureRegenerationTemplate();
                if (!commentsField) {
                    alert('⚠️ Поле комментариев не найдено. Убедитесь, что вы находитесь на странице генерации.');
                    return;
                }
                const numbered = comments.map((comment, idx) => `${idx + 1}. ${comment}`).join('\n');
                const existingTail = commentsField.value.includes(REGENERATION_TEMPLATE)
                    ? commentsField.value.split(REGENERATION_TEMPLATE).slice(1).join(REGENERATION_TEMPLATE).trim()
                    : '';
                const suffix = existingTail ? `\n\n${existingTail}` : '';
                commentsField.value = `${REGENERATION_TEMPLATE}\n\n${numbered}${suffix}`;
                
                // Показываем сообщение
                alert(`✅ Заполнено ${comments.length} замечаний из непройденных критериев`);
            } catch (error) {
                console.error('Ошибка при заполнении комментариев:', error);
                alert('⚠️ Ошибка при заполнении комментариев: ' + error.message);
            }
        }
        
        function filterMetrics(filter) {
            console.log('filterMetrics вызвана с фильтром:', filter);
            if (!filter) {
                console.error('Фильтр не указан');
                return;
            }
            
            currentFilter = filter;
            window.currentFilter = filter;
            
            // Определяем, какую версию метрик использовать
            const metricsVersion = currentMetricsVersion || 'original';
            let rubric;
            let containerId = null;
            
            // Проверяем, используется ли checker (checkerMetricsOriginal или checkerMetricsImproved)
            const checkerOriginalContainer = document.getElementById('checkerMetricsOriginal');
            const checkerImprovedContainer = document.getElementById('checkerMetricsImproved');
            
            if (checkerOriginalContainer && checkerOriginalContainer.style.display !== 'none') {
                // Используем данные из checker (исходные)
                rubric = window.checkerRubric || {};
                containerId = 'checkerMetricsOriginal';
            } else if (checkerImprovedContainer && checkerImprovedContainer.style.display !== 'none') {
                // Используем данные из checker (улучшенные)
                rubric = window.improvedRubric || {};
                containerId = 'checkerMetricsImproved';
            } else {
                // Проверяем старый контейнер checkerMetrics (для обратной совместимости)
                const checkerContainer = document.getElementById('checkerMetrics');
                if (checkerContainer && checkerContainer.parentElement && checkerContainer.parentElement.style.display !== 'none') {
                    rubric = window.checkerRubric || {};
                    containerId = 'checkerMetrics';
                } else if (metricsVersion === 'original' && originalRubric) {
                    rubric = originalRubric;
                    containerId = 'metricsContentOriginal';
                } else if (metricsVersion === 'regenerated' && regeneratedRubric) {
                    rubric = regeneratedRubric;
                    containerId = 'metricsContentRegen';
                } else {
                    rubric = window.currentRubric || {};
                }
            }
            
            if (!rubric || !rubric.items) {
                console.error('Нет данных для фильтрации', { 
                    rubric, 
                    metricsVersion, 
                    originalRubric, 
                    regeneratedRubric, 
                    checkerRubric: window.checkerRubric,
                    improvedRubric: window.improvedRubric,
                    containerId
                });
                return;
            }
            
            // Отображаем в нужном контейнере
            if (containerId) {
                displayMetrics(rubric, containerId);
            } else if (metricsVersion === 'original') {
                displayMetrics(rubric, 'metricsContentOriginal');
            } else {
                displayMetrics(rubric, 'metricsContentRegen');
            }
        }
        
        function clearCheckerResults() {
            if (!confirm('Вы уверены, что хотите очистить результаты проверки?')) {
                return;
            }
            
            // Очищаем sessionStorage
            sessionStorage.removeItem('checker_results');
            
            // Очищаем глобальные переменные
            window.checkerRubric = null;
            
            // Скрываем результаты
            const resultsArea = document.getElementById('resultsArea');
            const noResults = document.getElementById('noResults');
            if (resultsArea) {
                resultsArea.style.display = 'none';
            }
            if (noResults) {
                noResults.style.display = 'block';
                noResults.innerHTML = '<p>Загрузите README и нажмите «Проверить», чтобы увидеть результаты.</p>';
            }
            
            // Скрываем кнопку очистки
            const clearBtn = document.getElementById('clearResultsBtn');
            if (clearBtn) {
                clearBtn.style.display = 'none';
            }
            
            // Очищаем контейнеры
            const checkerMetrics = document.getElementById('checkerMetrics');
            const checkerReport = document.getElementById('checkerReport');
            const readmePreview = document.getElementById('readmePreview');
            if (checkerMetrics) checkerMetrics.innerHTML = '';
            if (checkerReport) checkerReport.innerHTML = '';
            if (readmePreview) readmePreview.innerHTML = '';
        }
        
        function restoreCheckerResults() {
            try {
                const saved = sessionStorage.getItem('checker_results');
                if (!saved) {
                    return;
                }
                
                const results = JSON.parse(saved);
                if (!results.rubric && !results.text_stats) {
                    return;
                }
                
                // Восстанавливаем результаты
                const resultsArea = document.getElementById('resultsArea');
                const noResults = document.getElementById('noResults');
                const clearBtn = document.getElementById('clearResultsBtn');
                
                if (resultsArea && noResults) {
                    noResults.style.display = 'none';
                    resultsArea.style.display = 'block';
                }
                
                if (clearBtn) {
                    clearBtn.style.display = 'inline-block';
                }
                
                // Восстанавливаем данные
                if (results.rubric) {
                    window.checkerRubric = results.rubric;
                    // Используем новый контейнер для исходных критериев
                    displayMetrics(results.rubric, 'checkerMetricsOriginal');
                    // Обновляем отображение, если есть переключатель версий
                    if (typeof window.updateCheckerMetricsDisplay === 'function') {
                        window.updateCheckerMetricsDisplay();
                    }
                }
                if (results.text_stats) {
                    displayReport({ text_stats: results.text_stats }, 'checkerReport');
                }
                if (results.markdown) {
                    displayMarkdown(results.markdown, 'readmePreview');
                }
                
                // Показываем сообщение об успехе
                const warningsArea = document.getElementById('warningsArea');
                if (warningsArea) {
                    if (window.sanitize) {
                        warningsArea.innerHTML = '<div class="success-msg">✅ Результаты восстановлены из предыдущей проверки</div>';
                    } else {
                        warningsArea.textContent = '✅ Результаты восстановлены из предыдущей проверки';
                    }
                }
            } catch (error) {
                console.error('Ошибка восстановления результатов:', error);
            }
        }
        
        function displayContextAnalysis(contextAnalysis) {
            const container = document.getElementById('contextContent');
            if (!container) {
                return;
            }
            
            if (!contextAnalysis) {
                container.innerHTML = '<div class="info-box">Анализ контекста недоступен</div>';
                return;
            }
            
            let html = '<h3>🔍 Анализ контекста</h3>';
            
            // Статистика
            const metrics = contextAnalysis.metrics || {};
            html += '<div class="metrics-grid">';
            html += `<div class="metric-card"><div class="metric-value">${contextAnalysis.similar_projects_count || 0}</div><div class="metric-label">Соседних проектов</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${metrics.skills_match_count || 0}</div><div class="metric-label">Совпадений навыков</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${metrics.lo_match_count || 0}</div><div class="metric-label">Совпадений ЗУНов</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${metrics.projects_found || 0}</div><div class="metric-label">Найдено проектов</div></div>`;
            html += `<div class="metric-card"><div class="metric-value">${metrics.projects_filtered || 0}</div><div class="metric-label">Отфильтровано</div></div>`;
            if (metrics.min_order !== undefined && metrics.max_order !== undefined) {
                html += `<div class="metric-card"><div class="metric-value">${metrics.min_order}-${metrics.max_order}</div><div class="metric-label">Диапазон порядков</div></div>`;
            }
            html += '</div>';
            
            // Информация о поиске
            if (contextAnalysis.is_first_project) {
                html += '<div class="info-box">🆕 Это первый проект в тематическом блоке</div>';
            } else {
                html += `<div class="info-box">📚 Учтено ${contextAnalysis.similar_projects_count || 0} соседних проектов</div>`;
            }
            
            // Режим поиска
            if (contextAnalysis.search_mode) {
                html += `<div class="info-box">🔍 Режим анализа: ${contextAnalysis.search_mode === 'semantic' ? 'Семантический' : 'По учебному плану'}</div>`;
            }
            
            // Выравнивание навыков
            if (contextAnalysis.skills_alignment) {
                const skillsAlign = contextAnalysis.skills_alignment;
                const hasIntersection = skillsAlign.intersection && Array.isArray(skillsAlign.intersection) && skillsAlign.intersection.length > 0;
                const hasMissing = skillsAlign.missing && Array.isArray(skillsAlign.missing) && skillsAlign.missing.length > 0;
                
                if (hasIntersection || hasMissing) {
                    html += '<h4>📊 Выравнивание навыков</h4>';
                    html += '<div class="info-box">';
                    if (hasIntersection) {
                        html += `<strong>Совпадающие навыки (${skillsAlign.intersection.length}):</strong> ${skillsAlign.intersection.join(', ')}<br>`;
                    }
                    if (hasMissing) {
                        html += `<strong>Отсутствующие навыки (${skillsAlign.missing.length}):</strong> ${skillsAlign.missing.join(', ')}<br>`;
                    }
                    html += '</div>';
                } else {
                    // Если данных нет, показываем сообщение
                    html += '<h4>📊 Выравнивание навыков</h4>';
                    html += '<div class="info-box">Нет данных о выравнивании навыков</div>';
                }
            }
            
            // Выравнивание ЗУНов
            if (contextAnalysis.learning_outcomes_alignment) {
                const loAlign = contextAnalysis.learning_outcomes_alignment;
                html += '<h4>📚 Выравнивание ЗУНов</h4>';
                html += '<div class="info-box">';
                if (loAlign.continuation && loAlign.continuation.length > 0) {
                    html += `<strong>Продолжение (${loAlign.continuation.length}):</strong> ${loAlign.continuation.join('; ')}<br>`;
                }
                if (loAlign.new_outcomes && loAlign.new_outcomes.length > 0) {
                    html += `<strong>Новые ЗУНы (${loAlign.new_outcomes.length}):</strong> ${loAlign.new_outcomes.join('; ')}<br>`;
                }
                html += '</div>';
            }
            
            // Резюме контекста
            if (contextAnalysis.context_summary) {
                html += '<h4>📝 Резюме контекста</h4>';
                const escapedSummary = window.sanitize ? window.sanitize.escapeHtml(contextAnalysis.context_summary) : contextAnalysis.context_summary;
                html += `<div class="info-box">${escapedSummary}</div>`;
            }
            
            // Нарратив
            if (contextAnalysis.narrative_anchor) {
                html += '<h4>🔗 Нарративный якорь</h4>';
                const escapedAnchor = window.sanitize ? window.sanitize.escapeHtml(contextAnalysis.narrative_anchor) : contextAnalysis.narrative_anchor;
                html += `<div class="info-box">${escapedAnchor}</div>`;
            }
            
            // Соседние проекты
            if (contextAnalysis.similar_projects && contextAnalysis.similar_projects.length > 0) {
                html += '<h4>📋 Соседние проекты</h4>';
                html += '<div class="table-container"><table><thead><tr><th>Код</th><th>Название</th><th>Порядок</th><th>Навыки</th></tr></thead><tbody>';
                contextAnalysis.similar_projects.slice(0, 10).forEach(proj => {
                    const skills = proj.skills ? (Array.isArray(proj.skills) ? proj.skills.join(', ') : proj.skills) : '-';
                    // Экранируем все пользовательские данные
                    const code = window.sanitize ? window.sanitize.escapeHtml(proj.code || proj.code_name || '-') : (proj.code || proj.code_name || '-');
                    const title = window.sanitize ? window.sanitize.escapeHtml(proj.title || '-') : (proj.title || '-');
                    const order = window.sanitize ? window.sanitize.escapeHtml(String(proj.order || '-')) : String(proj.order || '-');
                    const escapedSkills = window.sanitize ? window.sanitize.escapeHtml(skills) : skills;
                    html += `
                        <tr>
                            <td><strong>${code}</strong></td>
                            <td>${title}</td>
                            <td>${order}</td>
                            <td>${escapedSkills}</td>
                        </tr>
                    `;
                });
                html += '</tbody></table></div>';
            }
            
            // Используем санитизацию для HTML контента
            if (window.sanitize) {
                window.sanitize.safeSetHTML(container, html);
            } else {
                container.innerHTML = html;
            }
        }
        
        async function regenerateContent() {
            const comments = document.getElementById('regenerationComments').value.trim();
            if (!comments) {
                alert('⚠️ Пожалуйста, введите комментарии по изменению README.');
                return;
            }
            
            if (!currentMarkdown) {
                alert('⚠️ Сначала сгенерируйте контент.');
                return;
            }
            
            // Проверяем наличие токена перед запросом
            const token = localStorage.getItem('auth_token');
            if (!token) {
                alert('⚠️ Требуется авторизация. Перенаправление на страницу входа...');
                // Очищаем sessionStorage при редиректе на авторизацию
                sessionStorage.removeItem('generation_state');
                window.location.href = '/';
                return;
            }
            
            // Показываем загрузчик при перегенерации
            const generationLogs = document.getElementById('generationLogs');
            const logContent = document.getElementById('logContent');
            if (generationLogs && logContent) {
                generationLogs.style.display = 'block';
                
                // Создаем spinner через loading manager
                if (window.loading) {
                    const spinnerId = window.loading.showSpinner('logContent', '🔄 Перегенерация контента...');
                    window.currentRegenSpinnerId = spinnerId;
                } else {
                    logContent.innerHTML = '<div class="loading"><div class="spinner"></div><p>🔄 Перегенерация контента...</p></div>';
                }
            }
            
            try {
                const response = await fetch(`${API_URL}/regenerate`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`
                    },
                    body: JSON.stringify({
                        original_request_id: currentRequestId,
                        original_md: currentMarkdown,
                        comments: comments,
                        language: document.getElementById('language').value
                    })
                });
                
                if (!response.ok) {
                    if (response.status === 401) {
                        // Токен истек или невалиден - перенаправляем на страницу входа
                        localStorage.removeItem('auth_token');
                        localStorage.removeItem('user_id');
                        localStorage.removeItem('username');
                        localStorage.removeItem('session_id');
                        // Очищаем sessionStorage при редиректе на авторизацию
                        sessionStorage.removeItem('generation_state');
                        window.location.href = '/';
                        return;
                    }
                    const error = await response.json().catch(() => ({ detail: 'Ошибка перегенерации' }));
                    throw new Error(error.detail || `Ошибка ${response.status}: ${response.statusText}`);
                }
                
                const data = await response.json();
                
                // ВАЖНО: Сохраняем оригинальные данные ДО обновления currentResult
                // Иначе currentResult.rubric уже будет перегенерированным
                if (!originalRubric && currentResult && currentResult.rubric) {
                    originalRubric = currentResult.rubric;
                    console.log('✅ originalRubric сохранен при перегенерации:', originalRubric.items?.length || 0, 'критериев');
                } else if (originalRubric) {
                    console.log('✅ originalRubric уже сохранен:', originalRubric.items?.length || 0, 'критериев');
                } else {
                    console.warn('⚠️ Не удалось сохранить originalRubric: currentResult.rubric отсутствует');
                }
                
                if (!originalTextStats && currentResult && currentResult.text_stats) {
                    originalTextStats = currentResult.text_stats;
                    console.log('✅ originalTextStats сохранен при перегенерации');
                } else if (originalTextStats) {
                    console.log('✅ originalTextStats уже сохранен');
                } else {
                    console.warn('⚠️ Не удалось сохранить originalTextStats: currentResult.text_stats отсутствует');
                }
                
                // Сохраняем перегенерированный markdown отдельно
                // Сохраняем оригинальный markdown перед перегенерацией (если еще не сохранен)
                if (!originalMarkdown && currentMarkdown) {
                    originalMarkdown = currentMarkdown;
                }
                
                // Сохраняем перегенерированный markdown отдельно
                const regeneratedMarkdown = data.regenerated_md;
                window.regeneratedMarkdown = regeneratedMarkdown; // Сохраняем для скачивания
                
                // Обновляем текущий markdown перегенерированным
                currentMarkdown = regeneratedMarkdown;
                
                // Обновляем результат с новыми данными (ПОСЛЕ сохранения оригинальных)
                if (currentResult) {
                    currentResult.markdown = data.regenerated_md;
                    currentResult.rubric = data.rubric;
                    currentResult.text_stats = data.text_stats;
                }
                
                // Сохраняем перегенерированные метрики и отчет
                if (data.rubric) {
                    regeneratedRubric = data.rubric;
                    window.regeneratedRubric = data.rubric; // Сохраняем в window для глобального доступа
                    console.log('regeneratedRubric сохранен:', !!regeneratedRubric);
                }
                if (data.text_stats) {
                    regeneratedTextStats = data.text_stats;
                    window.regeneratedTextStats = data.text_stats; // Сохраняем в window для глобального доступа
                    console.log('regeneratedTextStats сохранен:', !!regeneratedTextStats);
                }
                
                // Сохраняем обновленное состояние
                saveGenerationState();
                
                // Очищаем контейнер перед отображением нового контента
                const regenContainer = document.getElementById('regenContent');
                if (regenContainer) {
                    regenContainer.innerHTML = '';
                }
                
                // Отображаем перегенерированный контент
                displayMarkdown(data.regenerated_md, 'regenContent');
                
                // Отображаем список изменений
                if (data.changes && data.changes.length > 0) {
                    const changesList = document.getElementById('regenerationChangesList');
                    const changesContainer = document.getElementById('regenerationChanges');
                    changesList.innerHTML = '<ul style="margin: 0; padding-left: 1.5rem;">' + 
                        data.changes.map(change => `<li style="margin-bottom: 0.5rem;">${change}</li>`).join('') + 
                        '</ul>';
                    changesContainer.style.display = 'block';
                } else {
                    document.getElementById('regenerationChanges').style.display = 'none';
                }
                
                // Отображаем перегенерированные метрики и отчет в их контейнерах
                if (data.rubric) {
                    console.log('Отображаем перегенерированные метрики:', {
                        itemsCount: data.rubric.items?.length || 0,
                        total: data.rubric.total,
                        max: data.rubric.max_score
                    });
                    displayMetrics(data.rubric, 'metricsContentRegen');
                    window.currentRubric = data.rubric;
                    currentMetricsVersion = 'regenerated';
                    window.currentMetricsVersion = 'regenerated';
                    switchMetricsVersion('regenerated');
                    console.log('✅ regeneratedRubric отображен в metricsContentRegen');
                } else {
                    console.warn('⚠️ data.rubric отсутствует, метрики не отображены');
                }
                if (data.text_stats) {
                    displayReport({ text_stats: data.text_stats }, 'reportContentRegen');
                    currentReportVersion = 'regenerated';
                    window.currentReportVersion = 'regenerated';
                    switchReportVersion('regenerated');
                    console.log('✅ regeneratedTextStats отображен в reportContentRegen');
                } else {
                    console.warn('⚠️ data.text_stats отсутствует, отчет не отображен');
                }
                
                // Удаляем spinner
                if (window.loading && window.currentRegenSpinnerId) {
                    window.loading.hideSpinner(window.currentRegenSpinnerId);
                }
                
                // Показываем toast об успешной перегенерации
                if (window.toast) {
                    window.toast.success('Перегенерация успешно завершена!');
                }
                
                // Показываем переключатели версий (должно быть после сохранения данных)
                console.log('Вызываем updateVersionButtons после перегенерации', {
                    hasRegeneratedRubric: !!regeneratedRubric,
                    hasRegeneratedTextStats: !!regeneratedTextStats
                });
                updateVersionButtons();
                
                // Убеждаемся, что переключатели видны
                const metricsSwitcher = document.getElementById('metricsVersionSwitcher');
                const reportSwitcher = document.getElementById('reportVersionSwitcher');
                if (metricsSwitcher) {
                    console.log('Состояние metricsVersionSwitcher:', {
                        display: metricsSwitcher.style.display,
                        hasRegeneratedRubric: !!regeneratedRubric
                    });
                }
                if (reportSwitcher) {
                    console.log('Состояние reportVersionSwitcher:', {
                        display: reportSwitcher.style.display,
                        hasRegeneratedTextStats: !!regeneratedTextStats
                    });
                }
                
                // Убеждаемся, что контейнеры метрик и отчетов видны в соответствующих вкладках
                // Переключаем на вкладку "Метрики" и "Отчет", чтобы пользователь видел переключатели
                const metricsTab = document.querySelector('.tab[onclick*="metrics"]');
                const reportTab = document.querySelector('.tab[onclick*="report"]');
                
                // Если есть перегенерация, показываем ее вкладку как основную по умолчанию
                if (regeneratedRubric) {
                    switchMetricsVersion('regenerated');
                }
                if (regeneratedTextStats) {
                    switchReportVersion('regenerated');
                }
                
                // Логируем состояние для отладки
                console.log('Состояние после перегенерации:', {
                    hasOriginalRubric: !!originalRubric,
                    hasRegeneratedRubric: !!regeneratedRubric,
                    hasOriginalTextStats: !!originalTextStats,
                    hasRegeneratedTextStats: !!regeneratedTextStats
                });
                
                // Скрываем загрузчик после успешной перегенерации
                if (generationLogs) {
                    generationLogs.style.display = 'none';
                }
                
                // Показываем вкладку перегенерации
                const regenTab = document.querySelector('.tab[onclick*="regen"]');
                if (regenTab) {
                    showTab('regen', regenTab);
                } else {
                    showTab('regen');
                }
                
            } catch (error) {
                // Удаляем spinner
                if (window.loading && window.currentRegenSpinnerId) {
                    window.loading.hideSpinner(window.currentRegenSpinnerId);
                }
                
                // При ошибке показываем сообщение об ошибке, но не скрываем загрузчик сразу
                // чтобы пользователь увидел сообщение
                if (logContent) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(logContent, `Ошибка перегенерации: ${error.message}`);
                    } else {
                        logContent.textContent = `❌ Ошибка перегенерации: ${error.message}`;
                    }
                }
                
                // Показываем toast с ошибкой
                if (window.toast) {
                    window.toast.error(`Ошибка перегенерации: ${error.message}`);
                } else {
                    alert('Ошибка перегенерации: ' + error.message);
                }
                
                // Скрываем загрузчик через 3 секунды после ошибки, чтобы пользователь успел увидеть сообщение
                setTimeout(() => {
                    if (generationLogs) {
                        generationLogs.style.display = 'none';
                    }
                }, 3000);
            }
        }
        
        async function downloadResults() {
            await downloadArchive(false);
        }
        
        async function downloadRegeneratedResults() {
            await downloadArchive(true);
        }
        
        async function downloadTranslatedResults() {
            if (!currentRequestId) {
                alert('Нет активного запроса. Сначала сгенерируйте проект.');
                return;
            }
            
            try {
                const token = localStorage.getItem('auth_token');
                if (!token) {
                    alert('Требуется авторизация');
                    return;
                }
                
                // Скачиваем ZIP архив с переведенным README, диаграммами и файлами данных
                const response = await fetch(`${API_URL}/download/translated/${currentRequestId}`, {
                    headers: getAuthHeaders()
                });
                
                if (!response.ok) {
                    if (response.status === 404) {
                        alert('Переведенный README не найден. Убедитесь, что генерация завершена и перевод доступен.');
                        return;
                    }
                    throw new Error(`Ошибка получения архива: ${response.statusText}`);
                }
                
                // Получаем имя файла из заголовка Content-Disposition
                const contentDisposition = response.headers.get('Content-Disposition');
                let filename = `README_translated_${currentRequestId}.zip`;
                if (contentDisposition) {
                    const filenameMatch = contentDisposition.match(/filename="?(.+)"?/);
                    if (filenameMatch) {
                        filename = filenameMatch[1];
                    }
                }
                
                // Создаем blob из ответа и скачиваем
                const blob = await response.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            } catch (error) {
                console.error('Ошибка скачивания переведенного архива:', error);
                alert(`Ошибка скачивания: ${error.message}`);
            }
        }

        // ===================== Модуль «Перевод README» =====================

        let translationOriginalMarkdown = '';
        let translationTranslatedMarkdown = '';
        let translationFileName = 'README_translated.md';
        let translationCurrentRequestId = null;
        let translationJobType = 'readme';
        let translationRenderAsMarkdown = false;

        function displayPlainText(text, containerId) {
            const container = document.getElementById(containerId);
            if (!container) return;
            if (!text || typeof text !== 'string') {
                container.innerHTML = '<div class="info-box">Контент отсутствует</div>';
                return;
            }
            const div = document.createElement('div');
            div.style.whiteSpace = 'pre-wrap';
            div.style.wordBreak = 'break-word';
            div.style.fontFamily = 'inherit';
            div.textContent = text;
            container.innerHTML = '';
            container.appendChild(div);
        }

        function resetTranslationState() {
            if (typeof stopTranslationPolling === 'function') stopTranslationPolling();
            translationOriginalMarkdown = '';
            translationTranslatedMarkdown = '';
            translationFileName = 'README_translated.md';
            translationCurrentRequestId = null;
            translationJobType = 'readme';
            translationRenderAsMarkdown = false;

            const subBtn = document.getElementById('downloadTranslatedSubtitlesBtn');
            if (subBtn) subBtn.style.display = 'none';
            const mdBtn = document.getElementById('downloadTranslatedMarkdownBtn');
            if (mdBtn) mdBtn.style.display = 'inline-block';

            const noResults = document.getElementById('translationNoResults');
            const resultsArea = document.getElementById('translationResultsArea');
            const originalContainer = document.getElementById('translationOriginalContent');
            const translatedContainer = document.getElementById('translationTranslatedContent');

            if (noResults) {
                noResults.style.display = 'block';
            }
            if (resultsArea) {
                resultsArea.style.display = 'none';
            }
            if (originalContainer) {
                originalContainer.innerHTML = '';
            }
            if (translatedContainer) {
                translatedContainer.innerHTML = '';
            }
        }

        function handleTranslationFileSelect(event) {
            const fileInput = event.target;
            const file = fileInput && fileInput.files && fileInput.files[0];
            const fileNameLabel = document.getElementById('translationFileName');

            if (!file) {
                if (fileNameLabel) {
                    fileNameLabel.textContent = '';
                }
                return;
            }

            if (fileNameLabel) {
                fileNameLabel.textContent = `Выбран файл: ${file.name}`;
            }

            translationRenderAsMarkdown = (file.name || '').toLowerCase().endsWith('.md');

            const reader = new FileReader();
            reader.onload = function (e) {
                const text = e.target.result || '';
                translationOriginalMarkdown = String(text);
                translationFileName = file.name ? file.name.replace(/\.[^.]+$/, '') + '_translated.md' : 'README_translated.md';

                const input = document.getElementById('translationInput');
                if (input) {
                    input.value = translationOriginalMarkdown;
                }

                const noResults = document.getElementById('translationNoResults');
                const resultsArea = document.getElementById('translationResultsArea');
                if (noResults && resultsArea) {
                    noResults.style.display = 'none';
                    resultsArea.style.display = 'block';
                }

                if (translationRenderAsMarkdown) {
                    displayMarkdown(translationOriginalMarkdown, 'translationOriginalContent');
                } else {
                    displayPlainText(translationOriginalMarkdown, 'translationOriginalContent');
                }
            };
            reader.onerror = function (e) {
                console.error('Ошибка чтения файла для перевода:', e);
                alert('Ошибка чтения файла. Попробуйте выбрать другой файл.');
            };
            reader.readAsText(file);
        }

        let translationPollInterval = null;

        function resetTranslationUploadProgress() {
            const container = document.getElementById('translationUploadProgressContainer');
            const labelEl = document.getElementById('translationUploadProgressLabel');
            const barEl = document.getElementById('translationUploadProgressBar');
            if (!container || !labelEl || !barEl) return;
            container.style.display = 'none';
            labelEl.textContent = 'Загрузка видео: 0%';
            barEl.style.width = '0%';
        }

        function updateTranslationUploadProgress(percent) {
            const container = document.getElementById('translationUploadProgressContainer');
            const labelEl = document.getElementById('translationUploadProgressLabel');
            const barEl = document.getElementById('translationUploadProgressBar');
            if (!container || !labelEl || !barEl) return;
            const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
            container.style.display = 'block';
            labelEl.textContent = 'Загрузка видео: ' + pct + '%';
            barEl.style.width = pct + '%';
        }

        function updateTranslationProgress(phase, status) {
            const container = document.getElementById('translationProgressContainer');
            const phaseEl = document.getElementById('translationProgressPhase');
            const barEl = document.getElementById('translationProgressBar');
            if (!container || !phaseEl || !barEl) return;
            container.style.setProperty('display', 'block', 'important');
            const phaseLabels = {
                translate: 'Перевод...',
                refine: 'Улучшение читаемости...',
                combine: 'Объединение версий...',
                repair: 'Починка непереведённых секций...',
                validate: 'Проверка структуры и языка...',
                repair_retry_1: 'Повторный перевод (попытка 2)...',
                repair_retry_2: 'Повторный перевод (попытка 3)...',
                extract_audio: 'Извлечение аудио...',
                chunk_audio: 'Разбиение аудио...',
                transcribe: 'Транскрипция (RU)...',
                correct_asr: 'Коррекция распознавания...',
                translate: 'Перевод...',
                build_subtitles: 'Формирование субтитров...',
                render_video: 'Рендер видео с субтитрами...',
                done: 'Готово',
                queued: 'В очереди...'
            };
            phaseEl.textContent = phaseLabels[phase] || 'Выполняется...';
            let pct = 30;
            const progressArg = arguments[2];
            if (typeof progressArg === 'number' && progressArg >= 0 && progressArg <= 100) {
                pct = progressArg;
            } else if (phase === 'refine') pct = 50;
            else if (phase === 'repair') pct = 65;
            else if (phase === 'validate') pct = 80;
            else if (phase === 'repair_retry_1') pct = 40;
            else if (phase === 'repair_retry_2') pct = 60;
            else if (phase === 'combine' || status === 'completed') pct = 100;
            else if (phase === 'extract_audio') pct = 10;
            else if (phase === 'chunk_audio') pct = 15;
            else if (phase === 'transcribe') pct = 35;
            else if (phase === 'correct_asr') pct = 45;
            else if (phase === 'translate') pct = 60;
            else if (phase === 'build_subtitles') pct = 75;
            else if (phase === 'render_video') pct = 90;
            else if (phase === 'done') pct = 100;
            else if (phase === 'queued') pct = 0;
            else if (phase === 'build_srt') pct = 90;
            barEl.style.width = pct + '%';
        }

        function stopTranslationPolling() {
            if (translationPollInterval) {
                clearInterval(translationPollInterval);
                translationPollInterval = null;
            }
            const container = document.getElementById('translationProgressContainer');
            if (container) container.style.setProperty('display', 'none', 'important');
        }

        async function translateReadme() {
            const status = document.getElementById('translationStatus');
            const languageSelect = document.getElementById('translationLanguage');
            const modeSelect = document.getElementById('translationMode');
            const input = document.getElementById('translationInput');
            const sourceVideoRadio = document.getElementById('translationSourceVideo');
            const isVideoMode = sourceVideoRadio && sourceVideoRadio.checked;

            const targetLanguage = languageSelect ? languageSelect.value : 'en';
            const translationMode = modeSelect ? modeSelect.value : 'literal';
            const manualMarkdown = input ? input.value.trim() : '';
            const sourceMarkdown = manualMarkdown || translationOriginalMarkdown;

            if (isVideoMode) {
                const videoInput = document.getElementById('translationVideoFile');
                const file = videoInput && videoInput.files && videoInput.files[0];
                if (!file) {
                    alert('Выберите видеофайл для перевода субтитров.');
                    return;
                }
                if (!targetLanguage) {
                    alert('Выберите целевой язык перевода.');
                    return;
                }
            } else {
                if (!sourceMarkdown) {
                    alert('Загрузите файл или вставьте текст для перевода.');
                    return;
                }
                if (!targetLanguage) {
                    alert('Выберите целевой язык перевода.');
                    return;
                }
            }

            stopTranslationPolling();
            resetTranslationUploadProgress();

            try {
                if (status) {
                    status.innerHTML = '<div class="info-box">⏳ Запуск перевода...</div>';
                }
                const progressContainer = document.getElementById('translationProgressContainer');
                const progressPhase = document.getElementById('translationProgressPhase');
                const progressBar = document.getElementById('translationProgressBar');
                if (progressContainer && progressPhase && progressBar) {
                    progressContainer.style.setProperty('display', 'block', 'important');
                    progressPhase.textContent = isVideoMode ? 'Загрузка видео...' : 'Запуск...';
                    progressBar.style.width = '0%';
                }

                let requestId;
                if (isVideoMode) {
                    const videoInput = document.getElementById('translationVideoFile');
                    const file = videoInput && videoInput.files && videoInput.files[0];
                    const outputModeSelect = document.getElementById('translationOutputMode');
                    const outputMode = (outputModeSelect && outputModeSelect.value) || 'both';
                    const subtitleStyle = 'boxed';
                    requestId = await startVideoTranslationUpload(file, targetLanguage, outputMode, subtitleStyle);
                } else {
                    const startResponse = await fetch(`${API_URL}/translate/readme`, {
                        method: 'POST',
                        headers: {
                            ...getAuthHeaders(),
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({
                            markdown: sourceMarkdown,
                            target_language: targetLanguage,
                            translation_mode: translationMode
                        })
                    });
                    if (!startResponse.ok) {
                        let detail = startResponse.statusText;
                        try {
                            const errJson = await startResponse.json();
                            detail = errJson.detail || JSON.stringify(errJson);
                        } catch {
                            detail = await startResponse.text().catch(() => startResponse.statusText);
                        }
                        throw new Error(detail || `Ошибка ${startResponse.status}`);
                    }
                    const startData = await startResponse.json();
                    requestId = startData.request_id;
                }

                if (!requestId) throw new Error('Нет request_id в ответе');
                translationCurrentRequestId = requestId;
                translationJobType = isVideoMode ? 'video' : 'readme';

                if (status) status.innerHTML = '<div class="info-box">⏳ ' + (isVideoMode ? 'Обработка видео (распознавание и перевод)...' : 'Перевод выполняется (это может занять несколько минут)...') + '</div>';
                updateTranslationProgress(isVideoMode ? 'extract_audio' : 'translate', 'in_progress');

                translationPollInterval = setInterval(async () => {
                    try {
                        const statusResponse = await fetch(`${API_URL}/translate/status/${requestId}`, { headers: getAuthHeaders() });
                        if (!statusResponse.ok) return;
                        const job = await statusResponse.json();
                        const s = job.status;
                        const phase = job.phase || (isVideoMode ? 'extract_audio' : 'translate');
                        const progressPct = job.progress != null ? job.progress : undefined;
                        updateTranslationProgress(phase, s, progressPct);

                        if (s === 'completed') {
                            stopTranslationPolling();
                            const isVideoResult = job.job_type === 'video';
                            translationJobType = isVideoResult ? 'video' : 'readme';
                            translationOriginalMarkdown = isVideoResult ? (job.original_transcript || '') : (job.original_markdown || sourceMarkdown);
                            translationTranslatedMarkdown = isVideoResult ? (job.translated_subtitles || '') : (job.translated_markdown || sourceMarkdown);
                            const noResults = document.getElementById('translationNoResults');
                            const resultsArea = document.getElementById('translationResultsArea');
                            if (noResults && resultsArea) {
                                noResults.style.display = 'none';
                                resultsArea.style.display = 'block';
                            }
                            const mdBtn = document.getElementById('downloadTranslatedMarkdownBtn');
                            const subBtn = document.getElementById('downloadTranslatedSubtitlesBtn');
                            const videoDownloadSection = document.getElementById('translationVideoDownloadSection');
                            const videoDownloadLinks = document.getElementById('translationVideoDownloadLinks');
                            if (mdBtn) mdBtn.style.display = isVideoResult ? 'none' : 'inline-block';
                            if (subBtn) subBtn.style.display = (isVideoResult && !(job.result_links && Object.keys(job.result_links).length)) ? 'inline-block' : 'none';
                            if (videoDownloadSection) videoDownloadSection.style.display = (isVideoResult && job.result_links && Object.keys(job.result_links).length) ? 'block' : 'none';
                            if (videoDownloadLinks && isVideoResult && job.result_links) {
                                videoDownloadLinks.innerHTML = '';
                                const labels = { video: 'Скачать видео с переводом', vtt: 'VTT', srt: 'SRT', ass: 'ASS', transcript: 'Транскрипт RU (JSON)' };
                                ['video', 'vtt', 'srt', 'ass', 'transcript'].forEach(function(t) {
                                    if (!job.result_links[t]) return;
                                    const btn = document.createElement('button');
                                    btn.className = 'btn btn-download';
                                    btn.textContent = labels[t] || t;
                                    btn.onclick = function() { downloadTranslationArtifact(translationCurrentRequestId, t); };
                                    videoDownloadLinks.appendChild(btn);
                                });
                            }
                            if (isVideoResult) {
                                const origText = translationOriginalMarkdown || (job.result_links ? 'Транскрипт и субтитры готовы. Скачайте файлы ниже.' : '');
                                const transText = translationTranslatedMarkdown || (job.result_links ? 'Видео и субтитры готовы. Скачайте файлы ниже.' : '');
                                displayPlainText(origText, 'translationOriginalContent');
                                displayPlainText(transText, 'translationTranslatedContent');
                            } else if (translationRenderAsMarkdown) {
                                displayMarkdown(translationOriginalMarkdown, 'translationOriginalContent');
                                displayMarkdown(translationTranslatedMarkdown, 'translationTranslatedContent');
                            } else {
                                displayPlainText(translationOriginalMarkdown, 'translationOriginalContent');
                                displayPlainText(translationTranslatedMarkdown, 'translationTranslatedContent');
                            }
                            if (status) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetHTML(status, '<div class="success-msg">✅ ' + (isVideoResult ? 'Субтитры готовы' : 'Перевод завершён') + '</div>');
                                } else {
                                    status.innerHTML = '<div class="success-msg">✅ ' + (isVideoResult ? 'Субтитры готовы' : 'Перевод завершён') + '</div>';
                                }
                            }
                            if (window.toast) window.toast.success(isVideoResult ? 'Субтитры успешно сгенерированы' : 'Перевод успешно выполнен');
                            return;
                        }

                        if (s === 'failed') {
                            stopTranslationPolling();
                            const errMsg = job.error || 'Неизвестная ошибка';
                            if (status) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetErrorMessage(status, `Ошибка перевода: ${errMsg}`);
                                } else {
                                    status.innerHTML = `<div class="error-msg">❌ Ошибка перевода: ${errMsg}</div>`;
                                }
                            }
                            if (window.toast) window.toast.error(errMsg);
                            else alert('Ошибка перевода: ' + errMsg);
                        }
                    } catch (e) {
                        console.error('Ошибка опроса статуса перевода:', e);
                    }
                }, 2000);
            } catch (error) {
                console.error('Ошибка при переводе README:', error);
                stopTranslationPolling();
                if (status) {
                    if (window.sanitize) {
                        window.sanitize.safeSetErrorMessage(status, `Ошибка перевода: ${error.message}`);
                    } else {
                        status.innerHTML = `<div class="error-msg">❌ Ошибка перевода: ${error.message}</div>`;
                    }
                }
                if (window.toast) {
                    window.toast.error(`Ошибка перевода: ${error.message}`);
                } else {
                    alert('Ошибка перевода: ' + error.message);
                }
            }
        }

        function downloadTranslatedMarkdown() {
            if (!translationTranslatedMarkdown) {
                alert('Нет переведённого текста для скачивания. Сначала выполните перевод.');
                return;
            }

            const blob = new Blob([translationTranslatedMarkdown], { type: 'text/markdown;charset=utf-8' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = translationFileName || 'README_translated.md';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }

        async function downloadTranslatedSubtitles() {
            if (!translationCurrentRequestId) {
                alert('Нет готовых субтитров для скачивания. Сначала выполните перевод видео.');
                return;
            }
            try {
                const response = await fetch(`${API_URL}/translate/subtitles/${translationCurrentRequestId}`, {
                    headers: getAuthHeaders()
                });
                if (!response.ok) throw new Error(response.statusText || 'Ошибка загрузки');
                const blob = await response.blob();
                const lang = document.getElementById('translationLanguage') && document.getElementById('translationLanguage').value || 'ru';
                const ext = (document.getElementById('translationSubtitleFormat') && document.getElementById('translationSubtitleFormat').value) || 'srt';
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `subtitles_${lang}.${ext}`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            } catch (e) {
                console.error(e);
                alert('Не удалось скачать субтитры: ' + e.message);
            }
        }

        async function startVideoTranslationUpload(file, targetLanguage, outputMode, subtitleStyle) {
            return new Promise((resolve, reject) => {
                if (!file) {
                    reject(new Error('Файл видео не выбран'));
                    return;
                }
                const xhr = new XMLHttpRequest();
                xhr.open('POST', `${API_URL}/translate/video`);

                const headers = getAuthHeaders() || {};
                Object.keys(headers).forEach((key) => {
                    if (key.toLowerCase() === 'content-type') return;
                    xhr.setRequestHeader(key, headers[key]);
                });

                xhr.upload.onprogress = function (event) {
                    if (!event.lengthComputable) return;
                    const percent = (event.loaded / event.total) * 100;
                    updateTranslationUploadProgress(percent);
                };

                xhr.onerror = function () {
                    reject(new Error('Ошибка сети при загрузке видео'));
                };

                xhr.onload = function () {
                    if (xhr.status < 200 || xhr.status >= 300) {
                        let detail = xhr.statusText || 'Ошибка ' + xhr.status;
                        try {
                            const errJson = JSON.parse(xhr.responseText || '{}');
                            if (errJson && errJson.detail) detail = errJson.detail;
                        } catch {
                            // ignore JSON parse error
                        }
                        reject(new Error(detail));
                        return;
                    }
                    try {
                        const data = JSON.parse(xhr.responseText || '{}');
                        if (!data || !data.request_id) {
                            reject(new Error('Нет request_id в ответе сервера'));
                        } else {
                            updateTranslationUploadProgress(100);
                            resolve(data.request_id);
                        }
                    } catch (e) {
                        reject(new Error('Ошибка разбора ответа сервера'));
                    }
                };

                const formData = new FormData();
                formData.append('file', file);
                formData.append('target_language', targetLanguage);
                formData.append('output_mode', outputMode);
                formData.append('subtitle_style', subtitleStyle);

                xhr.send(formData);
            });
        }

        async function downloadTranslationArtifact(requestId, type) {
            if (!requestId || !type) return;
            try {
                const response = await fetch(`${API_URL}/translate/download/${requestId}?type=${encodeURIComponent(type)}`, {
                    headers: getAuthHeaders()
                });
                if (!response.ok) throw new Error(response.statusText || 'Ошибка загрузки');
                const blob = await response.blob();
                const disp = response.headers.get('Content-Disposition');
                let filename = type + (type === 'video' ? '.mp4' : type === 'transcript' ? '_ru.json' : '.');
                if (disp) {
                    const m = disp.match(/filename="?([^";\n]+)"?/);
                    if (m) filename = m[1].trim();
                }
                if (filename.indexOf('.') < 0 && type === 'vtt') filename = 'subtitles.vtt';
                if (filename.indexOf('.') < 0 && type === 'srt') filename = 'subtitles.srt';
                if (filename.indexOf('.') < 0 && type === 'ass') filename = 'subtitles.ass';
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
            } catch (e) {
                console.error(e);
                alert('Не удалось скачать файл: ' + e.message);
            }
        }

        async function downloadArchive(includeRegenerated = false) {
            if (!currentRequestId) {
                alert('Нет активного запроса. Сначала сгенерируйте проект.');
                return;
            }

            try {
                const token = localStorage.getItem('auth_token');
                const url = `${API_URL}/download/${currentRequestId}${includeRegenerated ? '?include_regenerated=true' : ''}`;
                const response = await fetch(url, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (!response.ok) {
                    const detail = await response.text().catch(() => response.statusText);
                    throw new Error(detail || `Ошибка ${response.status}`);
                }

                const blob = await response.blob();
                const disposition = response.headers.get('Content-Disposition') || '';
                const fileNameMatch = disposition.match(/filename="?([^"]+)"?/i);
                const fallbackName = includeRegenerated ? `contentgen_${currentRequestId}_regen.zip` : `contentgen_${currentRequestId}.zip`;
                const fileName = fileNameMatch ? fileNameMatch[1] : fallbackName;

                const urlBlob = window.URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = urlBlob;
                link.download = fileName;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                window.URL.revokeObjectURL(urlBlob);
            } catch (error) {
                console.error('Ошибка при скачивании архива:', error);
                alert('Ошибка при скачивании архива: ' + error.message);
            }
        }
        // Делегирование событий для кнопок фильтров метрик
        // Используем делегирование на уровне документа, чтобы обработчики работали даже после перерисовки
        (function() {
            document.addEventListener('click', function(e) {
                // Проверяем, что клик был по кнопке фильтра
                const btn = e.target.closest('.metrics-filter-btn');
                if (btn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const filter = btn.getAttribute('data-filter');
                    if (filter) {
                        console.log('Фильтр выбран через делегирование:', filter);
                        filterMetrics(filter);
                    }
                }
            });
        })();
        
        // Делегирование событий для чекбокса "Показать описание"
        // Используем делегирование на уровне документа, чтобы обработчик работал даже после перерисовки
        (function() {
            document.addEventListener('change', function(e) {
                // Проверяем, что изменение было в чекбоксе "Показать описание"
                if (e.target && e.target.id === 'toggleDescription' && e.target.type === 'checkbox') {
                    console.log('Чекбокс "Показать описание" изменен через делегирование');
                    toggleDescriptionColumn();
                }
            });
        })();
        
        async function handleLogout() {
            if (!confirm('Вы уверены, что хотите выйти?')) {
                return;
            }
            
            try {
                const token = localStorage.getItem('auth_token');
                if (token) {
                    await fetch(`${API_URL}/logout`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${token}`
                        }
                    });
                }
            } catch (error) {
                console.error('Ошибка при выходе:', error);
            } finally {
                // Очищаем localStorage и sessionStorage
                localStorage.removeItem('auth_token');
                localStorage.removeItem('user_id');
                localStorage.removeItem('username');
                localStorage.removeItem('session_id');
                clearGenerationState(); // Очищаем состояние генерации
                window.location.href = '/';
            }
        }

        function goToMainMenu() {
            window.location.href = '/app';
        }
        
        function showTab(tabName, clickedElement) {
            console.log('showTab вызвана:', tabName, clickedElement);
            
            // Скрываем все вкладки и их контент
            document.querySelectorAll('.tab').forEach(tab => {
                tab.classList.remove('active');
            });
            
            document.querySelectorAll('.tab-content').forEach(content => {
                content.classList.remove('active');
                content.style.display = 'none'; // Явно скрываем все
            });
            
            // Показываем выбранную вкладку
            if (clickedElement) {
                clickedElement.classList.add('active');
            } else {
                // Если элемент не передан, находим по тексту
                document.querySelectorAll('.tab').forEach(tab => {
                    if (tab.textContent.includes(tabName) || (tab.onclick && tab.onclick.toString().includes(tabName))) {
                        tab.classList.add('active');
                    }
                });
            }
            
            // Показываем контент вкладки, если он существует
            const tabContent = document.getElementById(tabName);
            if (tabContent) {
                tabContent.classList.add('active');
                tabContent.style.display = 'block'; // Явно показываем выбранную
                console.log('Показан контент вкладки:', tabName);
                
                // Если открыта вкладка "Критерии", обновляем отображение критериев
                if (tabName === 'metrics') {
                    console.log('📈 Вкладка критериев открыта, обновляем отображение', {
                        hasOriginal: !!window.checkerRubric,
                        hasImproved: !!window.improvedRubric,
                        hasMainOriginal: !!originalRubric,
                        hasMainRegenerated: !!regeneratedRubric,
                        currentMetricsVersion: currentMetricsVersion,
                        updateCheckerMetricsDisplayAvailable: typeof window.updateCheckerMetricsDisplay === 'function'
                    });
                    
                    // Для checker.html
                    if (typeof window.updateCheckerMetricsDisplay === 'function') {
                        setTimeout(() => {
                            console.log('🔄 Вызываем updateCheckerMetricsDisplay из showTab');
                            window.updateCheckerMetricsDisplay();
                        }, 100);
                    } 
                    // Для основной страницы генератора
                    else {
                        // Определяем, какую версию метрик показывать
                        const version = currentMetricsVersion || 'original';
                        const containerOriginal = document.getElementById('metricsContentOriginal');
                        const containerRegen = document.getElementById('metricsContentRegen');
                        
                        if (version === 'original' && originalRubric && containerOriginal) {
                            console.log('🔄 Обновляем оригинальные метрики при открытии вкладки');
                            displayMetrics(originalRubric, 'metricsContentOriginal');
                        } else if (version === 'regenerated' && regeneratedRubric && containerRegen) {
                            console.log('🔄 Обновляем перегенерированные метрики при открытии вкладки');
                            displayMetrics(regeneratedRubric, 'metricsContentRegen');
                        } else if (originalRubric && containerOriginal) {
                            // Если версия не определена, показываем оригинальные
                            console.log('🔄 Показываем оригинальные метрики по умолчанию');
                            displayMetrics(originalRubric, 'metricsContentOriginal');
                        }
                    }
                }
                
                // Дополнительная проверка: убеждаемся, что все остальные скрыты
                document.querySelectorAll('.tab-content').forEach(content => {
                    if (content.id !== tabName && content.style.display !== 'none') {
                        console.warn(`Вкладка ${content.id} не скрыта, исправляем...`);
                        content.style.display = 'none';
                        content.classList.remove('active');
                    }
                });
            } else {
                console.warn(`Контент вкладки "${tabName}" не найден`);
            }
        }
        
        // Экспортируем все функции в глобальную область видимости для использования в onclick
        // Это нужно, чтобы функции были доступны из inline обработчиков onclick
        // Функции уже определены выше, просто делаем их доступными глобально
        try {
            // Прямое присваивание функций в window (они уже определены в области видимости IIFE)
            window.toggleExpander = toggleExpander;
            window.generateContent = generateContent;
            window.clearForm = clearForm;
            window.clearGeneration = clearGeneration;
            window.showTab = showTab;
            window.filterMetrics = filterMetrics;
            window.handleLogout = handleLogout;
            window.regenerateContent = regenerateContent;
            window.downloadResults = downloadResults;
            window.downloadRegeneratedResults = downloadRegeneratedResults;
            window.downloadTranslatedResults = downloadTranslatedResults;
            window.handleTranslationFileSelect = handleTranslationFileSelect;
            window.translateReadme = translateReadme;
            window.downloadTranslatedMarkdown = downloadTranslatedMarkdown;
            window.downloadTranslatedSubtitles = downloadTranslatedSubtitles;
            window.resetTranslationState = resetTranslationState;
            window.fillCommentsFromFailedCriteria = fillCommentsFromFailedCriteria;
            window.switchMetricsVersion = switchMetricsVersion;
            window.switchReportVersion = switchReportVersion;
            window.clearRegeneration = clearRegeneration;
            window.downloadTemplate = downloadTemplate;
            window.addThematicBlock = addThematicBlock;
            window.toggleBonusWish = toggleBonusWish;
            window.toggleGroupSize = toggleGroupSize;
            window.handleFileSelect = handleFileSelect;
            window.handleTrackFilesSelect = handleTrackFilesSelect;
            window.checkReadme = checkReadme;
            window.handleReadmeFileSelect = handleReadmeFileSelect;
            window.handleReadmeFileSelectForExtraction = handleReadmeFileSelectForExtraction;
            window.extractFromReadme = extractFromReadme;
            window.downloadExtractedExcel = downloadExtractedExcel;
            window.goToMainMenu = goToMainMenu;
            window.insertRegenerationTemplate = insertRegenerationTemplate;
            window.getAuthHeaders = getAuthHeaders;
            window.displayMetrics = displayMetrics;
            window.filterMetrics = filterMetrics;
            window.cancelGeneration = cancelGeneration;
            window.displayMarkdown = displayMarkdown;
            window.renderMarkdownPreview = renderMarkdownPreview;
            window.normalizeMarkdownForDisplay = normalizeMarkdownForDisplay;
            window.renderMermaidDiagrams = renderMermaidDiagrams;
            
            // Curriculum (УП) functions
            window.handleCurriculumUpload = handleCurriculumUpload;
            window.populateCurriculumBlocks = populateCurriculumBlocks;
            window.onCurriculumBlockChange = onCurriculumBlockChange;
            window.onCurriculumProjectChange = onCurriculumProjectChange;
            window.onDirectionChange = onDirectionChange;
            
            console.log('✅ Все функции экспортированы в window');
        } catch (error) {
            console.error('❌ Ошибка при экспорте функций:', error);
        }
        
        // Инициализация при загрузке
        window.addEventListener('DOMContentLoaded', async () => {
            try {
                const hasGeneratorUI = Boolean(document.getElementById('generateBtn'));
                const hasCheckerUI = Boolean(document.getElementById('checkBtn'));
                if (hasGeneratorUI) {
                    loadThematicBlocks();
                    updateThematicBlockSelect();
                    await loadGenerationState();
                    setTimeout(() => {
                        if (typeof window.toggleGroupSize === 'function') {
                            window.toggleGroupSize();
                        } else if (typeof toggleGroupSize === 'function') {
                            toggleGroupSize();
                        }
                        const directionEl = document.getElementById('direction');
                        const thematicEl = document.getElementById('thematicBlock');
                        if (directionEl && thematicEl && !thematicEl.value && directionEl.value && directionEl.value !== 'ADD') {
                            thematicEl.value = directionEl.value;
                        }
                    }, 100);
                }
                if (hasCheckerUI) {
                    // Ничего дополнительного, но убеждаемся, что функции экспорта доступны
                }
                
                // Проверка доступности функций
                console.log('DOM загружен, проверка функций:');
                console.log('toggleExpander:', typeof window.toggleExpander);
                console.log('generateContent:', typeof window.generateContent);
                console.log('clearForm:', typeof window.clearForm);
                console.log('showTab:', typeof window.showTab);
                console.log('handleLogout:', typeof window.handleLogout);
                
                // Проверяем наличие expander элементов
                const expanders = document.querySelectorAll('.expander');
                console.log(`Найдено expander элементов: ${expanders.length}`);
                
                // Проверяем наличие кнопок
                const buttons = document.querySelectorAll('button[onclick]');
                console.log(`Найдено кнопок с onclick: ${buttons.length}`);
            } catch (error) {
                console.error('Ошибка при инициализации:', error);
            }
        });
        
        // ==================== Reverse Extraction Functions ====================
        
        let currentExcelFileId = null;
        
        function handleReadmeFileSelectForExtraction(event) {
            console.log('🔍 handleReadmeFileSelectForExtraction вызвана', event);
            console.log('📋 Event target:', event ? event.target : null);
            console.log('📋 Event target files:', event && event.target && event.target.files ? event.target.files : null);
            
            // Получаем файл из события
            const fileInput = event && event.target ? event.target : null;
            if (!fileInput) {
                console.error('❌ event.target не найден');
                return;
            }
            
            const file = fileInput.files ? fileInput.files[0] : null;
            
            if (!file) {
                console.warn('⚠️ Файл не выбран. files.length:', fileInput.files ? fileInput.files.length : 0);
                // Пробуем получить файл напрямую из элемента
                const fileInputById = document.getElementById('readmeFileInput');
                if (fileInputById && fileInputById.files && fileInputById.files[0]) {
                    console.log('✅ Файл найден через getElementById');
                    const fileFromId = fileInputById.files[0];
                    // Рекурсивно вызываем функцию с новым событием
                    const syntheticEvent = { target: fileInputById };
                    return handleReadmeFileSelectForExtraction(syntheticEvent);
                }
                return;
            }
            
            console.log('📁 Файл выбран:', file.name, `(${(file.size / 1024).toFixed(2)} KB)`, 'Тип:', file.type);
            
            // Проверяем, что это текстовый файл
            if (!file.name.endsWith('.md') && !file.name.endsWith('.txt') && !file.type.includes('text')) {
                console.warn('⚠️ Файл может быть не текстовым:', file.type);
            }
            
            const reader = new FileReader();
            
            reader.onload = function(e) {
                try {
                    const content = e.target.result;
                    console.log('📄 Файл прочитан, размер содержимого:', content.length, 'символов');
                    
                    // Сохраняем содержимое файла в глобальную переменную
                    window.readmeTextForExtraction = content;
                    console.log('💾 Текст сохранен в window.readmeTextForExtraction');
                    
                    // Обновляем UI для отображения загруженного файла
                    const fileNameEl = document.getElementById('readmeFileNameForExtraction');
                    const uploadText = document.getElementById('readmeFileUploadText');
                    const uploadArea = document.getElementById('readmeFileUploadArea');
                    const extractBtn = document.getElementById('extractBtn');
                    
                    console.log('🎨 Обновление UI элементов:', {
                        fileNameEl: !!fileNameEl,
                        uploadText: !!uploadText,
                        uploadArea: !!uploadArea,
                        extractBtn: !!extractBtn
                    });
                    
                    if (fileNameEl) {
                        fileNameEl.textContent = `✅ ${file.name} (${(file.size / 1024).toFixed(2)} KB)`;
                        fileNameEl.style.display = 'block';
                        fileNameEl.style.color = '#4caf50';
                        console.log('✅ Имя файла обновлено');
                    } else {
                        console.warn('⚠️ Элемент readmeFileNameForExtraction не найден');
                    }
                    
                    if (uploadText) {
                        uploadText.textContent = '📄 Файл загружен';
                        uploadText.style.color = '#4caf50';
                        console.log('✅ Текст загрузки обновлен');
                    } else {
                        console.warn('⚠️ Элемент readmeFileUploadText не найден');
                    }
                    
                    if (uploadArea) {
                        uploadArea.style.borderColor = 'rgba(76, 175, 80, 0.5)';
                        uploadArea.style.background = 'rgba(76, 175, 80, 0.1)';
                        console.log('✅ Стили области загрузки обновлены');
                    } else {
                        console.warn('⚠️ Элемент readmeFileUploadArea не найден');
                    }
                    
                    if (extractBtn) {
                        extractBtn.disabled = false;
                        console.log('✅ Кнопка извлечения активирована');
                    } else {
                        console.warn('⚠️ Элемент extractBtn не найден');
                    }
                    
                    console.log('✅ Файл успешно загружен и готов к извлечению');
                } catch (error) {
                    console.error('❌ Ошибка при обработке файла:', error);
                    alert('Ошибка при обработке файла: ' + error.message);
                }
            };
            
            reader.onerror = function(error) {
                console.error('❌ Ошибка чтения файла:', error);
                alert('Ошибка при чтении файла. Проверьте, что файл не поврежден.');
            };
            
            reader.onprogress = function(e) {
                if (e.lengthComputable) {
                    const percentLoaded = Math.round((e.loaded / e.total) * 100);
                    console.log(`📊 Загрузка файла: ${percentLoaded}%`);
                }
            };
            
            // Читаем файл как текст с кодировкой UTF-8
            reader.readAsText(file, 'UTF-8');
        }
        
        async function extractFromReadme() {
            console.log('🚀 Начало процесса извлечения данных из README');
            
            // Получаем текст из глобальной переменной или из textarea (для обратной совместимости)
            const readmeText = window.readmeTextForExtraction || 
                              (document.getElementById('readmeInputForExtraction')?.value.trim()) ||
                              (document.getElementById('readmeInput')?.value.trim());
            
            if (!readmeText) {
                alert('Пожалуйста, загрузите README.md файл');
                return;
            }
            
            console.log(`📄 Размер README: ${readmeText.length} символов`);
            
            const extractBtn = document.getElementById('extractBtn');
            const statusDiv = document.getElementById('extractionStatus');
            const statusContent = document.getElementById('extractionStatusContent');
            const downloadBtn = document.getElementById('downloadExcelBtn');
            const loadingDiv = document.getElementById('extractionLoading');
            const loadingText = document.getElementById('extractionLoadingText');
            
            // Блокируем кнопку и показываем загрузку
            extractBtn.disabled = true;
            extractBtn.textContent = '⏳ Извлечение...';
            statusDiv.style.display = 'none';
            loadingDiv.style.display = 'block';
            downloadBtn.style.display = 'none';
            currentExcelFileId = null;
            
            try {
                console.log('🔐 Проверка авторизации...');
                const token = localStorage.getItem('auth_token');
                if (!token) {
                    throw new Error('Требуется авторизация');
                }
                console.log('✅ Авторизация подтверждена');
                
                console.log('📤 Отправка запроса на извлечение данных...');
                console.log('📋 Размер текста для отправки:', readmeText.length, 'символов');
                console.log('📋 Первые 200 символов текста:', readmeText.substring(0, 200));
                if (loadingText) loadingText.textContent = '📤 Отправка запроса на сервер...';
                
                // Отправляем как JSON с readme_text
                const requestBody = {
                    readme_text: readmeText
                };
                
                const jsonBody = JSON.stringify(requestBody);
                console.log('📦 Тело запроса подготовлено, размер JSON:', jsonBody.length, 'символов');
                console.log('📦 Первые 300 символов JSON:', jsonBody.substring(0, 300));
                
                const response = await fetch('/api/v1/reverse-extract/extract', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json; charset=utf-8',
                        'Authorization': `Bearer ${token}`
                    },
                    body: jsonBody
                });
                
                console.log('📥 Ответ получен, статус:', response.status, response.statusText);
                console.log('📥 Response headers:', Object.fromEntries(response.headers.entries()));
                
                console.log(`📥 Получен ответ от сервера: ${response.status} ${response.statusText}`);
                
                if (!response.ok) {
                    const error = await response.json();
                    console.error('❌ Ошибка от сервера:', error);
                    throw new Error(error.detail || 'Ошибка при извлечении данных');
                }
                
                console.log('🔄 Парсинг ответа от сервера...');
                if (loadingText) loadingText.textContent = '🔄 Обработка ответа...';
                
                const result = await response.json();
                console.log('✅ Ответ получен:', result);
                currentExcelFileId = result.excel_file_id;
                
                console.log('📊 Этапы извлечения:');
                if (result.metadata && result.metadata.extracted_fields) {
                    const extracted = result.metadata.extracted_fields;
                    console.log('  1. ✅ Нормализация README');
                    console.log('  2. ✅ Извлечение структуры');
                    if (extracted.classification) {
                        console.log('  3. ✅ Классификация:', {
                            language: extracted.classification.language,
                            thematic_block: extracted.classification.thematic_block,
                            audience_level: extracted.classification.audience_level
                        });
                    }
                    if (extracted.final_mapping) {
                        console.log('  4. ✅ Маппинг данных');
                        console.log('  5. ✅ Валидация данных');
                    }
                    console.log('  6. ✅ Заполнение Excel шаблона');
                }
                
                console.log('✅ Извлечение данных завершено успешно');
                
                // Скрываем загрузку и показываем результаты
                loadingDiv.style.display = 'none';
                statusDiv.style.display = 'block';
                
                // Отображаем результаты
                let statusHtml = '<div style="padding: 1rem;">';
                statusHtml += '<h3 style="color: #4caf50; margin-bottom: 1rem;">✅ Извлечение завершено</h3>';
                
                if (result.metadata.warnings && result.metadata.warnings.length > 0) {
                    statusHtml += '<div style="margin-bottom: 1rem; padding: 0.75rem; background: rgba(255, 193, 7, 0.15); border-radius: 8px; border-left: 4px solid #ffc107;">';
                    statusHtml += '<strong>⚠️ Предупреждения:</strong><ul style="margin: 0.5rem 0 0 0; padding-left: 1.5rem;">';
                    result.metadata.warnings.forEach(w => {
                        statusHtml += `<li style="margin: 0.25rem 0;">${w}</li>`;
                    });
                    statusHtml += '</ul></div>';
                }
                
                if (result.metadata.errors && result.metadata.errors.length > 0) {
                    statusHtml += '<div style="margin-bottom: 1rem; padding: 0.75rem; background: rgba(244, 67, 54, 0.15); border-radius: 8px; border-left: 4px solid #f44336;">';
                    statusHtml += '<strong>❌ Ошибки:</strong><ul style="margin: 0.5rem 0 0 0; padding-left: 1.5rem;">';
                    result.metadata.errors.forEach(e => {
                        statusHtml += `<li style="margin: 0.25rem 0;">${e}</li>`;
                    });
                    statusHtml += '</ul></div>';
                }
                
                const extracted = result.metadata.extracted_fields || {};
                if (extracted.final_mapping) {
                    statusHtml += '<div style="margin-top: 1rem;"><strong>📊 Извлеченные данные:</strong>';
                    statusHtml += '<ul style="margin: 0.5rem 0 0 0; padding-left: 1.5rem;">';
                    if (extracted.final_mapping.title_seed) {
                        statusHtml += `<li><strong>Название:</strong> ${extracted.final_mapping.title_seed}</li>`;
                    }
                    // Показываем предложенный блок, если он есть, иначе найденный
                    const thematicBlock = extracted.classification?.final_thematic_block || 
                                         extracted.classification?.thematic_block_suggested || 
                                         extracted.classification?.thematic_block || 
                                         extracted.final_mapping?.thematic_block;
                    if (thematicBlock) {
                        const blockName = extracted.classification?.thematic_block_name;
                        const displayBlock = blockName ? `${thematicBlock} (${blockName})` : thematicBlock;
                        statusHtml += `<li><strong>Тематический блок:</strong> ${displayBlock}</li>`;
                    }
                    if (extracted.final_mapping.language) {
                        statusHtml += `<li><strong>Язык:</strong> ${extracted.final_mapping.language}</li>`;
                    }
                    statusHtml += '</ul></div>';
                }
                
                statusHtml += '</div>';
                statusContent.innerHTML = statusHtml;
                
                // Показываем кнопку скачивания
                if (currentExcelFileId) {
                    downloadBtn.style.display = 'block';
                }
                
            } catch (error) {
                console.error('❌ Ошибка извлечения:', error);
                loadingDiv.style.display = 'none';
                statusDiv.style.display = 'block';
                statusContent.innerHTML = `
                    <div style="padding: 1rem; background: rgba(244, 67, 54, 0.15); border-radius: 8px; border-left: 4px solid #f44336;">
                        <strong>❌ Ошибка:</strong> ${error.message}
                    </div>
                `;
            } finally {
                extractBtn.disabled = false;
                extractBtn.textContent = '🔍 Извлечь данные';
                console.log('🏁 Процесс извлечения завершен');
            }
        }
        
        async function downloadExtractedExcel() {
            if (!currentExcelFileId) {
                alert('Нет файла для скачивания');
                return;
            }
            
            try {
                const token = localStorage.getItem('auth_token');
                if (!token) {
                    throw new Error('Требуется авторизация');
                }
                
                const response = await fetch(`/api/v1/reverse-extract/download/${currentExcelFileId}`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });
                
                if (!response.ok) {
                    throw new Error('Ошибка при скачивании файла');
                }
                
                const blob = await response.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = response.headers.get('Content-Disposition')?.split('filename=')[1]?.replace(/"/g, '') || 'project_spec.xlsx';
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                window.URL.revokeObjectURL(url);
                
            } catch (error) {
                console.error('Ошибка скачивания:', error);
                alert(`Ошибка при скачивании: ${error.message}`);
            }
        }
        
        // Экспортируем функции для использования в HTML (дублируем для надежности)
        window.handleReadmeFileSelectForExtraction = handleReadmeFileSelectForExtraction;
        window.extractFromReadme = extractFromReadme;
        window.downloadExtractedExcel = downloadExtractedExcel;
        
        console.log('✅ Reverse extraction функции экспортированы:', {
            handleReadmeFileSelectForExtraction: typeof window.handleReadmeFileSelectForExtraction,
            extractFromReadme: typeof window.extractFromReadme,
            downloadExtractedExcel: typeof window.downloadExtractedExcel
        });
        
        // Экспортируем дополнительные функции для использования в HTML (checker.html)
        // Основные функции уже экспортированы выше
        window.clearCheckerResults = clearCheckerResults;
        window.restoreCheckerResults = restoreCheckerResults;
        window.toggleDescriptionColumn = toggleDescriptionColumn;
        })(); // Закрываем IIFE
