// Generation session persistence.
// Keeps sessionStorage serialization outside main.js while using its runtime state contract.

function getGenerationPersistenceRuntime() {
    return window.ContentGenGenerationRuntime || {};
}

function getGenerationPersistenceState() {
    const runtime = getGenerationPersistenceRuntime();
    return typeof runtime.getState === 'function' ? runtime.getState() : {};
}

function setGenerationPersistenceState(updates) {
    const runtime = getGenerationPersistenceRuntime();
    if (typeof runtime.setState === 'function') {
        runtime.setState(updates || {});
    }
}

function getGenerationApiUrl() {
    const runtime = getGenerationPersistenceRuntime();
    if (typeof runtime.getApiUrl === 'function') return runtime.getApiUrl();
    return window.ContentGenApiUrl || window.API_URL || `${window.location.origin}/api/v1`;
}

function getGenerationAuthHeaders() {
    const runtime = getGenerationPersistenceRuntime();
    if (typeof runtime.getAuthHeaders === 'function') return runtime.getAuthHeaders();
    if (typeof window.getAuthHeaders === 'function') return window.getAuthHeaders();
    const token = localStorage.getItem('auth_token');
    return {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json'
    };
}

function setGenerationButtonState(disabled, text = 'Сгенерировать') {
    const button = document.getElementById('generateBtn');
    if (!button) return;
    button.disabled = !!disabled;
    button.textContent = text;
}

function saveGenerationState() {
    try {
        const state = getGenerationPersistenceState();
        const payload = {
            requestId: state.currentRequestId,
            markdown: state.currentMarkdown,
            originalMarkdown: state.originalMarkdown,
            result: state.currentResult,
            seed: state.currentSeed,
            originalRubric: state.originalRubric,
            originalTextStats: state.originalTextStats,
            regeneratedRubric: state.regeneratedRubric,
            regeneratedTextStats: state.regeneratedTextStats,
            regeneratedMarkdown: state.regeneratedMarkdown || null,
            generationStartTime: state.generationStartTime,
            lastKnownGenerationPhase: state.lastKnownGenerationPhase,
            lastKnownGenerationProgress: state.lastKnownGenerationProgress,
            lastKnownGenerationAgent: state.lastKnownGenerationAgent,
            currentGenerationStatus: state.currentGenerationStatus,
            workflowProfile: state.workflowProfile || null,
            timestamp: Date.now()
        };
        sessionStorage.setItem('generation_state', JSON.stringify(payload));
        console.log('✅ Состояние генерации сохранено в sessionStorage', {
            hasOriginalRubric: !!payload.originalRubric,
            hasRegeneratedRubric: !!payload.regeneratedRubric,
            hasOriginalTextStats: !!payload.originalTextStats,
            hasRegeneratedTextStats: !!payload.regeneratedTextStats
        });
    } catch (error) {
        console.error('❌ Ошибка сохранения состояния:', error);
    }
}

async function loadGenerationState() {
    try {
        const saved = sessionStorage.getItem('generation_state');
        if (!saved) return false;

        const savedState = JSON.parse(saved);
        const maxAge = 24 * 60 * 60 * 1000;
        if (!savedState.timestamp || (Date.now() - savedState.timestamp) >= maxAge) {
            clearGenerationState();
            return false;
        }

        setGenerationPersistenceState({
            currentRequestId: savedState.requestId,
            currentMarkdown: savedState.markdown,
            originalMarkdown: savedState.originalMarkdown || null,
            currentResult: savedState.result,
            currentSeed: savedState.seed,
            generationStartTime: savedState.generationStartTime || null,
            lastKnownGenerationPhase: savedState.lastKnownGenerationPhase || null,
            lastKnownGenerationProgress: Number(savedState.lastKnownGenerationProgress || 0),
            lastKnownGenerationAgent: savedState.lastKnownGenerationAgent || 'Инициализация...',
            currentGenerationStatus: savedState.currentGenerationStatus || 'idle',
            workflowProfile: savedState.workflowProfile || undefined
        });

        let state = getGenerationPersistenceState();
        if (state.currentRequestId) {
            const shouldContinueRestore = await reconcileSavedGenerationWithServer(savedState, state.currentRequestId);
            if (shouldContinueRestore === false) return false;
            if (shouldContinueRestore === true) return true;
        }

        restoreSavedMetrics(savedState);
        state = getGenerationPersistenceState();

        if (state.currentSeed && typeof window.fillFormFromData === 'function') {
            window.fillFormFromData(state.currentSeed);
        }

        if (state.currentResult && typeof state.currentResult === 'object') {
            if (typeof state.currentResult.markdown !== 'string') {
                console.warn('⚠️ currentResult не содержит markdown при восстановлении:', state.currentResult);
                return false;
            }

            try {
                window.displayResults?.({
                    result: state.currentResult,
                    request_id: state.currentRequestId,
                    warnings: []
                });
            } catch (displayError) {
                console.error('❌ Ошибка при восстановлении отображения результатов:', displayError);
                clearGenerationState();
                return false;
            }

            renderRestoredMetrics();
        }

        if (state.currentSeed && typeof window.restoreFormData === 'function') {
            window.restoreFormData(state.currentSeed);
        }

        console.log('✅ Состояние генерации восстановлено из sessionStorage');
        return true;
    } catch (error) {
        console.error('❌ Ошибка восстановления состояния:', error);
        clearGenerationState();
        return false;
    }
}

async function reconcileSavedGenerationWithServer(savedState, requestId) {
    try {
        const response = await fetch(`${getGenerationApiUrl()}/generate/status/${requestId}`, {
            headers: getGenerationAuthHeaders()
        });

        if (response.status === 404) {
            console.log('⚠️ Запрос генерации не найден на сервере');
            clearGenerationState();
            return false;
        }
        if (!response.ok) return null;

        const statusData = await response.json();
        const status = statusData.status;
        const workflowMeta = window.workflowUiOptions ? window.workflowUiOptions(statusData) : {};
        setGenerationPersistenceState({
            currentGenerationStatus: status || 'idle',
            workflowProfile: statusData.workflow_profile || undefined
        });

        if (status === 'pending' || status === 'in_progress') {
            console.log('🔄 Генерация еще идет, возобновляем polling...');
            const generationLogs = document.getElementById('generationLogs');
            if (generationLogs) generationLogs.style.display = 'block';

            const latest = getGenerationPersistenceState();
            const progress = Math.max(workflowMeta.progress || 0, latest.lastKnownGenerationProgress || 0, 1);
            window.showCompactGenerationProgress?.('Генерация проекта продолжается...', {
                progress,
                agent: workflowMeta.agent || latest.lastKnownGenerationAgent || 'Продолжение генерации'
            });
            window.showGenerationRunView?.(latest.currentSeed || {}, {
                phase: workflowMeta.phase || latest.lastKnownGenerationPhase || 'initialization',
                status,
                progress,
                agent: workflowMeta.agent || latest.lastKnownGenerationAgent || 'Продолжение генерации'
            });
            window.startTimer?.();
            window.pollGenerationStatus?.(requestId);
            setGenerationButtonState(true, 'Генерация...');
            return true;
        }

        if (status === 'needs_review') {
            const latest = getGenerationPersistenceState();
            const message = statusData.error || 'Требуется ручная методологическая проверка';
            window.showGenerationRunView?.(latest.currentSeed || {}, {
                phase: workflowMeta.phase || statusData.methodology?.checkpoint?.stage || latest.lastKnownGenerationPhase || 'methodology_review',
                status,
                methodology: statusData.methodology || null,
                progress: Math.max(
                    workflowMeta.progress || 0,
                    latest.lastKnownGenerationProgress || 0,
                    window.progressFromCheckpointStage?.(statusData.methodology?.checkpoint?.stage) || 0,
                    1
                ),
                message,
                agent: workflowMeta.agent || 'Ожидание методолога'
            });
            window.showMethodologyReviewActions?.(requestId, message);
            setGenerationButtonState(false);
            return true;
        }

        if (status === 'failed') {
            console.log('❌ Генерация завершилась с ошибкой');
            setLogError(`Ошибка генерации: ${statusData.error || 'Неизвестная ошибка'}`);
            clearGenerationState();
            return false;
        }

        if (status === 'completed') {
            console.log('✅ Генерация завершена, загружаем результат...');
            if (!statusData.result) {
                console.warn('⚠️ Результат генерации не найден');
                clearGenerationState();
                return false;
            }

            setGenerationPersistenceState({
                currentResult: statusData.result,
                currentMarkdown: statusData.result?.markdown || '',
                originalMarkdown: statusData.result?.markdown || '',
                originalRubric: statusData.result.rubric && !savedState.originalRubric
                    ? statusData.result.rubric
                    : undefined,
                originalTextStats: statusData.result.text_stats && !savedState.originalTextStats
                    ? statusData.result.text_stats
                    : undefined,
                workflowProfile: statusData.workflow_profile || statusData.result.workflow_profile || undefined
            });
            saveGenerationState();
        }

        return null;
    } catch (error) {
        console.error('❌ Ошибка при проверке статуса генерации:', error);
        return null;
    }
}

function restoreSavedMetrics(savedState) {
    const state = getGenerationPersistenceState();
    if (savedState.originalRubric) {
        setGenerationPersistenceState({ originalRubric: savedState.originalRubric });
        console.log('✅ originalRubric восстановлен из sessionStorage:', savedState.originalRubric.items?.length || 0, 'критериев');
    } else if (state.currentResult?.rubric) {
        setGenerationPersistenceState({ originalRubric: state.currentResult.rubric });
        console.log('✅ originalRubric восстановлен из currentResult:', state.currentResult.rubric.items?.length || 0, 'критериев');
    }

    if (savedState.originalTextStats) {
        setGenerationPersistenceState({ originalTextStats: savedState.originalTextStats });
        console.log('✅ originalTextStats восстановлен из sessionStorage');
    } else if (state.currentResult?.text_stats) {
        setGenerationPersistenceState({ originalTextStats: state.currentResult.text_stats });
        console.log('✅ originalTextStats восстановлен из currentResult');
    }

    if (savedState.regeneratedRubric) {
        setGenerationPersistenceState({ regeneratedRubric: savedState.regeneratedRubric });
        console.log('✅ regeneratedRubric восстановлен из sessionStorage:', savedState.regeneratedRubric.items?.length || 0, 'критериев');
    }
    if (savedState.regeneratedTextStats) {
        setGenerationPersistenceState({ regeneratedTextStats: savedState.regeneratedTextStats });
        console.log('✅ regeneratedTextStats восстановлен из sessionStorage');
    }
    if (savedState.regeneratedMarkdown) {
        setGenerationPersistenceState({ regeneratedMarkdown: savedState.regeneratedMarkdown });
        console.log('✅ regeneratedMarkdown восстановлен из sessionStorage');
    }
}

function renderRestoredMetrics() {
    const state = getGenerationPersistenceState();
    if (state.originalRubric) {
        window.displayMetrics?.(state.originalRubric, 'metricsContentOriginal');
        console.log('✅ Оригинальные метрики отображены после восстановления');
    }
    if (state.originalTextStats) {
        window.displayReport?.({ text_stats: state.originalTextStats }, 'reportContentOriginal');
        console.log('✅ Оригинальный отчет отображен после восстановления');
    }
    if (state.regeneratedRubric) {
        window.displayMetrics?.(state.regeneratedRubric, 'metricsContentRegen');
        console.log('✅ Перегенерированные метрики отображены после восстановления');
    }
    if (state.regeneratedTextStats) {
        window.displayReport?.({ text_stats: state.regeneratedTextStats }, 'reportContentRegen');
        console.log('✅ Перегенерированный отчет отображен после восстановления');
    }

    window.updateVersionButtons?.();
    if (state.originalRubric) {
        window.switchMetricsVersion?.('original');
    } else if (state.regeneratedRubric) {
        window.switchMetricsVersion?.('regenerated');
    }
    if (state.originalTextStats) {
        window.switchReportVersion?.('original');
    } else if (state.regeneratedTextStats) {
        window.switchReportVersion?.('regenerated');
    }
}

function setLogError(message) {
    const logContent = document.getElementById('logContent');
    if (!logContent) return;
    if (window.sanitize) {
        window.sanitize.safeSetErrorMessage(logContent, message);
    } else {
        logContent.textContent = message;
    }
}

function clearGenerationState() {
    try {
        sessionStorage.removeItem('generation_state');
        setGenerationPersistenceState({
            currentRequestId: null,
            currentMarkdown: null,
            originalMarkdown: null,
            currentTranslatedMarkdown: null,
            currentResult: null,
            currentSeed: null,
            lastKnownGenerationPhase: null,
            lastKnownGenerationProgress: 0,
            lastKnownGenerationAgent: 'Инициализация...',
            currentGenerationStatus: 'idle',
            workflowProfile: 'standard'
        });
        window.finishGenerationRun?.('idle');
        const runtime = getGenerationPersistenceRuntime();
        if (typeof runtime.hideMethodologyAssistantChat === 'function') {
            runtime.hideMethodologyAssistantChat();
        }
        console.log('✅ Состояние генерации очищено');
    } catch (error) {
        console.error('❌ Ошибка очистки состояния:', error);
    }
}

Object.assign(window, {
    saveGenerationState,
    loadGenerationState,
    clearGenerationState
});
