/**
 * Toast-уведомления для пользователя
 */

class ToastManager {
    constructor() {
        this.container = null;
        this.init();
    }

    init() {
        // Создаем контейнер для toast-уведомлений
        this.container = document.createElement('div');
        this.container.id = 'toast-container';
        this.container.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 10000;
            display: flex;
            flex-direction: column;
            gap: 10px;
            pointer-events: none;
        `;
        document.body.appendChild(this.container);
    }

    show(message, type = 'info', duration = 3000) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.style.cssText = `
            background: rgba(10, 14, 39, 0.95);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(118, 75, 162, 0.4);
            border-radius: 8px;
            padding: 1rem 1.5rem;
            color: #e0e6ed;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            min-width: 300px;
            max-width: 400px;
            pointer-events: auto;
            animation: slideInRight 0.3s ease-out;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        `;

        const icons = {
            success: '✅',
            error: '❌',
            warning: '⚠️',
            info: 'ℹ️'
        };

        const colors = {
            success: '#64ffda',
            error: '#ff6b6b',
            warning: '#ffc107',
            info: '#64b5f6'
        };

        toast.innerHTML = `
            <span style="font-size: 1.2rem;">${icons[type] || icons.info}</span>
            <span style="flex: 1; line-height: 1.5;">${message}</span>
            <button onclick="this.parentElement.remove()" style="
                background: none;
                border: none;
                color: #b8c5d6;
                cursor: pointer;
                font-size: 1.2rem;
                padding: 0;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
            ">×</button>
        `;

        toast.style.borderLeft = `4px solid ${colors[type] || colors.info}`;

        this.container.appendChild(toast);

        // Автоматическое удаление
        if (duration > 0) {
            setTimeout(() => {
                toast.style.animation = 'slideOutRight 0.3s ease-in';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }

        return toast;
    }

    success(message, duration = 3000) {
        return this.show(message, 'success', duration);
    }

    error(message, duration = 5000) {
        return this.show(message, 'error', duration);
    }

    warning(message, duration = 4000) {
        return this.show(message, 'warning', duration);
    }

    info(message, duration = 3000) {
        return this.show(message, 'info', duration);
    }
}

// Добавляем CSS анимации
if (!document.getElementById('toast-styles')) {
    const style = document.createElement('style');
    style.id = 'toast-styles';
    style.textContent = `
        @keyframes slideInRight {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
        @keyframes slideOutRight {
            from {
                transform: translateX(0);
                opacity: 1;
            }
            to {
                transform: translateX(100%);
                opacity: 0;
            }
        }
    `;
    document.head.appendChild(style);
}

// Создаем глобальный экземпляр
window.toast = new ToastManager();

