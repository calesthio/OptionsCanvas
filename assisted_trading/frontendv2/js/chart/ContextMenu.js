/**
 * ContextMenu - Right-click context menu for quick trading actions
 * TradingView-style context menu for placing orders directly from chart
 * @version 1.0 - Quick order placement
 */

class ContextMenu {
    constructor(chartManager, tradingPanel) {
        this.chartManager = chartManager;
        this.tradingPanel = tradingPanel;
        this.menu = null;
        this.clickPrice = null;
        this.enabled = false;

        // Event handlers
        this.onContextMenu = this.handleContextMenu.bind(this);
        this.onDocumentClick = this.handleDocumentClick.bind(this);

        console.log('ContextMenu initialized');
    }

    /**
     * Enable context menu
     */
    enable() {
        if (this.enabled) return;

        const container = this.chartManager.container;
        if (!container) {
            console.error('Chart container not found');
            return;
        }

        container.addEventListener('contextmenu', this.onContextMenu);
        document.addEventListener('click', this.onDocumentClick);

        this.enabled = true;
        console.log('Context menu enabled');
    }

    /**
     * Disable context menu
     */
    disable() {
        if (!this.enabled) return;

        const container = this.chartManager.container;
        if (container) {
            container.removeEventListener('contextmenu', this.onContextMenu);
        }
        document.removeEventListener('click', this.onDocumentClick);

        this.hideMenu();
        this.enabled = false;
        console.log('Context menu disabled');
    }

    /**
     * Handle right-click
     */
    handleContextMenu(event) {
        event.preventDefault();

        // Get price at click location
        const price = this.getPriceFromEvent(event);
        if (price === null) return;

        this.clickPrice = price;

        // Show menu
        this.showMenu(event.clientX, event.clientY);
    }

    /**
     * Handle document click (to hide menu)
     */
    handleDocumentClick(event) {
        if (this.menu && !this.menu.contains(event.target)) {
            this.hideMenu();
        }
    }

    /**
     * Get price from mouse event
     */
    getPriceFromEvent(event) {
        const rect = this.chartManager.container.getBoundingClientRect();
        const y = event.clientY - rect.top;

        const series = this.chartManager.getSeries();
        if (!series) return null;

        try {
            return series.coordinateToPrice(y);
        } catch (error) {
            console.error('Error converting coordinate to price:', error);
            return null;
        }
    }

    /**
     * Show context menu
     */
    showMenu(x, y) {
        // Hide existing menu
        this.hideMenu();

        // Create menu element
        this.menu = document.createElement('div');
        this.menu.className = 'chart-context-menu';
        this.menu.style.cssText = `
            position: fixed;
            left: ${x}px;
            top: ${y}px;
            background: var(--primary-bg);
            border: 1px solid var(--border);
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 10000;
            min-width: 200px;
            padding: 4px 0;
            font-size: 13px;
        `;

        // Get current symbol
        const currentSymbol = this.chartManager.getCurrentSymbol() || 'SPY';

        // Menu header
        const header = document.createElement('div');
        header.style.cssText = `
            padding: 8px 12px;
            font-weight: bold;
            border-bottom: 1px solid var(--border);
            color: var(--text-secondary);
            font-size: 11px;
        `;
        header.textContent = `${currentSymbol} @ $${this.clickPrice.toFixed(2)}`;
        this.menu.appendChild(header);

        // Menu items
        const items = [
            { label: '📈 Buy CALL at this price', action: () => this.quickOrder('CALL') },
            { label: '📉 Buy PUT at this price', action: () => this.quickOrder('PUT') },
            { divider: true },
            { label: '🎯 Set as Entry Price', action: () => this.setAsEntry() },
            { label: '🛑 Set as Stop Loss', action: () => this.setAsStopLoss() },
            { label: '✅ Set as Take Profit', action: () => this.setAsTakeProfit() },
            { divider: true },
            { label: '📍 Draw Horizontal Line', action: () => this.drawHorizontalLine() },
            { label: '🔔 Set Price Alert', action: () => this.setPriceAlert(), disabled: true },
        ];

        items.forEach(item => {
            if (item.divider) {
                const divider = document.createElement('div');
                divider.style.cssText = `
                    height: 1px;
                    background: var(--border);
                    margin: 4px 0;
                `;
                this.menu.appendChild(divider);
            } else {
                const menuItem = document.createElement('div');
                menuItem.className = 'context-menu-item';
                menuItem.style.cssText = `
                    padding: 8px 12px;
                    cursor: ${item.disabled ? 'not-allowed' : 'pointer'};
                    color: ${item.disabled ? 'var(--text-disabled)' : 'var(--text-primary)'};
                    transition: background 0.15s;
                `;
                menuItem.textContent = item.label;

                if (!item.disabled) {
                    menuItem.addEventListener('mouseenter', () => {
                        menuItem.style.background = 'var(--secondary-bg)';
                    });
                    menuItem.addEventListener('mouseleave', () => {
                        menuItem.style.background = 'transparent';
                    });
                    menuItem.addEventListener('click', () => {
                        item.action();
                        this.hideMenu();
                    });
                }

                this.menu.appendChild(menuItem);
            }
        });

        document.body.appendChild(this.menu);

        // Adjust position if menu goes off-screen
        const menuRect = this.menu.getBoundingClientRect();
        if (menuRect.right > window.innerWidth) {
            this.menu.style.left = (x - menuRect.width) + 'px';
        }
        if (menuRect.bottom > window.innerHeight) {
            this.menu.style.top = (y - menuRect.height) + 'px';
        }
    }

    /**
     * Hide context menu
     */
    hideMenu() {
        if (this.menu && this.menu.parentNode) {
            this.menu.parentNode.removeChild(this.menu);
            this.menu = null;
        }
    }

    /**
     * Quick order at clicked price (for limit orders in future)
     */
    quickOrder(contractType) {
        if (!this.tradingPanel) return;

        // Set contract type
        this.tradingPanel.setContractType(contractType);

        // For now, just execute market order
        // TODO: Implement limit order at clickPrice
        this.tradingPanel.executeOrder();

        if (window.Toast) {
            window.Toast.info(`Placing ${contractType} order`, 2000);
        }
    }

    /**
     * Set as entry price (visual indicator)
     */
    setAsEntry() {
        // TODO: Implement bracket order with this as entry
        if (window.Toast) {
            window.Toast.info(`Entry price set to $${this.clickPrice.toFixed(2)}`, 2000);
        }

        // Could integrate with BracketOrderDrawer here
        if (window.BracketOrderDrawer) {
            window.BracketOrderDrawer.enable();
        }
    }

    /**
     * Set as stop loss
     */
    setAsStopLoss() {
        const slInput = document.getElementById('stopLoss');
        if (slInput) {
            slInput.value = this.clickPrice.toFixed(2);
            if (window.Toast) {
                window.Toast.success(`Stop Loss set to $${this.clickPrice.toFixed(2)}`, 2000);
            }
        }
    }

    /**
     * Set as take profit
     */
    setAsTakeProfit() {
        const tpInput = document.getElementById('takeProfit');
        if (tpInput) {
            tpInput.value = this.clickPrice.toFixed(2);
            if (window.Toast) {
                window.Toast.success(`Take Profit set to $${this.clickPrice.toFixed(2)}`, 2000);
            }
        }
    }

    /**
     * Draw horizontal line at price
     */
    drawHorizontalLine() {
        if (window.DrawingManager) {
            const series = this.chartManager.getSeries();
            if (series) {
                // Create horizontal line directly
                const priceLine = series.createPriceLine({
                    price: this.clickPrice,
                    color: '#3861fb',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: true,
                    title: `$${this.clickPrice.toFixed(2)}`,
                });

                if (window.Toast) {
                    window.Toast.info(`Horizontal line drawn at $${this.clickPrice.toFixed(2)}`, 2000);
                }
            }
        }
    }

    /**
     * Set price alert (placeholder for future implementation)
     */
    setPriceAlert() {
        if (window.Toast) {
            window.Toast.info('Price alerts coming soon!', 2000);
        }
    }
}

// Make globally available
window.ContextMenu = ContextMenu;
