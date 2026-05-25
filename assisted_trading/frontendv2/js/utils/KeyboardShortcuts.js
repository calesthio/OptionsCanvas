/**
 * KeyboardShortcutManager - TradingView-style keyboard shortcuts
 * Provides hotkeys for common trading actions
 * @version 1.0 - Professional trading shortcuts
 */

class KeyboardShortcutManager {
    constructor() {
        this.enabled = false;
        this.shortcuts = new Map();

        // Bind handler
        this.handleKeyDown = this.onKeyDown.bind(this);

        // Register default shortcuts
        this.registerDefaultShortcuts();

        console.log('KeyboardShortcutManager initialized');
    }

    /**
     * Register default trading shortcuts
     */
    registerDefaultShortcuts() {
        // Order placement
        this.register('b', () => {
            // Buy CALL at market
            if (window.TradingPanel) {
                window.TradingPanel.setContractType('CALL');
                window.TradingPanel.executeOrder();
            }
        }, 'Buy CALL at market');

        this.register('s', () => {
            // Buy PUT (Sell/Short equivalent)
            if (window.TradingPanel) {
                window.TradingPanel.setContractType('PUT');
                window.TradingPanel.executeOrder();
            }
        }, 'Buy PUT at market');

        this.register('f', () => {
            // Flatten all positions
            if (window.TradingPanel) {
                window.TradingPanel.closeAllPositions();
            }
        }, 'Close all positions');

        // Drawing tools
        this.register('d', () => {
            // Draw horizontal line
            if (window.DrawingManager) {
                window.DrawingManager.setTool('hline');
            }
        }, 'Draw horizontal line');

        this.register('t', () => {
            // Draw trend line
            if (window.DrawingManager) {
                window.DrawingManager.setTool('trendline');
            }
        }, 'Draw trend line');

        this.register('Escape', () => {
            // Reset to crosshair
            if (window.DrawingManager) {
                window.DrawingManager.setTool(null);
            }
            if (window.BracketOrderDrawer && window.BracketOrderDrawer.enabled) {
                window.BracketOrderDrawer.disable();
            }
        }, 'Cancel drawing/Reset to crosshair');

        // Bracket order mode
        this.register('shift+b', () => {
            // Toggle bracket order drawing mode
            if (window.BracketOrderDrawer) {
                if (window.BracketOrderDrawer.enabled) {
                    window.BracketOrderDrawer.disable();
                } else {
                    window.BracketOrderDrawer.enable();
                }
            }
        }, 'Toggle bracket order mode');

        // Position size presets (1-5 keys)
        const sizePresets = [500, 1000, 2000, 5000, 10000];
        for (let i = 0; i < sizePresets.length; i++) {
            this.register(`${i + 1}`, () => {
                const sizeInput = document.getElementById('positionSize');
                if (sizeInput) {
                    sizeInput.value = sizePresets[i];
                    // Trigger input event to update preview
                    sizeInput.dispatchEvent(new Event('input', { bubbles: true }));

                    if (window.Toast) {
                        window.Toast.info(`Position size: $${sizePresets[i]}`, 1500);
                    }
                }
            }, `Set position size: $${sizePresets[i]}`);
        }

        // Contract type toggle
        this.register('c', () => {
            // Toggle between CALL and PUT
            if (window.TradingPanel) {
                const currentType = window.TradingPanel.contractType;
                window.TradingPanel.setContractType(currentType === 'CALL' ? 'PUT' : 'CALL');

                if (window.Toast) {
                    window.Toast.info(`Switched to ${currentType === 'CALL' ? 'PUT' : 'CALL'}`, 1500);
                }
            }
        }, 'Toggle CALL/PUT');

        // Strike adjustment
        this.register('ArrowUp', () => {
            // Increase strike
            if (window.TradingPanel) {
                window.TradingPanel.adjustStrike(1);
            }
        }, 'Increase strike');

        this.register('ArrowDown', () => {
            // Decrease strike
            if (window.TradingPanel) {
                window.TradingPanel.adjustStrike(-1);
            }
        }, 'Decrease strike');

        // Symbol navigation
        this.register('alt+ArrowLeft', () => {
            // Previous symbol
            this.changeSymbol(-1);
        }, 'Previous symbol');

        this.register('alt+ArrowRight', () => {
            // Next symbol
            this.changeSymbol(1);
        }, 'Next symbol');

        // Timeframe shortcuts
        this.register('alt+1', () => this.setTimeframe('1Min'), 'Set 1min timeframe');
        this.register('alt+2', () => this.setTimeframe('5Min'), 'Set 5min timeframe');
        this.register('alt+3', () => this.setTimeframe('15Min'), 'Set 15min timeframe');
        this.register('alt+4', () => this.setTimeframe('30Min'), 'Set 30min timeframe');
        this.register('alt+5', () => this.setTimeframe('1Hour'), 'Set 1hour timeframe');
        this.register('alt+6', () => this.setTimeframe('1Day'), 'Set 1day timeframe');

        // Help
        this.register('?', () => {
            this.showShortcutsHelp();
        }, 'Show keyboard shortcuts help');

        console.log(`Registered ${this.shortcuts.size} keyboard shortcuts`);
    }

    /**
     * Register a keyboard shortcut
     */
    register(key, callback, description = '') {
        this.shortcuts.set(key.toLowerCase(), {
            callback,
            description
        });
    }

    /**
     * Enable keyboard shortcuts
     */
    enable() {
        if (this.enabled) return;

        document.addEventListener('keydown', this.handleKeyDown);
        this.enabled = true;
        console.log('Keyboard shortcuts enabled');
    }

    /**
     * Disable keyboard shortcuts
     */
    disable() {
        if (!this.enabled) return;

        document.removeEventListener('keydown', this.handleKeyDown);
        this.enabled = false;
        console.log('Keyboard shortcuts disabled');
    }

    /**
     * Handle keydown event
     */
    onKeyDown(event) {
        // Ignore if user is typing in an input field
        const target = event.target;
        if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable) {
            return;
        }

        // Build key combination string
        let key = event.key.toLowerCase();

        // Add modifiers
        const modifiers = [];
        if (event.ctrlKey) modifiers.push('ctrl');
        if (event.altKey) modifiers.push('alt');
        if (event.shiftKey) modifiers.push('shift');
        if (event.metaKey) modifiers.push('meta');

        const fullKey = modifiers.length > 0 ? `${modifiers.join('+')}+${key}` : key;

        // Check if shortcut exists
        const shortcut = this.shortcuts.get(fullKey);

        if (shortcut) {
            event.preventDefault();
            try {
                shortcut.callback(event);
            } catch (error) {
                console.error(`Error executing shortcut "${fullKey}":`, error);
            }
        }
    }

    /**
     * Change symbol (navigate symbol list)
     */
    changeSymbol(direction) {
        const symbolSelect = document.getElementById('symbolSelect');
        if (!symbolSelect) return;

        const currentIndex = symbolSelect.selectedIndex;
        const newIndex = currentIndex + direction;

        if (newIndex >= 0 && newIndex < symbolSelect.options.length) {
            symbolSelect.selectedIndex = newIndex;
            symbolSelect.dispatchEvent(new Event('change', { bubbles: true }));

            if (window.Toast) {
                window.Toast.info(`Symbol: ${symbolSelect.value}`, 1500);
            }
        }
    }

    /**
     * Set timeframe
     */
    setTimeframe(timeframe) {
        const tfButton = document.querySelector(`[data-tf="${timeframe}"]`);
        if (tfButton) {
            tfButton.click();

            if (window.Toast) {
                window.Toast.info(`Timeframe: ${timeframe}`, 1500);
            }
        }
    }

    /**
     * Show shortcuts help modal
     */
    showShortcutsHelp() {
        const shortcuts = Array.from(this.shortcuts.entries())
            .map(([key, data]) => `<tr><td style="font-family: monospace; padding: 4px 12px; background: var(--secondary-bg);">${key}</td><td style="padding: 4px 12px;">${data.description}</td></tr>`)
            .join('');

        const helpHtml = `
            <div style="max-width: 600px; max-height: 70vh; overflow-y: auto;">
                <h2 style="margin-bottom: 16px;">⌨️ Keyboard Shortcuts</h2>
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 1px solid var(--border);">
                            <th style="text-align: left; padding: 8px 12px;">Key</th>
                            <th style="text-align: left; padding: 8px 12px;">Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${shortcuts}
                    </tbody>
                </table>
            </div>
        `;

        // Show in a simple modal (you can enhance this with a proper modal component)
        const modal = document.createElement('div');
        modal.style.cssText = `
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10000;
            padding: 20px;
        `;

        const content = document.createElement('div');
        content.style.cssText = `
            background: var(--primary-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 24px;
            color: var(--text-primary);
        `;
        content.innerHTML = helpHtml;

        modal.appendChild(content);
        document.body.appendChild(modal);

        // Close on click outside or ESC
        const closeModal = () => {
            if (modal.parentNode) {
                modal.parentNode.removeChild(modal);
            }
        };

        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        const escapeHandler = (e) => {
            if (e.key === 'Escape') {
                closeModal();
                document.removeEventListener('keydown', escapeHandler);
            }
        };

        document.addEventListener('keydown', escapeHandler);
    }

    /**
     * Get all registered shortcuts
     */
    getAllShortcuts() {
        return Array.from(this.shortcuts.entries()).map(([key, data]) => ({
            key,
            description: data.description
        }));
    }
}

// Make globally available
window.KeyboardShortcutManager = KeyboardShortcutManager;
