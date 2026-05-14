// Floating methodology assistant chat for generation runtime.
// The module owns DOM events and review-change submission; main.js only passes runtime state.

(function () {
    let config = {};
    let flushInProgress = false;

    function configure(options = {}) {
        config = { ...config, ...options };
    }

    function getState() {
        if (typeof config.getState === 'function') {
            return config.getState() || {};
        }
        if (window.ContentGenGenerationRuntime?.getState) {
            return window.ContentGenGenerationRuntime.getState() || {};
        }
        return {};
    }

    function getApiUrl() {
        if (typeof config.getApiUrl === 'function') {
            return config.getApiUrl();
        }
        return window.ContentGenApiUrl || window.API_URL || `${window.location.origin}/api/v1`;
    }

    function getAuthHeaders() {
        if (typeof config.getAuthHeaders === 'function') {
            return config.getAuthHeaders();
        }
        if (typeof window.getAuthHeaders === 'function') {
            return window.getAuthHeaders();
        }
        const token = localStorage.getItem('auth_token');
        return token
            ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
            : { 'Content-Type': 'application/json' };
    }

    function escapeHtml(value) {
        if (typeof window.escapeHtmlSafe === 'function') {
            return window.escapeHtmlSafe(value);
        }
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function currentStageId() {
        const state = getState();
        if (typeof window.runStageFromPhase === 'function') {
            return window.runStageFromPhase(state.lastKnownGenerationPhase);
        }
        return state.lastKnownGenerationPhase || 'pipeline';
    }

    function currentRequestId() {
        return getState().currentRequestId || '';
    }

    function pendingKey(requestId = currentRequestId()) {
        return requestId ? `methodology_assistant_pending:${requestId}` : '';
    }

    function loadPendingCommands(requestId = currentRequestId()) {
        const key = pendingKey(requestId);
        if (!key) return [];
        try {
            const raw = sessionStorage.getItem(key);
            const parsed = raw ? JSON.parse(raw) : [];
            return Array.isArray(parsed) ? parsed.filter(item => item && item.text) : [];
        } catch (_error) {
            return [];
        }
    }

    function savePendingCommands(commands, requestId = currentRequestId()) {
        const key = pendingKey(requestId);
        if (!key) return;
        const safeCommands = Array.isArray(commands) ? commands.filter(item => item && item.text) : [];
        if (!safeCommands.length) {
            sessionStorage.removeItem(key);
            return;
        }
        sessionStorage.setItem(key, JSON.stringify(safeCommands.slice(-20)));
    }

    function queuePendingCommand(text, requestId = currentRequestId()) {
        const commands = loadPendingCommands(requestId);
        commands.push({
            text,
            queued_at: new Date().toISOString(),
            stage: currentStageId(),
        });
        savePendingCommands(commands, requestId);
    }

    function show(status = getState().currentGenerationStatus) {
        const chat = document.getElementById('methodologyAssistantChat');
        if (!chat) return;
        chat.style.display = 'grid';
        updateStatus(status, currentStageId());
    }

    function hide() {
        const chat = document.getElementById('methodologyAssistantChat');
        if (chat) {
            chat.style.display = 'none';
        }
    }

    function updateStatus(status = getState().currentGenerationStatus, stageId = currentStageId()) {
        const statusNode = document.getElementById('assistantChatStatus');
        const stageNode = document.getElementById('assistantChatStage');
        if (statusNode) {
            const labels = {
                pending: 'запуск ожидает',
                in_progress: 'генерация активна',
                needs_review: 'контрольная точка',
                completed: 'результат готов',
                failed: 'ошибка генерации',
                cancelled: 'остановлено'
            };
            statusNode.textContent = labels[status] || 'готов к комментариям';
        }
        if (stageNode) {
            stageNode.textContent = String(stageId || 'pipeline').toUpperCase();
        }
        if (status === 'needs_review') {
            flushPendingCommands();
        }
    }

    function appendMessage(role, text) {
        const messages = document.getElementById('assistantChatMessages');
        if (!messages || !text) return;
        const node = document.createElement('div');
        node.className = `assistant-message ${role === 'user' ? 'user' : 'assistant'}`;
        const avatar = role === 'user'
            ? (document.getElementById('generatorUserInitials')?.textContent || 'Вы')
            : 'М';
        node.innerHTML = `<span>${escapeHtml(avatar)}</span><div>${escapeHtml(text)}</div>`;
        messages.appendChild(node);
        messages.scrollTop = messages.scrollHeight;
    }

    function commandLabel(command) {
        return {
            approve: 'продолжить генерацию',
            request_changes: 'запросить правку',
            simplify_task: 'упростить задачу',
            add_example: 'добавить пример',
            fix_failed_criteria: 'исправить непройденные критерии',
            regenerate_section: 'перегенерировать раздел'
        }[command] || command || 'команда';
    }

    async function submitCommand(text, { appendUser = true, fromQueue = false } = {}) {
        const state = getState();
        show(state.currentGenerationStatus);
        if (appendUser) {
            appendMessage('user', text);
        }

        if (state.currentGenerationStatus === 'needs_review' && state.currentRequestId) {
            try {
                const response = await fetch(`${getApiUrl()}/generate/review/${state.currentRequestId}/assistant-command`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                    body: JSON.stringify({
                        message: text,
                        selected_target_id: null
                    })
                });
                const responseData = await response.json().catch(() => ({}));
                if (!response.ok) {
                    const detail = responseData.detail || responseData || {};
                    throw new Error(detail.detail || detail.message || `Ошибка ${response.status}`);
                }
                const parsed = responseData.assistant_command || {};
                appendMessage('assistant', `${fromQueue ? 'Очередь применена. ' : ''}Распознано: ${commandLabel(parsed.command)}.`);
                const message = parsed.command === 'regenerate_section'
                    ? 'Раздел отправлен на перегенерацию из durable checkpoint.'
                    : 'Команда из чата сохранена. Проверьте список правок и продолжайте генерацию, когда будете готовы.';
                if (typeof config.showMethodologyReviewActions === 'function') {
                    config.showMethodologyReviewActions(state.currentRequestId, message);
                } else if (typeof window.showMethodologyReviewActions === 'function') {
                    window.showMethodologyReviewActions(state.currentRequestId, message);
                }
            } catch (error) {
                if (fromQueue) {
                    queuePendingCommand(text, state.currentRequestId);
                }
                appendMessage('assistant', `Не удалось выполнить workflow-команду: ${error.message}.`);
            }
            return;
        }

        if (state.currentRequestId) {
            queuePendingCommand(text, state.currentRequestId);
            appendMessage('assistant', 'Команда поставлена в очередь. На ближайшей контрольной точке я отправлю ее как валидируемую workflow-команду.');
        } else {
            appendMessage('assistant', 'Нет активного запуска: команда не отправлена в workflow.');
        }
    }

    async function flushPendingCommands() {
        const requestId = currentRequestId();
        const state = getState();
        if (flushInProgress || !requestId || state.currentGenerationStatus !== 'needs_review') return;
        const commands = loadPendingCommands(requestId);
        if (!commands.length) return;
        flushInProgress = true;
        try {
            savePendingCommands([], requestId);
            appendMessage('assistant', `Отправляю pending-команд${commands.length === 1 ? 'у' : 'ы'} методолога в workflow.`);
            for (const item of commands) {
                await submitCommand(item.text, { appendUser: false, fromQueue: true });
            }
        } finally {
            flushInProgress = false;
        }
    }

    async function send(rawText = '') {
        const input = document.getElementById('assistantChatInput');
        const text = (rawText || input?.value || '').trim();
        if (!text) return;
        if (input) input.value = '';
        await submitCommand(text);
    }

    function initialize() {
        document.getElementById('assistantChatSend')?.addEventListener('click', () => send());
        document.getElementById('assistantChatClose')?.addEventListener('click', hide);
        document.getElementById('assistantChatInput')?.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                send();
            }
        });
        document.querySelectorAll('[data-assistant-suggestion]').forEach((button) => {
            button.addEventListener('click', () => {
                const input = document.getElementById('assistantChatInput');
                if (!input) return;
                input.value = button.getAttribute('data-assistant-suggestion') || '';
                input.focus();
            });
        });
    }

    window.MethodologyAssistantChat = {
        configure,
        show,
        hide,
        updateStatus,
        appendMessage,
        send,
        flushPendingCommands,
        initialize,
    };
})();
