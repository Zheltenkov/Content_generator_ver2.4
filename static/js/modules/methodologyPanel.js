(function () {
    let config = {
        apiUrl: '',
        getAuthHeaders: () => ({}),
        getCurrentRequestId: () => null,
        onApproved: () => {},
        onDiffApproved: () => {},
        onChangeRequested: () => {},
        onRejected: () => {},
        onError: (message) => {
            if (window.toast) {
                window.toast.error(message);
            }
        },
    };
    let pendingRequestId = null;
    let currentReviewState = null;
    let reviewBusy = false;
    let checkpointMarkdownBlocks = [];

    function configure(nextConfig) {
        config = { ...config, ...(nextConfig || {}) };
    }

    function esc(value) {
        const text = value === null || value === undefined ? '' : String(value);
        return window.sanitize ? window.sanitize.escapeHtml(text) : text;
    }

    function render(payload, containerId = 'methodologyContent', options = {}) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const compact = !!options.compact || containerId === 'methodologyLiveStatus';
        if (compact) {
            container.style.display = 'none';
            container.innerHTML = '';
            return;
        }

        if (!payload || typeof payload !== 'object') {
            container.style.display = '';
            container.innerHTML = '<div class="info-box">Методологический trace пока недоступен.</div>';
            return;
        }

        const summary = payload.summary || payload.methodology_gate_summary || {};
        const decisions = Array.isArray(payload.decisions)
            ? payload.decisions
            : (Array.isArray(payload.methodology_gate_decisions) ? payload.methodology_gate_decisions : []);
        const revisions = Array.isArray(payload.revision_results)
            ? payload.revision_results
            : (Array.isArray(payload.methodology_revision_results) ? payload.methodology_revision_results : []);
        const total = summary.total_decisions || decisions.length || 0;
        const latestStage = summary.latest_stage || (decisions.length ? decisions[decisions.length - 1].stage : '-');
        const latestAction = summary.latest_action || (decisions.length ? decisions[decisions.length - 1].action : 'continue');
        const humanReview = summary.human_review_required ? 'да' : 'нет';
        const blocking = summary.blocking ? 'да' : 'нет';

        const cards = `
            <div class="methodology-summary-grid">
                <div class="methodology-summary-item">
                    <div class="methodology-summary-value">${esc(total)}</div>
                    <div class="methodology-summary-label">проверок</div>
                </div>
                <div class="methodology-summary-item">
                    <div class="methodology-summary-value">${esc(latestAction)}</div>
                    <div class="methodology-summary-label">последнее решение</div>
                </div>
                <div class="methodology-summary-item">
                    <div class="methodology-summary-value">${esc(humanReview)}</div>
                    <div class="methodology-summary-label">нужен методолог</div>
                </div>
                <div class="methodology-summary-item">
                    <div class="methodology-summary-value">${esc(blocking)}</div>
                    <div class="methodology-summary-label">блокировка</div>
                </div>
            </div>
        `;

        const visibleDecisions = compact ? decisions.slice(-3) : decisions;
        const list = visibleDecisions.map((decision) => {
            const action = ['continue', 'warn', 'pause', 'fail'].includes(decision.action)
                ? decision.action
                : 'continue';
            const issues = Array.isArray(decision.issues) ? decision.issues.slice(0, compact ? 2 : 5) : [];
            const issuesHtml = issues.length
                ? `<ul class="methodology-issue-list">${issues.map(issue => {
                    const severity = issue.severity || 'info';
                    const code = issue.code || '';
                    const message = issue.message || '';
                    return `<li>${esc(severity)} · ${esc(code)}: ${esc(message)}</li>`;
                }).join('')}</ul>`
                : '';
            return `
                <li class="methodology-stage-item action-${action}">
                    <div class="methodology-stage-header">
                        <span>${esc(decision.stage || 'stage')}</span>
                        <span>${esc(action)}</span>
                    </div>
                    <div class="methodology-stage-meta">
                        ${esc(decision.summary || decision.title || '')}
                    </div>
                    ${issuesHtml}
                </li>
            `;
        }).join('');

        const title = compact
            ? `<div class="methodology-stage-header"><span>Методологический gate</span><span>${esc(latestStage)}</span></div>`
            : '<h3>🧭 Методологический gate</h3>';
        const html = `
            ${title}
            ${cards}
            ${list ? `<ul class="methodology-stage-list">${list}</ul>` : '<div class="info-box">Проверки ещё не зафиксированы.</div>'}
            ${revisions.length ? renderRevisionResults(revisions) : ''}
        `;

        container.style.display = '';
        if (window.sanitize) {
            window.sanitize.safeSetHTML(container, html);
        } else {
            container.innerHTML = html;
        }
    }

    function reviewActionContainers() {
        return [
            document.getElementById('methodologyReviewWorkspace'),
            document.getElementById('methodologyReviewActions'),
        ].filter(Boolean);
    }

    function activeReviewActionContainer() {
        return document.getElementById('methodologyReviewWorkspace')
            || document.getElementById('methodologyReviewActions');
    }

    function resetReviewActionContainer(container) {
        container.style.display = 'none';
        container.innerHTML = '';
        container.classList.remove('is-active');
    }

    function showActions({ requestId, message = '' }) {
        const container = activeReviewActionContainer();
        if (!container || !requestId) return;
        pendingRequestId = requestId;
        reviewActionContainers()
            .filter(item => item !== container)
            .forEach(resetReviewActionContainer);
        const html = `
            <div class="methodology-review-header">
                <div>
                    <div class="methodology-review-title">Решение методолога</div>
                    <div class="methodology-stage-meta">${esc(message)}</div>
                </div>
                <span class="methodology-review-status">needs_review</span>
            </div>
            <div class="methodology-review-layout">
                <section class="methodology-review-main" aria-label="Артефакт и история методолога">
                    <div class="methodology-review-state" id="methodologyReviewState"></div>
                </section>
                <section class="methodology-review-toolbar" aria-label="Действия методолога">
                    <div class="btn-group methodology-primary-actions">
                        <button class="btn" type="button" id="methodologyApproveBtn">Продолжить генерацию</button>
                        <button class="btn" type="button" id="methodologyApproveDiffBtn">Принять изменения</button>
                        <button class="btn" type="button" id="methodologyToggleChangeRequestBtn">Изменить правки</button>
                        <button class="btn" type="button" id="methodologyPreviewChangesBtn">Показать изменения</button>
                        <button class="btn btn-danger" type="button" id="methodologyRejectBtn">Остановить</button>
                    </div>
                    <div class="methodology-change-form" id="methodologyChangeRequestForm" style="display: none;">
                        <div class="methodology-form-title">Запрос правки</div>
                        <div class="methodology-form-hint">
                            Заполните только смысл правки. Технические поля система подставит сама по выбранному блоку.
                        </div>

                        <label for="methodologyTargetSelect">Что правим</label>
                        <select id="methodologyTargetSelect">
                            <option value="">Текущий блок</option>
                        </select>
                        <div class="methodology-field-hint">Обычно достаточно оставить выбранный блок.</div>

                        <label for="methodologyChangeInstruction">Что исправить</label>
                        <textarea id="methodologyChangeInstruction" rows="4" placeholder="Например: усилить связь аннотации с рабочим кейсом и итоговым артефактом"></textarea>

                        <label for="methodologyChangeExpected">Как должно стать</label>
                        <textarea id="methodologyChangeExpected" rows="2" placeholder="Например: читатель понимает роль, задачу и результат проекта"></textarea>

                        <label for="methodologyChangeForbidden">Что не трогать</label>
                        <input id="methodologyChangeForbidden" type="text" placeholder="Например: не менять структуру задач, не добавлять готовые ответы">

                        <details class="methodology-advanced-fields">
                            <summary>Дополнительно</summary>
                            <label for="methodologyTargetStageFilter">Показать цели</label>
                            <select id="methodologyTargetStageFilter">
                                <option value="">Все этапы</option>
                                <option value="title">Название</option>
                                <option value="annotation">Аннотация</option>
                                <option value="skeleton">Структура</option>
                                <option value="theory">Теория</option>
                                <option value="practice">Практика</option>
                                <option value="dataset">Материалы</option>
                                <option value="final">Финальная сборка</option>
                            </select>
                            <div class="methodology-form-grid">
                                <div>
                                    <label for="methodologyChangeStage">Этап</label>
                                    <select id="methodologyChangeStage">
                                        <option value="title">Название</option>
                                        <option value="annotation">Аннотация</option>
                                        <option value="theory">Теория</option>
                                        <option value="practice">Практика</option>
                                        <option value="dataset">Материалы</option>
                                        <option value="final">Финальная сборка</option>
                                        <option value="task_planning">План задач</option>
                                        <option value="skeleton">Структура</option>
                                        <option value="context">Контекст</option>
                                    </select>
                                </div>
                                <div>
                                    <label for="methodologyChangeScope">Граница правки</label>
                                    <select id="methodologyChangeScope">
                                        <option value="local_section_only">Только выбранный блок</option>
                                        <option value="task_only">Только задача</option>
                                        <option value="materials_only">Только materials</option>
                                    </select>
                                </div>
                            </div>
                            <label for="methodologyChangeSelector">Точный адрес</label>
                            <input id="methodologyChangeSelector" type="text" placeholder="Например: annotation, theory.part.1 или materials/task_01_source_notes.md">
                            <label for="methodologyChangeIssueCodes">Коды замечаний</label>
                            <input id="methodologyChangeIssueCodes" type="text" placeholder="Например: 2.4.3, narrative_focus">
                        </details>
                        <div id="methodologyChangeFeedback" class="methodology-review-feedback" style="display: none;"></div>
                        <div class="btn-group methodology-change-actions">
                            <button class="btn" type="button" id="methodologySubmitChangeRequestBtn">Сохранить правку</button>
                            <button class="btn" type="button" id="methodologyCancelChangeRequestBtn">Скрыть форму</button>
                        </div>
                    </div>
                </section>
            </div>
        `;
        container.style.display = 'block';
        container.classList.add('is-active');
        container.innerHTML = html;
        document.getElementById('methodologyApproveBtn')?.addEventListener('click', approve);
        document.getElementById('methodologyApproveDiffBtn')?.addEventListener('click', approveDiff);
        document.getElementById('methodologyToggleChangeRequestBtn')?.addEventListener('click', toggleChangeRequestForm);
        document.getElementById('methodologyPreviewChangesBtn')?.addEventListener('click', previewChanges);
        document.getElementById('methodologyRejectBtn')?.addEventListener('click', reject);
        document.getElementById('methodologySubmitChangeRequestBtn')?.addEventListener('click', requestChanges);
        document.getElementById('methodologyCancelChangeRequestBtn')?.addEventListener('click', toggleChangeRequestForm);
        document.getElementById('methodologyTargetSelect')?.addEventListener('change', applySelectedTarget);
        document.getElementById('methodologyTargetStageFilter')?.addEventListener('change', () => populateTargetSelect(currentReviewState));
        updateReviewActionAvailability();
        fetchReviewState(requestId);
    }

    function hideActions() {
        reviewActionContainers().forEach(resetReviewActionContainer);
        pendingRequestId = null;
        currentReviewState = null;
        reviewBusy = false;
    }

    async function fetchReviewState(requestId) {
        if (!requestId) return null;
        try {
            const response = await fetch(`${config.apiUrl}/generate/review/${requestId}`, {
                headers: config.getAuthHeaders()
            });
            if (!response.ok) return null;
            currentReviewState = await response.json();
            populateTargetSelect(currentReviewState);
            renderReviewState(currentReviewState);
            return currentReviewState;
        } catch (error) {
            console.debug('Не удалось получить review state:', error);
            return null;
        }
    }

    function populateTargetSelect(state) {
        const select = document.getElementById('methodologyTargetSelect');
        if (!select) return;
        const stageFilter = document.getElementById('methodologyTargetStageFilter')?.value || '';
        const targets = (state?.target_registry?.targets || [])
            .filter(target => !stageFilter || target.stage === stageFilter);
        const options = ['<option value="">Текущий блок</option>'].concat(
            targets.map(target => (
                `<option value="${esc(target.id)}">${esc(targetOptionLabel(target))}</option>`
            ))
        );
        const current = select.value;
        select.innerHTML = options.join('');
        if (current && targets.some(target => target.id === current)) {
            select.value = current;
        } else if (targets.length) {
            const preferred = preferredTargetForCheckpoint(targets, state);
            select.value = (preferred || targets[0]).id;
        }
        if (select.value) {
            applySelectedTarget();
        }
    }

    function preferredTargetForCheckpoint(targets, state) {
        const checkpointStage = normalizeCheckpointStage(state?.checkpoint?.stage || state?.checkpoint?.target_stage || '');
        if (!checkpointStage) return targets[0] || null;
        return targets.find(target => normalizeCheckpointStage(target.stage) === checkpointStage) || targets[0] || null;
    }

    function normalizeCheckpointStage(stage) {
        const value = String(stage || '').trim();
        return {
            structure: 'skeleton',
            title_annotation: 'title',
        }[value] || value;
    }

    function targetOptionLabel(target) {
        const label = target.label || target.id || 'текущий блок';
        const stage = stageLabel(target.stage || '');
        return stage ? `${stage}: ${label}` : label;
    }

    function stageLabel(stage) {
        return {
            title: 'Название',
            annotation: 'Аннотация',
            skeleton: 'Структура',
            theory: 'Теория',
            practice: 'Практика',
            dataset: 'Материалы',
            final: 'Финальная сборка',
            task_planning: 'План задач',
            context: 'Контекст',
        }[stage] || stage;
    }

    function applySelectedTarget() {
        const selectedId = document.getElementById('methodologyTargetSelect')?.value || '';
        if (!selectedId || !currentReviewState) return;
        const target = (currentReviewState.target_registry?.targets || []).find(item => item.id === selectedId);
        if (!target) return;
        const selector = document.getElementById('methodologyChangeSelector');
        const stage = document.getElementById('methodologyChangeStage');
        const scope = document.getElementById('methodologyChangeScope');
        if (selector) selector.value = target.id;
        if (stage) stage.value = target.stage || 'final';
        if (scope) scope.value = target.scope || 'local_section_only';
    }

    function renderReviewState(state) {
        const container = document.getElementById('methodologyReviewState');
        if (!container) return;
        checkpointMarkdownBlocks = [];
        const actions = Array.isArray(state?.review_actions) ? state.review_actions : [];
        const results = Array.isArray(state?.revision_results) ? state.revision_results : [];
        const changes = actions.filter(action => action.action === 'changes_requested');
        const targets = state?.target_registry?.targets || [];
        const pendingIds = Array.isArray(state?.pending_change_ids) ? state.pending_change_ids : [];
        const previewIds = new Set(Array.isArray(state?.preview_action_ids) ? state.preview_action_ids : []);
        const approvedIds = new Set(Array.isArray(state?.approved_action_ids) ? state.approved_action_ids : []);
        const changesHtml = changes.length
            ? `<ul class="methodology-stage-list">${changes.map((action, index) => {
                const req = action.details?.change_request || {};
                const actionId = pendingIds[index] || '';
                const changeStatus = approvedIds.has(actionId)
                    ? 'diff_approved'
                    : (previewIds.has(actionId) ? 'preview_ready' : 'pending');
                return `
                    <li class="methodology-stage-item action-pause">
                        <div class="methodology-stage-header">
                            <span>${esc(req.target_selector || `change-${index + 1}`)}</span>
                            <span>${esc(changeStatus)}</span>
                        </div>
                        <div class="methodology-stage-meta">${esc(req.target_stage || '')}/${esc(req.scope || '')}</div>
                        <div class="methodology-stage-meta">${esc(req.instruction || action.comment || '')}</div>
                    </li>
                `;
            }).join('')}</ul>`
            : '<div class="methodology-stage-meta">Запросов правок пока нет.</div>';
        const resultsHtml = results.length
            ? `<ul class="methodology-stage-list">${results.map(result => `
                <li class="methodology-stage-item action-${result.status === 'rejected' ? 'fail' : result.status === 'applied' ? 'continue' : 'warn'}">
                    <div class="methodology-stage-header">
                        <span>${esc(result.target_id || result.target_selector || result.target_stage)}</span>
                        <span>${esc(result.status)}</span>
                    </div>
                    <div class="methodology-stage-meta">
                        ${esc(result.target_label || result.target_kind || '')}
                        ${result.changed ? ` · ${esc(result.changed_chars)} симв.` : ''}
                    </div>
                    ${renderDiff(result.diff_preview)}
                    ${renderIssues(result.issues)}
                </li>
            `).join('')}</ul>`
            : '';
        const hasHistory = changes.length || results.length;
        const html = `
            ${renderCheckpoint(state?.checkpoint, {
                reviewState: state?.review_state || state?.status || 'needs_review',
                targetsCount: targets.length,
            })}
            <details class="methodology-history-details" ${hasHistory ? 'open' : ''}>
                <summary>
                    <span>История запросов и изменений</span>
                    <span>${esc(state?.review_state || state?.status || 'needs_review')}</span>
                </summary>
                <div class="methodology-history-body">
                    ${changesHtml}
                    ${resultsHtml}
                </div>
            </details>
        `;
        if (window.sanitize) {
            window.sanitize.safeSetHTML(container, html);
        } else {
            container.innerHTML = html;
        }
        hydrateCheckpointMarkdown(container);
        bindMarkdownSectionSwitchers(container);
        updateReviewActionAvailability();
    }

    function renderIssues(issues) {
        if (!Array.isArray(issues) || !issues.length) return '';
        return `<ul class="methodology-issue-list">${issues.map(issue => `<li>${esc(issue)}</li>`).join('')}</ul>`;
    }

    function renderRevisionResults(results) {
        return `
            <h3>Правки методолога</h3>
            <ul class="methodology-stage-list">
                ${results.map(result => `
                    <li class="methodology-stage-item action-${result.status === 'rejected' ? 'fail' : result.status === 'applied' ? 'continue' : 'warn'}">
                        <div class="methodology-stage-header">
                            <span>${esc(result.target_id || result.target_selector || result.target_stage)}</span>
                            <span>${esc(result.status)}</span>
                        </div>
                        <div class="methodology-stage-meta">${esc(result.target_label || result.target_kind || '')}</div>
                        ${renderDiff(result.diff_preview)}
                        ${renderIssues(result.issues)}
                    </li>
                `).join('')}
            </ul>
        `;
    }

    function renderDiff(diffLines) {
        if (!Array.isArray(diffLines) || !diffLines.length) return '';
        return `<div class="methodology-diff-preview">${diffLines.map(renderDiffLine).join('')}</div>`;
    }

    function renderDiffLine(line) {
        let cls = 'context';
        if (line.startsWith('+') && !line.startsWith('+++')) cls = 'added';
        if (line.startsWith('-') && !line.startsWith('---')) cls = 'removed';
        if (line.startsWith('@@')) cls = 'hunk';
        return `<div class="diff-line diff-${cls}">${esc(line) || '&nbsp;'}</div>`;
    }

    function setReviewBusy(isBusy) {
        reviewBusy = !!isBusy;
        updateReviewActionAvailability();
    }

    function updateReviewActionAvailability() {
        const state = currentReviewState || {};
        const pendingCount = Array.isArray(state.pending_change_ids) ? state.pending_change_ids.length : 0;
        const approveBtn = document.getElementById('methodologyApproveBtn');
        const approveDiffBtn = document.getElementById('methodologyApproveDiffBtn');
        const previewBtn = document.getElementById('methodologyPreviewChangesBtn');
        const simpleButtons = [
            'methodologyToggleChangeRequestBtn',
            'methodologyRejectBtn',
            'methodologySubmitChangeRequestBtn',
        ];

        if (approveBtn) {
            approveBtn.disabled = reviewBusy || !!state.requires_diff_approval;
            approveBtn.title = state.requires_diff_approval
                ? 'Сначала посмотрите и примите изменения'
                : '';
        }
        if (approveDiffBtn) {
            approveDiffBtn.disabled = reviewBusy
                || pendingCount === 0
                || state.review_state !== 'preview_ready'
                || !!state.preview_has_rejections;
            approveDiffBtn.title = approveDiffBtn.disabled && pendingCount > 0
                ? 'Изменения можно принять только после предпросмотра'
                : '';
        }
        if (previewBtn) {
            previewBtn.disabled = reviewBusy || pendingCount === 0;
            previewBtn.title = pendingCount === 0 ? 'Сначала сохраните запрос правок' : '';
        }
        simpleButtons.forEach((id) => {
            const button = document.getElementById(id);
            if (button) button.disabled = reviewBusy;
        });
    }

    async function approve() {
        const requestId = pendingRequestId || config.getCurrentRequestId();
        if (!requestId) return;
        const comment = document.getElementById('methodologyReviewComment')?.value || '';
        try {
            setReviewBusy(true);
            const response = await fetch(`${config.apiUrl}/generate/review/${requestId}/approve`, {
                method: 'POST',
                headers: {
                    ...config.getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ comment })
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorMessage(errorData.detail, response.status));
            }
            hideActions();
            config.onApproved(requestId, comment);
        } catch (error) {
            console.error('Ошибка продолжения генерации:', error);
            config.onError(`Не удалось продолжить генерацию: ${error.message}`);
        } finally {
            setReviewBusy(false);
        }
    }

    function renderCheckpoint(checkpoint, context = {}) {
        if (!checkpoint || typeof checkpoint !== 'object') return '';
        const artifact = checkpoint.artifact || {};
        const checkpointTitle = displayCheckpointTitle(checkpoint);
        const artifactDetails = Object.entries(artifact)
            .filter(([key, value]) => (
                !['title', 'annotation', 'markdown_sections'].includes(key)
                && value !== null
                && value !== undefined
                && value !== ''
            ))
            .map(([key, value]) => renderArtifactField(key, value))
            .join('');
        const fullMarkdownTitle = isFinalCheckpoint(checkpoint) ? 'Весь README' : 'Вся глава';
        const markdownSections = renderMarkdownSections(
            artifact.markdown_excerpt,
            artifact.markdown_sections,
            fullMarkdownTitle
        );
        const allowedTargets = Array.isArray(checkpoint.allowed_targets) && checkpoint.allowed_targets.length
            ? `<div class="methodology-stage-meta">Targets: ${checkpoint.allowed_targets.map(esc).join(', ')}</div>`
            : '';
        const targetCount = Number(context.targetsCount || 0);
        const targetInfo = targetCount
            ? `Доступно блоков для точечной правки: ${targetCount}.`
            : 'Сейчас доступен только текущий блок.';
        const generatedContent = `
            ${artifact.title ? `<div class="methodology-artifact-title">${esc(artifact.title)}</div>` : ''}
            ${artifact.annotation ? `<div class="methodology-artifact-text">${esc(artifact.annotation)}</div>` : ''}
            ${artifactDetails}
            ${markdownSections}
        `.trim() || '<div class="info-box">Содержимое для проверки пока не передано.</div>';
        return `
            <div class="methodology-checkpoint-layout">
                <details class="methodology-context-details">
                    <summary>
                        <span>Что проверяется</span>
                        <strong>${esc(checkpointTitle)}</strong>
                        <em>${esc(checkpoint.stage || '')}</em>
                    </summary>
                    <div class="methodology-context-body">
                        <div class="methodology-context-row">
                            <strong>Статус</strong>
                            <span>${esc(context.reviewState || 'needs_review')}</span>
                        </div>
                        <div class="methodology-context-row">
                            <strong>Пояснение</strong>
                            <span>${esc(checkpoint.summary || '')}</span>
                        </div>
                        <div class="methodology-context-row">
                            <strong>Правки</strong>
                            <span>${esc(targetInfo)}</span>
                        </div>
                        ${allowedTargets}
                    </div>
                </details>

                <section class="methodology-generated-block" aria-label="Сгенерированный блок для проверки">
                    <div class="methodology-generated-heading">
                        <span>Содержимое для проверки</span>
                    </div>
                    <div class="methodology-generated-content">
                        ${generatedContent}
                    </div>
                </section>
            </div>
        `;
    }

    function displayCheckpointTitle(checkpoint) {
        const stage = String(checkpoint?.stage || '').toLowerCase();
        const title = String(checkpoint?.title || '').trim();
        if (
            stage === 'title'
            || stage === 'title_annotation'
            || title.toLowerCase() === 'проверка названия проекта'
        ) {
            return 'Название и аннотация';
        }
        return title || 'Контрольная точка';
    }

    function isFinalCheckpoint(checkpoint) {
        const stage = String(checkpoint?.stage || '').toLowerCase();
        const id = String(checkpoint?.id || '').toLowerCase();
        const nodeId = String(checkpoint?.node_id || '').toLowerCase();
        return (
            stage === 'final'
            || ['quality', 'evaluation'].includes(id)
            || ['global_quality', 'evaluation'].includes(nodeId)
        );
    }

    function renderArtifactField(key, value) {
        const label = artifactLabel(key);
        if (key === 'markdown_excerpt') {
            return '';
        }
        if (key === 'requirements_matrix') {
            return renderRequirementsMatrix(value);
        }
        if (key === 'structure_outline' && Array.isArray(value)) {
            return renderStructureOutline(value);
        }
        if (Array.isArray(value)) {
            if (!value.length) return '';
            const visibleItems = key === 'structure_outline' ? value.slice(0, 40) : value.slice(0, 8);
            return `
                <div class="methodology-artifact-title">${label}</div>
                <ul class="methodology-artifact-list">
                    ${visibleItems.map(item => `<li>${renderArtifactInline(item)}</li>`).join('')}
                    ${value.length > visibleItems.length ? `<li>${esc(`Еще: ${value.length - visibleItems.length}`)}</li>` : ''}
                </ul>
            `;
        }
        if (typeof value === 'object') {
            return `
                <div class="methodology-artifact-title">${label}</div>
                <pre class="methodology-artifact-pre">${esc(JSON.stringify(value, null, 2))}</pre>
            `;
        }
        return `
            <div class="methodology-stage-meta">
                <strong>${label}:</strong> ${esc(value)}
            </div>
        `;
    }

    function renderRequirementsMatrix(items) {
        if (!Array.isArray(items) || !items.length) return '';
        const rows = items.map(item => {
            const passed = item?.passed === true || item?.status === 'pass';
            const status = passed ? 'pass' : 'fail';
            const statusText = passed ? 'pass' : 'fail';
            return `
                <li class="methodology-requirement-row status-${status}">
                    <span class="methodology-requirement-status">${esc(statusText)}</span>
                    <span class="methodology-requirement-title">${esc(item?.title || item?.id || 'Требование')}</span>
                    <span class="methodology-requirement-evidence">${esc(item?.evidence || '')}</span>
                </li>
            `;
        }).join('');
        return `
            <div class="methodology-requirements-matrix">
                <div class="methodology-artifact-title">Матрица требований</div>
                <ul class="methodology-requirements-list">
                    ${rows}
                </ul>
            </div>
        `;
    }

    function renderStructureOutline(items) {
        const normalized = Array.isArray(items) ? items.filter(Boolean) : [];
        if (!normalized.length) return '';
        const tree = [];
        normalized.forEach((item) => {
            const level = Number(item.level || 0);
            const title = String(item.title || '').trim();
            if (!title) return;
            const node = {
                level,
                title,
                kind: outlineKind(title, level),
                children: [],
            };
            if (level <= 2 || !tree.length) {
                tree.push(node);
                return;
            }
            tree[tree.length - 1].children.push(node);
        });

        return `
            <div class="methodology-artifact-title">Черновик структуры README</div>
            <div class="methodology-structure-hint">
                Это не готовые заголовки, а карта будущего README. Плейсхолдеры показывают слоты: названия теоретических разделов и практических заданий появятся на следующих этапах генерации.
            </div>
            <ol class="methodology-structure-tree">
                ${tree.map(renderStructureNode).join('')}
            </ol>
        `;
    }

    function renderStructureNode(node) {
        const children = node.children.length
            ? `<ol>${node.children.map(renderStructureNode).join('')}</ol>`
            : '';
        const placeholderHint = structurePlaceholderHint(node);
        return `
            <li class="methodology-structure-node level-${esc(node.level)}">
                <div class="methodology-structure-row">
                    <span class="methodology-structure-kind">${esc(node.kind)}</span>
                    <span class="methodology-structure-title">
                        ${esc(readableStructureTitle(node.title, node.kind))}
                        ${placeholderHint ? `<span class="methodology-structure-placeholder">${esc(placeholderHint)}</span>` : ''}
                    </span>
                </div>
                ${children}
            </li>
        `;
    }

    function readableStructureTitle(title, kind) {
        let text = String(title || '');
        text = text.replace(/<\s*название\s+раздела\s*>/gi, 'название раздела будет задано позже');
        text = text.replace(/<\s*название\s*>/gi, kind === 'задача'
            ? 'название задания будет задано позже'
            : 'название будет задано позже');
        return text;
    }

    function structurePlaceholderHint(node) {
        const title = String(node.title || '').toLowerCase();
        if (!/<\s*название/.test(title)) {
            if (node.kind === 'практика') {
                return 'Проверяется наличие практического блока, а не финальные формулировки задач.';
            }
            return '';
        }
        if (node.kind === 'задача') {
            return 'Это слот будущего задания; конкретика появится после генерации практики.';
        }
        if (node.kind === 'раздел' || node.kind === 'теория') {
            return 'Это слот будущего теоретического раздела.';
        }
        return 'Плейсхолдер будет заменен на следующем этапе.';
    }

    function outlineKind(title, level) {
        const lower = title.toLowerCase();
        if (level === 1) return 'проект';
        if (lower.includes('содержание')) return 'навигация';
        if (lower.includes('введение')) return 'введение';
        if (lower.includes('инструкция')) return 'инструкция';
        if (lower.includes('теорет')) return 'теория';
        if (lower.includes('практи')) return 'практика';
        if (lower.includes('задание') || lower.includes('задача')) return 'задача';
        if (lower.includes('бонус')) return 'бонус';
        return level <= 2 ? 'глава' : 'раздел';
    }

    function renderMarkdownSections(fullMarkdown, sections, fullTitle = 'Вся глава') {
        const normalizedFull = String(fullMarkdown || '').trim();
        const sectionItems = Array.isArray(sections)
            ? sections.filter(item => item && String(item.markdown || '').trim())
            : [];
        if (!normalizedFull && !sectionItems.length) return '';

        const blocks = [];
        if (normalizedFull) {
            blocks.push({
                id: 'full',
                title: fullTitle,
                markdown: normalizedFull,
            });
        }
        sectionItems.forEach((item, index) => {
            blocks.push({
                id: item.id || `section-${index + 1}`,
                title: item.title || `Раздел ${index + 1}`,
                markdown: String(item.markdown || ''),
            });
        });

        const groupId = `methodology-md-${checkpointMarkdownBlocks.length}`;
        const tabs = blocks.map((block, index) => (
            `<button class="methodology-section-tab ${index === 0 ? 'active' : ''}" type="button" data-section-index="${index}" data-section-title="${esc(block.title)}">${esc(block.title)}</button>`
        )).join('');
        const previews = blocks.map((block, index) => {
            const markdownIndex = registerMarkdownBlock(block.markdown);
            return `
                <div class="methodology-markdown-pane" data-pane-index="${index}" style="${index === 0 ? '' : 'display: none;'}">
                    <div class="methodology-active-section-title">Открыто: ${esc(block.title)}</div>
                    <div class="methodology-markdown-preview markdown-preview" data-markdown-index="${markdownIndex}">
                        <pre class="methodology-artifact-pre methodology-markdown-fallback">${esc(block.markdown)}</pre>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="methodology-artifact-title">Фрагмент README</div>
            <div class="methodology-markdown-viewer" data-markdown-group="${esc(groupId)}">
                ${blocks.length > 1 ? `
                    <div class="methodology-section-tabs" role="tablist" aria-label="Разделы README">
                        ${tabs}
                    </div>
                ` : ''}
                ${previews}
            </div>
        `;
    }

    function registerMarkdownBlock(markdown) {
        checkpointMarkdownBlocks.push(String(markdown || ''));
        return checkpointMarkdownBlocks.length - 1;
    }

    function hydrateCheckpointMarkdown(root) {
        if (!root) return;
        root.querySelectorAll('.methodology-markdown-preview').forEach((node, fallbackIndex) => {
            hydrateMarkdownPreviewNode(node, fallbackIndex);
        });
    }

    function hydrateMarkdownPreviewNode(node, fallbackIndex = 0) {
        if (!node) return;
        const rawIndex = node.getAttribute('data-markdown-index');
        const index = rawIndex === null ? fallbackIndex : Number(rawIndex);
        const markdown = checkpointMarkdownBlocks[index] || '';
        if (typeof window.renderMarkdownPreview === 'function') {
            window.renderMarkdownPreview(node, markdown, {
                emptyMessage: 'Markdown-фрагмент пуст.',
            });
            return;
        }

        setTimeout(() => {
            if (typeof window.renderMarkdownPreview === 'function') {
                window.renderMarkdownPreview(node, markdown, {
                    emptyMessage: 'Markdown-фрагмент пуст.',
                });
                return;
            }
            node.innerHTML = `<pre class="methodology-artifact-pre methodology-markdown-fallback">${esc(markdown)}</pre>`;
        }, 50);
    }

    function bindMarkdownSectionSwitchers(root) {
        if (!root) return;
        root.querySelectorAll('.methodology-section-tab').forEach(tab => {
            tab.addEventListener('click', () => {
                const viewer = tab.closest('.methodology-markdown-viewer');
                if (!viewer) return;
                const tabs = [...viewer.querySelectorAll('.methodology-section-tab')];
                const panes = [...viewer.querySelectorAll('.methodology-markdown-pane')];
                const fallbackIndex = Math.max(0, tabs.indexOf(tab));
                const selected = String(tab.getAttribute('data-section-index') ?? fallbackIndex);
                tabs.forEach(item => {
                    item.classList.toggle('active', item === tab);
                });
                panes.forEach((pane, index) => {
                    const paneIndex = String(pane.getAttribute('data-pane-index') ?? index);
                    pane.style.display = paneIndex === selected ? '' : 'none';
                });
                const selectedPane = panes.find((pane, index) => {
                    const paneIndex = String(pane.getAttribute('data-pane-index') ?? index);
                    return paneIndex === selected;
                });
                const selectedPreview = selectedPane?.querySelector('.methodology-markdown-preview');
                hydrateMarkdownPreviewNode(selectedPreview, fallbackIndex);
                if (selectedPreview) {
                    selectedPreview.scrollTop = 0;
                }
                try {
                    selectTargetForMarkdownSection(tab.getAttribute('data-section-title') || tab.textContent || '');
                } catch (error) {
                    console.debug('Не удалось синхронизировать target для markdown-секции:', error);
                }
            });
        });
    }

    function selectTargetForMarkdownSection(sectionTitle) {
        const normalizedTitle = normalizeSearchText(sectionTitle);
        const fullPreviewTitles = [normalizeSearchText('Вся глава'), normalizeSearchText('Весь README')];
        if (!normalizedTitle || fullPreviewTitles.includes(normalizedTitle) || !currentReviewState) return;
        const checkpointStage = normalizeCheckpointStage(currentReviewState?.checkpoint?.stage || '');
        const targets = currentReviewState.target_registry?.targets || [];
        const target = targets.find(item => (
            (!checkpointStage || normalizeCheckpointStage(item.stage) === checkpointStage)
            && targetMatchesTitle(item, normalizedTitle)
        )) || targets.find(item => targetMatchesTitle(item, normalizedTitle));
        if (!target) return;
        const select = document.getElementById('methodologyTargetSelect');
        if (!select) return;
        if (![...select.options].some(option => option.value === target.id)) {
            populateTargetSelect(currentReviewState);
        }
        select.value = target.id;
        applySelectedTarget();
    }

    function targetMatchesTitle(target, normalizedTitle) {
        const label = normalizeSearchText(target?.label || '');
        const selector = normalizeSearchText(target?.selector || '');
        const id = normalizeSearchText(target?.id || '');
        return [label, selector, id].some(value => value && (
            value === normalizedTitle || value.includes(normalizedTitle) || normalizedTitle.includes(value)
        ));
    }

    function normalizeSearchText(value) {
        return String(value || '')
            .toLowerCase()
            .replace(/[^\wа-яё0-9]+/gi, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function renderArtifactInline(value) {
        if (value === null || value === undefined) return '';
        if (typeof value !== 'object') return esc(value);
        if (value.level && value.title) {
            return `<span class="methodology-outline-level">H${esc(value.level)}</span> ${esc(value.title)}`;
        }
        const parts = [];
        if (value.title) parts.push(`<strong>${esc(value.title)}</strong>`);
        if (value.objective) parts.push(esc(value.objective));
        if (value.path) parts.push(`<code class="path-token">${esc(value.path)}</code>`);
        if (value.words !== undefined) parts.push(esc(`${value.words} слов`));
        if (value.bytes !== undefined) parts.push(esc(`${value.bytes} байт`));
        return parts.length ? parts.join(' · ') : esc(JSON.stringify(value));
    }

    function artifactLabel(key) {
        return {
            summary: 'Сводка',
            structure_outline: 'Структура README',
            theory_parts: 'Части теории',
            practice_tasks: 'Практические задачи',
            dataset_files: 'Materials',
            markdown_excerpt: 'Фрагмент README',
            markdown_chars: 'Размер README',
            warnings_count: 'Предупреждения',
            rubric_score: 'Оценка валидатора',
            rubric_failed_count: 'Непройденные критерии',
            issues_count: 'Замечания',
        }[key] || key;
    }

    async function reject() {
        const requestId = pendingRequestId || config.getCurrentRequestId();
        if (!requestId) return;
        const comment = document.getElementById('methodologyReviewComment')?.value || '';
        try {
            setReviewBusy(true);
            const response = await fetch(`${config.apiUrl}/generate/review/${requestId}/reject`, {
                method: 'POST',
                headers: {
                    ...config.getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ comment })
            });
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorMessage(errorData.detail, response.status));
            }
            hideActions();
            config.onRejected(requestId, comment);
        } catch (error) {
            console.error('Ошибка остановки генерации методологом:', error);
            config.onError(`Не удалось остановить генерацию: ${error.message}`);
        } finally {
            setReviewBusy(false);
        }
    }

    function toggleChangeRequestForm() {
        const form = document.getElementById('methodologyChangeRequestForm');
        if (!form) return;
        form.style.display = form.style.display === 'none' ? 'block' : 'none';
        renderChangeFeedback('', [], 'info', false);
    }

    function splitCsv(value) {
        return String(value || '')
            .split(',')
            .map((item) => item.trim())
            .filter(Boolean);
    }

    function changeRequestPayload() {
        return {
            target_stage: document.getElementById('methodologyChangeStage')?.value || 'final',
            target_selector: document.getElementById('methodologyChangeSelector')?.value || '',
            scope: document.getElementById('methodologyChangeScope')?.value || 'local_section_only',
            instruction: document.getElementById('methodologyChangeInstruction')?.value || '',
            issue_codes: splitCsv(document.getElementById('methodologyChangeIssueCodes')?.value || ''),
            forbidden_changes: splitCsv(document.getElementById('methodologyChangeForbidden')?.value || ''),
            expected_outcome: document.getElementById('methodologyChangeExpected')?.value || ''
        };
    }

    function renderChangeFeedback(message, conflicts = [], kind = 'info', visible = true) {
        const node = document.getElementById('methodologyChangeFeedback');
        if (!node) return;
        if (!visible) {
            node.style.display = 'none';
            node.innerHTML = '';
            return;
        }
        const conflictHtml = Array.isArray(conflicts) && conflicts.length
            ? `<ul>${conflicts.map(conflict => (
                `<li>${esc(conflict.severity || 'hard')} · ${esc(conflict.code || '')}: ${esc(conflict.message || '')}</li>`
            )).join('')}</ul>`
            : '';
        node.className = `methodology-review-feedback ${kind === 'error' ? 'error-msg' : 'info-box'}`;
        node.style.display = 'block';
        const html = `<div>${esc(message)}</div>${conflictHtml}`;
        if (window.sanitize) {
            window.sanitize.safeSetHTML(node, html);
        } else {
            node.innerHTML = html;
        }
    }

    async function requestChanges() {
        const requestId = pendingRequestId || config.getCurrentRequestId();
        if (!requestId) return;
        const payload = changeRequestPayload();
        if (!payload.instruction.trim()) {
            renderChangeFeedback('Опишите запрос правки.', [], 'error');
            return;
        }
        try {
            setReviewBusy(true);
            const response = await fetch(`${config.apiUrl}/generate/review/${requestId}/request-changes`, {
                method: 'POST',
                headers: {
                    ...config.getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });
            const responseData = await response.json().catch(() => ({}));
            if (!response.ok) {
                const detail = responseData.detail || {};
                if (response.status === 409 && Array.isArray(detail.conflicts)) {
                    renderChangeFeedback(detail.message || 'Запрос конфликтует с hard rules.', detail.conflicts, 'error');
                    return;
                }
                const message = typeof detail === 'string'
                    ? detail
                    : (detail.message || `Ошибка ${response.status}`);
                throw new Error(message);
            }
            renderChangeFeedback(responseData.message || 'Запрос правок сохранен. Генерация остается на паузе.', responseData.conflicts || [], 'info');
            currentReviewState = {
                ...(currentReviewState || {}),
                review_actions: responseData.review_actions || currentReviewState?.review_actions || [],
                review_state: responseData.review_state || currentReviewState?.review_state,
                requires_diff_approval: responseData.requires_diff_approval ?? currentReviewState?.requires_diff_approval,
                pending_change_ids: responseData.pending_change_ids || currentReviewState?.pending_change_ids || [],
                preview_action_ids: responseData.preview_action_ids || [],
                approved_action_ids: responseData.approved_action_ids || [],
                target_registry: responseData.target_registry || currentReviewState?.target_registry || {},
            };
            renderReviewState(currentReviewState);
            fetchReviewState(requestId);
            config.onChangeRequested(requestId, payload, responseData);
        } catch (error) {
            console.error('Ошибка сохранения запроса правок:', error);
            config.onError(`Не удалось сохранить запрос правок: ${error.message}`);
        } finally {
            setReviewBusy(false);
        }
    }

    async function previewChanges() {
        const requestId = pendingRequestId || config.getCurrentRequestId();
        if (!requestId) return;
        renderChangeFeedback('Выполняется предпросмотр правок...', [], 'info');
        try {
            setReviewBusy(true);
            const response = await fetch(`${config.apiUrl}/generate/review/${requestId}/preview-changes`, {
                method: 'POST',
                headers: {
                    ...config.getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({})
            });
            const responseData = await response.json().catch(() => ({}));
            if (!response.ok) {
                const detail = responseData.detail || {};
                const message = typeof detail === 'string'
                    ? detail
                    : (detail.message || `Ошибка ${response.status}`);
                throw new Error(message);
            }
            currentReviewState = {
                ...(currentReviewState || {}),
                revision_results: responseData.revision_results || [],
                review_actions: responseData.review_actions || currentReviewState?.review_actions || [],
                review_state: responseData.review_state || currentReviewState?.review_state,
                requires_diff_approval: responseData.requires_diff_approval ?? currentReviewState?.requires_diff_approval,
                pending_change_ids: responseData.pending_change_ids || currentReviewState?.pending_change_ids || [],
                preview_action_ids: responseData.preview_action_ids
                    || responseData.revision_results?.map(item => item.action_id).filter(Boolean)
                    || [],
                approved_action_ids: responseData.approved_action_ids || [],
                preview_hash: responseData.preview_hash || '',
                preview_markdown: responseData.preview_markdown || '',
                preview_has_rejections: !!responseData.preview_has_rejections,
                target_registry: responseData.target_registry || currentReviewState?.target_registry || {},
                checkpoint: responseData.checkpoint || currentReviewState?.checkpoint,
            };
            renderReviewState(currentReviewState);
            const message = responseData.preview_has_rejections
                ? 'Некоторые правки отклонены защитными правилами. Уточните запрос и попробуйте снова.'
                : 'Изменения готовы. Проверьте их и нажмите «Принять изменения».';
            renderChangeFeedback(message, [], responseData.preview_has_rejections ? 'error' : 'info');
        } catch (error) {
            console.error('Ошибка предпросмотра правок:', error);
            renderChangeFeedback(`Не удалось выполнить предпросмотр: ${error.message}`, [], 'error');
        } finally {
            setReviewBusy(false);
        }
    }

    async function approveDiff() {
        const requestId = pendingRequestId || config.getCurrentRequestId();
        if (!requestId) return;
        const comment = document.getElementById('methodologyReviewComment')?.value || '';
        try {
            setReviewBusy(true);
            const response = await fetch(`${config.apiUrl}/generate/review/${requestId}/approve-diff`, {
                method: 'POST',
                headers: {
                    ...config.getAuthHeaders(),
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ comment })
            });
            const responseData = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(errorMessage(responseData.detail, response.status));
            }
            currentReviewState = responseData;
            populateTargetSelect(currentReviewState);
            renderReviewState(currentReviewState);
            renderChangeFeedback(responseData.message || 'Изменения приняты.', [], 'info');
            config.onDiffApproved(requestId, responseData);
        } catch (error) {
            console.error('Ошибка подтверждения diff:', error);
            renderChangeFeedback(`Не удалось принять изменения: ${error.message}`, [], 'error');
        } finally {
            setReviewBusy(false);
        }
    }

    function errorMessage(detail, status) {
        if (!detail) return `Ошибка ${status}`;
        if (typeof detail === 'string') return detail;
        if (detail.message) return detail.message;
        return `Ошибка ${status}`;
    }

    window.methodologyPanel = {
        configure,
        render,
        showActions,
        hideActions,
    };
})();
