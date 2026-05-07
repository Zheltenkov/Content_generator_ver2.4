/**
 * Управление индикаторами загрузки и прогресс-барами
 */

class LoadingManager {
    constructor() {
        this.progressBars = new Map();
        this.generationStages = [
            { label: 'Контекст', start: 0, end: 20 },
            { label: 'План', start: 20, end: 35, tone: 'warm' },
            { label: 'Теория', start: 35, end: 60 },
            { label: 'Практика', start: 60, end: 78 },
            { label: 'Проверка', start: 78, end: 100 }
        ];
    }

    /**
     * Проверяет, что индикатор рисуется в компактной области генерации README.
     */
    isGenerationProgressContainer(container) {
        if (!container) return false;
        return container.id === 'logContent' || container.classList?.contains('generation-progress-strip');
    }

    /**
     * Создает компактную горизонтальную шкалу этапов генерации.
     */
    createGenerationPhaseProgress(container) {
        const progressId = `progress-${Date.now()}`;
        const progressBar = document.createElement('div');
        progressBar.id = progressId;
        progressBar.className = 'generation-phase-strip';
        progressBar.innerHTML = this.generationStages.map(stage => `
            <div class="generation-phase-card ${stage.tone === 'warm' ? 'is-warm' : ''}" data-start="${stage.start}" data-end="${stage.end}">
                <span class="generation-phase-label">${stage.label}</span>
                <div class="generation-phase-track">
                    <div class="generation-phase-fill"></div>
                </div>
            </div>
        `).join('');

        container.appendChild(progressBar);

        this.progressBars.set(progressId, {
            type: 'generation-phase',
            element: progressBar,
            stages: this.generationStages,
            cards: Array.from(progressBar.querySelectorAll('.generation-phase-card')),
            fills: Array.from(progressBar.querySelectorAll('.generation-phase-fill'))
        });

        return progressId;
    }

    /**
     * Показывает spinner в элементе
     */
    showSpinner(container, message = 'Загрузка...') {
        if (typeof container === 'string') {
            container = document.getElementById(container);
        }

        const spinnerId = `spinner-${Date.now()}`;
        const spinner = document.createElement('div');

        if (this.isGenerationProgressContainer(container)) {
            spinner.id = spinnerId;
            spinner.className = 'generation-activity';
            spinner.innerHTML = `
                <span class="generation-activity-dot"></span>
                <span>${message}</span>
            `;
            if (container) {
                container.appendChild(spinner);
            }
            return spinnerId;
        }

        spinner.id = spinnerId;
        spinner.className = 'loading-spinner';
        spinner.innerHTML = `
            <div class="spinner-wrapper">
                <div class="spinner"></div>
                <p style="margin-top: 1rem; color: #b8c5d6;">${message}</p>
            </div>
        `;
        spinner.style.cssText = `
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
            min-height: 200px;
        `;

        if (container) {
            container.appendChild(spinner);
        }

        return spinnerId;
    }

    /**
     * Удаляет spinner
     */
    hideSpinner(spinnerId) {
        const spinner = document.getElementById(spinnerId);
        if (spinner) {
            spinner.remove();
        }
    }

    /**
     * Создает прогресс-бар
     */
    createProgressBar(containerId, label = 'Прогресс') {
        const container = document.getElementById(containerId);
        if (!container) return null;

        if (this.isGenerationProgressContainer(container)) {
            return this.createGenerationPhaseProgress(container);
        }

        const progressId = `progress-${Date.now()}`;
        const progressBar = document.createElement('div');
        progressBar.id = progressId;
        progressBar.className = 'progress-bar-container';
        progressBar.innerHTML = `
            <div style="display: flex; justify-content: space-between; margin-bottom: 0.5rem;">
                <span style="color: #b8c5d6; font-weight: 600;">${label}</span>
                <span class="progress-percent" style="color: #64ffda; font-weight: 600;">0%</span>
            </div>
            <div class="progress-bar-track" style="
                width: 100%;
                height: 8px;
                background: rgba(118, 75, 162, 0.2);
                border-radius: 4px;
                overflow: hidden;
            ">
                <div class="progress-bar-fill" style="
                    height: 100%;
                    width: 0%;
                    background: linear-gradient(90deg, #764ba2 0%, #64ffda 100%);
                    border-radius: 4px;
                    transition: width 0.3s ease;
                "></div>
            </div>
        `;

        container.appendChild(progressBar);

        this.progressBars.set(progressId, {
            element: progressBar,
            fill: progressBar.querySelector('.progress-bar-fill'),
            percent: progressBar.querySelector('.progress-percent')
        });

        return progressId;
    }

    /**
     * Обновляет прогресс-бар
     */
    updateProgress(progressId, percent) {
        const progress = this.progressBars.get(progressId);
        if (!progress) return;

        const clampedPercent = Math.max(0, Math.min(100, percent));
        if (progress.type === 'generation-phase') {
            progress.stages.forEach((stage, index) => {
                const range = Math.max(1, stage.end - stage.start);
                const localPercent = Math.max(0, Math.min(100, ((clampedPercent - stage.start) / range) * 100));
                const fill = progress.fills[index];
                const card = progress.cards[index];

                if (fill) {
                    fill.style.width = `${localPercent}%`;
                }
                if (card) {
                    card.classList.toggle('is-active', clampedPercent >= stage.start && clampedPercent < stage.end);
                    card.classList.toggle('is-complete', clampedPercent >= stage.end);
                }
            });
            return;
        }

        progress.fill.style.width = `${clampedPercent}%`;
        progress.percent.textContent = `${Math.round(clampedPercent)}%`;
    }

    /**
     * Удаляет прогресс-бар
     */
    removeProgressBar(progressId) {
        const progress = this.progressBars.get(progressId);
        if (progress) {
            progress.element.remove();
            this.progressBars.delete(progressId);
        }
    }

    /**
     * Показывает индикатор загрузки на кнопке
     */
    setButtonLoading(buttonId, loading = true, originalText = null) {
        const button = typeof buttonId === 'string' ? document.getElementById(buttonId) : buttonId;
        if (!button) return;

        if (loading) {
            button.dataset.originalText = originalText || button.textContent;
            button.disabled = true;
            button.innerHTML = `
                <span class="button-spinner" style="
                    display: inline-block;
                    width: 16px;
                    height: 16px;
                    border: 2px solid rgba(255,255,255,0.3);
                    border-top-color: #fff;
                    border-radius: 50%;
                    animation: spin 0.6s linear infinite;
                    margin-right: 0.5rem;
                    vertical-align: middle;
                "></span>
                ${button.dataset.originalText}
            `;
        } else {
            button.disabled = false;
            button.textContent = button.dataset.originalText || originalText || 'Отправить';
        }
    }
}

// Добавляем CSS для spinner
if (!document.getElementById('loading-styles')) {
    const style = document.createElement('style');
    style.id = 'loading-styles';
    style.textContent = `
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        .spinner-wrapper {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .spinner {
            width: 50px;
            height: 50px;
            border: 4px solid rgba(118, 75, 162, 0.3);
            border-top-color: #64ffda;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        .loading {
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 2rem;
        }
        .loading .spinner {
            width: 40px;
            height: 40px;
            border: 3px solid rgba(118, 75, 162, 0.3);
            border-top-color: #64ffda;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 1rem;
        }
    `;
    document.head.appendChild(style);
}

// Создаем глобальный экземпляр
window.loading = new LoadingManager();
