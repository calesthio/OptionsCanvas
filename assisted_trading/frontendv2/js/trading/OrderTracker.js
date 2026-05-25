/**
 * OrderTracker - Manages display and updates of queued orders
 * Handles order cards and on-chart limit lines for equity-triggered orders
 */

class OrderTracker {
    constructor() {
        this.orders = new Map();
        this.pollingInterval = null;

        this.initializeElements();
        this.attachEventListeners();
        this.startPolling();
    }

    initializeElements() {
        this.ordersList = document.getElementById('ordersList');
        this.ordersPanel = document.getElementById('ordersPanel');
        this.collapseBtn = document.getElementById('orderCollapseBtn');
    }

    attachEventListeners() {
        const toggleCollapse = (e) => {
            this.ordersPanel?.classList.toggle('collapsed');
            const isCollapsed = this.ordersPanel?.classList.contains('collapsed');
            if (this.collapseBtn) this.collapseBtn.textContent = isCollapsed ? '+' : '−';
            e?.stopPropagation();
        };
        this.collapseBtn?.addEventListener('click', toggleCollapse);

        // When collapsed, the whole header strip is clickable to re-expand
        // (forgiving target on a narrow vertical strip).
        this.ordersPanel?.addEventListener('click', (e) => {
            if (!this.ordersPanel.classList.contains('collapsed')) return;
            if (e.target.closest('.collapse-btn')) return;
            if (e.target.closest('.positions-header')) toggleCollapse(e);
        });

        // Listen for new orders placed
        window.EventBus?.on('order:placed', () => {
            this.refreshOrders();
        });
    }

    startPolling() {
        this.pollingInterval = setInterval(() => this.refreshOrders(), 3000);
        this.refreshOrders(); // Initial fetch
    }

    async refreshOrders() {
        try {
            const response = await window.ApiClient.getOrders();
            if (response && response.orders) {
                this.updateOrders(response.orders);
                this.syncWithChart(response.orders);
            }
        } catch (error) {
            console.error('OrderTracker: Error refreshing orders:', error);
        }
    }

    updateOrders(ordersData) {
        if (!this.ordersList) return;

        // Clear if empty
        if (ordersData.length === 0) {
            this.ordersList.innerHTML = '<div class="empty-positions">No queued orders</div>';
            this.orders.clear();
            return;
        }

        // Build list
        this.ordersList.innerHTML = '';
        ordersData.forEach(order => {
            this.orders.set(order.order_id, order);
            const card = this.createOrderCard(order);
            this.ordersList.appendChild(card);
        });
    }

    createOrderCard(order) {
        const card = document.createElement('div');
        card.className = 'position-card order-card';
        card.dataset.orderId = order.order_id;

        const isLimit = order.order_type === 'equity_limit';
        const statusClass = order.status.replace(/_/g, '-');

        // Calculate estimated expiry date from DTE
        const estimatedExpiry = this.calculateExpiryFromDTE(order.dte);
        const optionOrderType = order.option_order_type || 'limit';
        const executionDisplay = {
            'limit': 'Limit @ Midpoint',
            'market': 'Market'
        }[optionOrderType] || 'Limit @ Midpoint';

        card.innerHTML = `
            <div class="position-header">
                <div class="position-title">
                    <span class="position-type ${order.contract_type.toLowerCase()}">${order.contract_type}</span>
                    <span class="position-symbol">${order.symbol}</span>
                </div>
                <div class="position-pnl">
                    <span class="order-status-badge ${statusClass}">${order.status.replace(/_/g, ' ')}</span>
                </div>
            </div>
            <div class="position-details">
                <div class="detail-item">
                    <span class="detail-label">Position Size</span>
                    <span class="detail-value">$${order.position_size}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">DTE</span>
                    <span class="detail-value">${order.dte}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Est. Expiry</span>
                    <span class="detail-value">${estimatedExpiry}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Execution</span>
                    <span class="detail-value">${executionDisplay}</span>
                </div>
                <div class="detail-item">
                    <span class="detail-label">Trigger</span>
                    <span class="detail-value">${order.order_type === 'equity_limit' ? 'Wait for Price' : 'Immediate'}</span>
                </div>
                ${isLimit ? `
                <div class="detail-item">
                    <span class="detail-label">Trigger Price</span>
                    <span class="detail-value">$${order.equity_limit_price.toFixed(2)}</span>
                </div>
                ` : ''}
            </div>
            <div class="position-actions" style="margin-top: 10px;">
                <button class="action-btn sell" onclick="event.stopPropagation(); window.OrderTracker.cancelOrder('${order.order_id}')">
                    Cancel Order
                </button>
            </div>
        `;

        // Click to navigate to order's symbol
        card.addEventListener('click', (e) => {
            // Don't navigate if clicking action buttons
            if (e.target.closest('.action-btn')) {
                return;
            }
            this.navigateToOrderSymbol(order.symbol);
        });

        return card;
    }

    /**
     * Navigate chart to the order's symbol
     * @param {string} symbol - Underlying symbol
     */
    navigateToOrderSymbol(symbol) {
        if (!symbol || symbol === window.App?.currentSymbol) {
            return; // Already on this symbol
        }

        const symbolSelect = document.getElementById('symbolSelect');
        if (!symbolSelect) {
            console.error('Symbol dropdown not found');
            return;
        }

        // Check if symbol exists in dropdown
        const option = Array.from(symbolSelect.options).find(opt => opt.value === symbol);
        if (!option) {
            console.warn(`Symbol ${symbol} not found in dropdown`);
            return;
        }

        // Update dropdown and trigger change
        symbolSelect.value = symbol;
        symbolSelect.dispatchEvent(new Event('change', { bubbles: true }));

        console.log(`OrderTracker: Switched chart to ${symbol}`);
    }

    /**
     * Calculate estimated expiry date from DTE
     * @param {number} dte - Days to expiration
     * @returns {string} Formatted date
     */
    calculateExpiryFromDTE(dte) {
        try {
            const today = new Date();
            const expiryDate = new Date(today);
            expiryDate.setDate(today.getDate() + parseInt(dte));

            const month = String(expiryDate.getMonth() + 1).padStart(2, '0');
            const day = String(expiryDate.getDate()).padStart(2, '0');
            const year = expiryDate.getFullYear();

            return `${month}/${day}/${year}`;
        } catch (error) {
            return 'N/A';
        }
    }

    async cancelOrder(orderId) {
        try {
            if (!confirm('Are you sure you want to cancel this queued order?')) return;

            const result = await window.ApiClient.cancelPendingOrder(orderId);

            if (result.success) {
                // Success - show confirmation
                window.Toast?.success(result.message || 'Order canceled');
                this.refreshOrders();
            } else {
                // Failed - show user-friendly error message
                const message = result.message || 'Could not cancel order';
                const hint = result.hint;

                // Show error with longer duration for important messages
                if (message.includes('filled')) {
                    // Use warning for "already filled" - it's informational, not an error
                    window.Toast?.warning(message, 6000);
                } else if (message.includes('already canceled')) {
                    // Just info if already canceled
                    window.Toast?.info(message, 4000);
                } else {
                    // Other errors
                    window.Toast?.error(message, 5000);
                }

                // Show hint as separate info toast if provided
                if (hint) {
                    setTimeout(() => {
                        window.Toast?.info(hint, 4000);
                    }, 500);
                }

                // Refresh to show current state
                this.refreshOrders();
            }
        } catch (error) {
            // Network or unexpected error
            console.error('Error canceling order:', error);
            window.Toast?.error('Connection error. Please check your internet and try again.', 5000);
        }
    }

    syncWithChart(orders) {
        if (!window.PriceLineManager) return;

        // Current symbol filter
        const currentSymbol = window.App?.currentSymbol;

        // Track order IDs currently being shown on chart
        const activePendingOrderIds = new Set();

        // We want to show lines for equity limit orders
        orders.forEach(order => {
            if (order.symbol === currentSymbol && order.order_type === 'equity_limit' && order.status === 'monitoring_equity') {
                const lineId = `pending_${order.order_id}`;
                activePendingOrderIds.add(lineId);

                if (window.PriceLineManager.addPendingOrderLine) {
                    window.PriceLineManager.addPendingOrderLine(order);
                }
            }
        });

        // Cleanup lines for orders no longer in pending list for THIS symbol
        // PriceLineManager.priceLines is a Map
        window.PriceLineManager.priceLines.forEach((lineData, lineId) => {
            if (lineData.type === 'pending_order' && lineData.symbol === currentSymbol) {
                if (!activePendingOrderIds.has(lineId)) {
                    window.PriceLineManager.removeLine(lineId);
                }
            }
        });
    }
}

// Global instance
window.OrderTracker = null;
