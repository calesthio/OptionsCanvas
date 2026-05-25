/**
 * Toast - Non-blocking notification system
 * Replaces browser alert() with elegant, non-blocking toasts
 */

class Toast {
    constructor() {
        this.container = null;
        this.toasts = new Map();
        this.idCounter = 0;
        this.initialize();
    }

    /**
     * Initialize toast container
     */
    initialize() {
        // Create container if it doesn't exist
        this.container = document.getElementById('toastContainer');
        if (!this.container) {
            this.container = document.createElement('div');
            this.container.id = 'toastContainer';
            this.container.className = 'toast-container';
            document.body.appendChild(this.container);
        }
    }

    /**
     * Show a toast notification
     * @param {string} message - Message to display
     * @param {string} type - Type: 'success', 'error', 'warning', 'info'
     * @param {number} duration - Duration in ms (0 = persist until dismissed)
     * @returns {number} Toast ID
     */
    show(message, type = 'info', duration = 3000) {
        const id = this.idCounter++;

        // Create toast element
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.dataset.id = id;

        // Icon based on type
        const icons = {
            success: '✓',
            error: '✕',
            warning: '⚠',
            info: 'ℹ'
        };

        toast.innerHTML = `
            <div class="toast-icon">${icons[type] || icons.info}</div>
            <div class="toast-message">${message}</div>
            <button class="toast-close" onclick="window.Toast.dismiss(${id})">×</button>
        `;

        // Add to container
        this.container.appendChild(toast);
        this.toasts.set(id, toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('toast-show');
        });

        // Auto-dismiss after duration
        if (duration > 0) {
            setTimeout(() => {
                this.dismiss(id);
            }, duration);
        }

        return id;
    }

    /**
     * Show success toast
     * @param {string} message - Message
     * @param {number} duration - Duration in ms
     */
    success(message, duration = 3000) {
        return this.show(message, 'success', duration);
    }

    /**
     * Show error toast
     * @param {string} message - Message
     * @param {number} duration - Duration in ms
     */
    error(message, duration = 5000) {
        return this.show(message, 'error', duration);
    }

    /**
     * Show warning toast
     * @param {string} message - Message
     * @param {number} duration - Duration in ms
     */
    warning(message, duration = 4000) {
        return this.show(message, 'warning', duration);
    }

    /**
     * Show info toast
     * @param {string} message - Message
     * @param {number} duration - Duration in ms
     */
    info(message, duration = 3000) {
        return this.show(message, 'info', duration);
    }

    /**
     * Dismiss a toast
     * @param {number} id - Toast ID
     */
    dismiss(id) {
        const toast = this.toasts.get(id);
        if (!toast) return;

        // Trigger exit animation
        toast.classList.remove('toast-show');
        toast.classList.add('toast-hide');

        // Remove after animation completes
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
            this.toasts.delete(id);
        }, 300);
    }

    /**
     * Dismiss all toasts
     */
    dismissAll() {
        this.toasts.forEach((toast, id) => {
            this.dismiss(id);
        });
    }

    /**
     * Show confirmation dialog (non-blocking)
     * @param {string} message - Message
     * @param {Function} onConfirm - Callback on confirm
     * @param {Function} onCancel - Callback on cancel (optional)
     */
    confirm(message, onConfirm, onCancel = null) {
        const id = this.idCounter++;

        // Create confirmation toast
        const toast = document.createElement('div');
        toast.className = 'toast toast-confirm';
        toast.dataset.id = id;

        toast.innerHTML = `
            <div class="toast-icon">?</div>
            <div class="toast-message">${message}</div>
            <div class="toast-actions">
                <button class="toast-btn toast-btn-confirm" data-action="confirm">Confirm</button>
                <button class="toast-btn toast-btn-cancel" data-action="cancel">Cancel</button>
            </div>
        `;

        // Add event listeners
        toast.querySelector('[data-action="confirm"]').addEventListener('click', () => {
            this.dismiss(id);
            if (onConfirm) onConfirm();
        });

        toast.querySelector('[data-action="cancel"]').addEventListener('click', () => {
            this.dismiss(id);
            if (onCancel) onCancel();
        });

        // Add to container
        this.container.appendChild(toast);
        this.toasts.set(id, toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.classList.add('toast-show');
        });

        return id;
    }
}

// Create global instance
window.Toast = new Toast();
