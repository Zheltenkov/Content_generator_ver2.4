/**
 * Модальные окна для подтверждений действий
 */

class ModalManager {
    constructor() {
        this.overlay = null;
        this.init();
    }

    init() {
        // Создаем overlay для модальных окон
        this.overlay = document.createElement('div');
        this.overlay.id = 'modal-overlay';
        this.overlay.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0, 0, 0, 0.7);
            backdrop-filter: blur(4px);
            z-index: 9999;
            display: none;
            align-items: center;
            justify-content: center;
            animation: fadeIn 0.2s ease-out;
        `;
        document.body.appendChild(this.overlay);

        // Добавляем CSS анимации
        if (!document.getElementById('modal-styles')) {
            const style = document.createElement('style');
            style.id = 'modal-styles';
            style.textContent = `
                @keyframes fadeIn {
                    from { opacity: 0; }
                    to { opacity: 1; }
                }
                @keyframes slideUp {
                    from {
                        transform: translateY(20px);
                        opacity: 0;
                    }
                    to {
                        transform: translateY(0);
                        opacity: 1;
                    }
                }
                .modal-content {
                    animation: slideUp 0.3s ease-out;
                }
            `;
            document.head.appendChild(style);
        }
    }

    confirm(title, message, confirmText = 'Подтвердить', cancelText = 'Отмена') {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal-content';
            modal.style.cssText = `
                background: rgba(10, 14, 39, 0.95);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(118, 75, 162, 0.4);
                border-radius: 12px;
                padding: 2rem;
                max-width: 500px;
                width: 90%;
                box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            `;

            modal.innerHTML = `
                <h3 style="color: #64ffda; margin-bottom: 1rem; font-size: 1.5rem;">${title}</h3>
                <p style="color: #b8c5d6; margin-bottom: 2rem; line-height: 1.6;">${message}</p>
                <div style="display: flex; gap: 1rem; justify-content: flex-end;">
                    <button class="btn btn-secondary" data-action="cancel" style="width: auto; padding: 0.75rem 1.5rem;">
                        ${cancelText}
                    </button>
                    <button class="btn btn-danger" data-action="confirm" style="width: auto; padding: 0.75rem 1.5rem;">
                        ${confirmText}
                    </button>
                </div>
            `;

            const handleClick = (e) => {
                const action = e.target.getAttribute('data-action');
                if (action === 'confirm') {
                    this.close();
                    resolve(true);
                } else if (action === 'cancel') {
                    this.close();
                    resolve(false);
                }
            };

            modal.addEventListener('click', handleClick);
            this.overlay.addEventListener('click', (e) => {
                if (e.target === this.overlay) {
                    this.close();
                    resolve(false);
                }
            });

            this.overlay.appendChild(modal);
            this.overlay.style.display = 'flex';

            // Закрытие по Escape
            const handleEscape = (e) => {
                if (e.key === 'Escape') {
                    this.close();
                    resolve(false);
                    document.removeEventListener('keydown', handleEscape);
                }
            };
            document.addEventListener('keydown', handleEscape);
        });
    }

    close() {
        this.overlay.style.display = 'none';
        this.overlay.innerHTML = '';
    }
}

// Создаем глобальный экземпляр
window.modal = new ModalManager();

