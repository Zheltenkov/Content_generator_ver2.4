// Translation screen controller.
// Keeps README/video translation state out of main.js while preserving legacy window functions.

        function setTranslationText(id, value) {
            const el = document.getElementById(id);
            if (el) {
                el.textContent = value == null ? '' : String(value);
            }
        }

        function getTranslationApiUrl() {
            return window.API_URL || window.ContentGenApiUrl || '/api/v1';
        }

        function getTranslationAuthHeaders() {
            return typeof window.getAuthHeaders === 'function' ? window.getAuthHeaders() : {};
        }

function updateTranslationSummary(kind = 'document', statusText = 'Готово') {
            const langSelect = document.getElementById('translationLanguage');
            const language = (langSelect && langSelect.value ? langSelect.value.toUpperCase() : 'EN');
            setTranslationText('translationSummaryMode', kind === 'video' ? 'Видео' : 'Документ');
            setTranslationText('translationSummaryLanguage', `RU → ${language}`);
            setTranslationText('translationSummaryStatus', statusText);
            const brandBadge = document.getElementById('translationBrandBadge');
            const brandMark = document.getElementById('translationBrandMark');
            const subbarTitle = document.getElementById('translationSubbarTitle');
            if (brandBadge) brandBadge.setAttribute('data-step', kind === 'video' ? '05.2' : '05.1');
            if (brandMark) {
                brandMark.textContent = kind === 'video'
                    ? `ПЕРЕВОД ВИДЕО · ${statusText || 'В РАБОТЕ'}`
                    : `ПЕРЕВОД ДОКУМЕНТА · RU → ${language}`;
            }
            if (subbarTitle) subbarTitle.textContent = kind === 'video' ? 'Перевод · Видео' : 'Перевод';
        }

        let translationOriginalMarkdown = '';
        let translationTranslatedMarkdown = '';
        let translationFileName = 'README_translated.md';
        let translationCurrentRequestId = null;
        let translationJobType = 'readme';
        let translationRenderAsMarkdown = false;

        function countTranslationWords(text) {
            return String(text || '')
                .trim()
                .split(/\s+/)
                .filter(Boolean).length;
        }

        function formatTranslationBytes(bytes) {
            const value = Number(bytes || 0);
            if (!value) return '0 КБ';
            if (value >= 1024 * 1024) return `${Math.round(value / 1024 / 1024)} МБ`;
            return `${Math.max(1, Math.round(value / 1024))} КБ`;
        }

        function updateTranslationTextMeta(kind, text, bytes) {
            const words = countTranslationWords(text);
            const suffix = bytes ? ` · ${formatTranslationBytes(bytes)}` : '';
            const value = `${words.toLocaleString('ru-RU')} слов${suffix}`;
            const targetId = kind === 'translated' ? 'translationTranslatedMeta' : 'translationOriginalMeta';
            setTranslationText(targetId, value);
            return value;
        }

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
            setTranslationText('translationSourceFileTitle', 'Загрузить README.md');
            setTranslationText('translationFileName', 'Markdown-файл для перевода');
            setTranslationText('translationOriginalMeta', '0 слов');
            setTranslationText('translationTranslatedMeta', '0 слов');
            const brandBadge = document.getElementById('translationBrandBadge');
            const brandMark = document.getElementById('translationBrandMark');
            if (brandBadge) brandBadge.setAttribute('data-step', '05.1');
            if (brandMark) brandMark.textContent = 'ПЕРЕВОД ДОКУМЕНТА · RU → EN';
            updateTranslationSummary('document', 'Ожидает запуска');
        }

        function handleTranslationFileSelect(event) {
            const fileInput = event.target;
            const file = fileInput && fileInput.files && fileInput.files[0];
            const fileNameLabel = document.getElementById('translationFileName');

            if (!file) {
                if (fileNameLabel) {
                    fileNameLabel.textContent = 'Markdown-файл для перевода';
                }
                setTranslationText('translationSourceFileTitle', 'Загрузить README.md');
                return;
            }

            const sourceTitle = document.getElementById('translationSourceFileTitle');
            if (sourceTitle) sourceTitle.textContent = file.name;
            if (fileNameLabel) fileNameLabel.textContent = `${formatTranslationBytes(file.size)} · загружен`;

            const lowerFileName = (file.name || '').toLowerCase();
            translationRenderAsMarkdown = lowerFileName.endsWith('.md') || lowerFileName.endsWith('.markdown');

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
                updateTranslationTextMeta('original', translationOriginalMarkdown, file.size);
                setTranslationText('translationTranslatedMeta', 'Ожидает перевода');
                updateTranslationSummary('document', 'Предпросмотр');
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
            setTranslationText('translationVideoProgressPct', pct + ' %');
        }

        function updateTranslationProgress(phase, status) {
            const container = document.getElementById('translationProgressContainer');
            const phaseEl = document.getElementById('translationProgressPhase');
            const barEl = document.getElementById('translationProgressBar');
            if (!container || !phaseEl || !barEl) return;
            const videoModeActive = translationJobType === 'video' || !!document.getElementById('translationSourceVideo')?.checked;
            container.style.setProperty('display', videoModeActive ? 'none' : 'block', 'important');
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
            setTranslationText('translationVideoProgressLabel', phaseEl.textContent.replace(/\.\.\.$/, ''));
            updateTranslationSummary(translationJobType === 'video' ? 'video' : 'document', status === 'completed' ? 'Готово' : phaseEl.textContent.replace(/\.\.\.$/, ''));
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
            setTranslationText('translationVideoProgressPct', pct + ' %');
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
                    status.innerHTML = '<div class="info-box">Запуск перевода...</div>';
                }
                const progressContainer = document.getElementById('translationProgressContainer');
                const progressPhase = document.getElementById('translationProgressPhase');
                const progressBar = document.getElementById('translationProgressBar');
                if (progressContainer && progressPhase && progressBar) {
                    progressContainer.style.setProperty('display', isVideoMode ? 'none' : 'block', 'important');
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
                    const startResponse = await fetch(`${getTranslationApiUrl()}/translate/readme`, {
                        method: 'POST',
                        headers: {
                            ...getTranslationAuthHeaders(),
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

                if (status) status.innerHTML = '<div class="info-box">' + (isVideoMode ? 'Обработка видео: распознавание и перевод' : 'Перевод выполняется. Это может занять несколько минут.') + '</div>';
                updateTranslationSummary(isVideoMode ? 'video' : 'document', 'В работе');
                updateTranslationProgress(isVideoMode ? 'extract_audio' : 'translate', 'in_progress');

                translationPollInterval = setInterval(async () => {
                    try {
                        const statusResponse = await fetch(`${getTranslationApiUrl()}/translate/status/${requestId}`, { headers: getTranslationAuthHeaders() });
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
                            updateTranslationSummary(isVideoResult ? 'video' : 'document', 'Готово');
                            translationOriginalMarkdown = isVideoResult ? (job.original_transcript || '') : (job.original_markdown || sourceMarkdown);
                            translationTranslatedMarkdown = isVideoResult ? (job.translated_subtitles || '') : (job.translated_markdown || sourceMarkdown);
                            window.translationTranslatedMarkdown = translationTranslatedMarkdown;
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
                                updateTranslationTextMeta('original', origText);
                                updateTranslationTextMeta('translated', transText);
                            } else if (translationRenderAsMarkdown) {
                                displayMarkdown(translationOriginalMarkdown, 'translationOriginalContent');
                                displayMarkdown(translationTranslatedMarkdown, 'translationTranslatedContent');
                                updateTranslationTextMeta('original', translationOriginalMarkdown);
                                updateTranslationTextMeta('translated', translationTranslatedMarkdown);
                            } else {
                                displayPlainText(translationOriginalMarkdown, 'translationOriginalContent');
                                displayPlainText(translationTranslatedMarkdown, 'translationTranslatedContent');
                                updateTranslationTextMeta('original', translationOriginalMarkdown);
                                updateTranslationTextMeta('translated', translationTranslatedMarkdown);
                            }
                            if (status) {
                                if (window.sanitize) {
                                    window.sanitize.safeSetHTML(status, '<div class="success-msg">' + (isVideoResult ? 'Субтитры готовы' : 'Перевод завершён') + '</div>');
                                } else {
                                    status.innerHTML = '<div class="success-msg">' + (isVideoResult ? 'Субтитры готовы' : 'Перевод завершён') + '</div>';
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
                                    status.innerHTML = `<div class="error-msg">Ошибка перевода: ${errMsg}</div>`;
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
                        status.innerHTML = `<div class="error-msg">Ошибка перевода: ${error.message}</div>`;
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
                const response = await fetch(`${getTranslationApiUrl()}/translate/subtitles/${translationCurrentRequestId}`, {
                    headers: getTranslationAuthHeaders()
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
                xhr.open('POST', `${getTranslationApiUrl()}/translate/video`);

                const headers = getTranslationAuthHeaders() || {};
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
                const response = await fetch(`${getTranslationApiUrl()}/translate/download/${requestId}?type=${encodeURIComponent(type)}`, {
                    headers: getTranslationAuthHeaders()
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

        if (typeof window !== 'undefined') {
            Object.assign(window, {
                handleTranslationFileSelect,
                translateReadme,
                downloadTranslatedMarkdown,
                downloadTranslatedSubtitles,
                resetTranslationState,
                downloadTranslationArtifact,
                startVideoTranslationUpload,
                updateTranslationSummary,
            });
        }

