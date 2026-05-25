/**
 * PositionTracker - Manages position display and updates
 * Handles position cards, real-time P&L updates, and position actions
 */

class PositionTracker {
    constructor() {
        this.positions = new Map();
        this.updateInterval = null;
        this.isCollapsed = false;
        this.chartReady = false;

        this.initializeElements();
        this.attachEventListeners();
        // Listen for drag updates from the chart
        window.EventBus?.on('draghandle:dropped', () => {
            console.log('PositionTracker: Drag confirmed, waiting for backend stabilize...');
            setTimeout(() => {
                this.refreshPositions();
            }, 500);
        });

        // Listen for chart symbol loaded - refresh positions to draw lines
        window.EventBus?.on('chart:symbol_loaded', () => {
            console.log('PositionTracker: Chart symbol loaded, refreshing positions to draw lines');
            this.chartReady = true;
            this.refreshPositions();
        });

        // Delay initial polling until chart is likely ready
        // This prevents race condition where positions sync before chart loads
        setTimeout(() => this.startPolling(), 1000);
    }

    /**
     * Initialize DOM elements
     */
    initializeElements() {
        this.positionsPanel = document.getElementById('positionsPanel');
        this.positionsList = document.getElementById('positionsList');
        this.collapseBtn = document.getElementById('posCollapseBtn');
        this.dayPnLEl = document.getElementById('dayPnL');
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Collapse/expand panel — the small ± button is the canonical control.
        const toggleCollapse = (e) => {
            this.isCollapsed = !this.isCollapsed;
            this.positionsPanel?.classList.toggle('collapsed', this.isCollapsed);
            if (this.collapseBtn) {
                this.collapseBtn.textContent = this.isCollapsed ? '+' : '−';
            }
            e?.stopPropagation();
        };
        this.collapseBtn?.addEventListener('click', toggleCollapse);

        // While collapsed, let the user click anywhere on the header strip
        // (not just the ± button) to re-expand. Without this, the user has to
        // hit a 28px button on a narrow vertical strip — too fiddly. Bind on
        // the panel itself so the listener stays alive across class toggles.
        this.positionsPanel?.addEventListener('click', (e) => {
            if (!this.isCollapsed) return;                         // only when collapsed
            if (e.target.closest('.collapse-btn')) return;         // button has its own handler
            if (e.target.closest('.positions-header')) toggleCollapse(e);
        });

        // Listen for new orders
        window.EventBus.on('order:placed', () => {
            // Refresh positions immediately (WebSocket event should trigger, but force refresh as backup)
            this.refreshPositions();
        });

        // Listen for close all event
        window.EventBus.on('positions:close_all', () => {
            this.closeAllPositions();
        });

        // Listen for position closed events
        window.EventBus.on('position:closed', (data) => {
            console.log('Position closed via WebSocket:', data);
            this.refreshPositions();
        });
    }

    /**
     * Start polling for position updates
     */
    startPolling() {
        // Initial load
        this.refreshPositions();

        // Poll every 2 seconds (reduced from 5 for faster updates)
        this.updateInterval = setInterval(() => {
            this.refreshPositions();
        }, 2000);

        console.log('Position polling started (2-second interval)');
    }

    /**
     * Stop polling
     */
    stopPolling() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
            console.log('Position polling stopped');
        }
    }

    /**
     * Refresh positions from API
     */
    async refreshPositions() {
        try {
            const response = await window.ApiClient.getPositions();

            if (!response || !response.positions) {
                console.warn('No position data received');
                return;
            }

            // 1. Sync with chart (add/remove price lines) - Must happen BEFORE updatePositions
            this.syncWithChart(response.positions);

            // 2. Sync with on-chart position panels - Must happen BEFORE updatePositions
            if (window.PositionPanelOnChart) {
                window.PositionPanelOnChart.syncPositions(response.positions);
            }

            // 3. Update internal state and UI cards
            this.updatePositions(response.positions);

            // 4. Update day P&L
            this.updateDayPnL();

        } catch (error) {
            console.error('Error refreshing positions:', error);
        }
    }

    /**
     * Update positions display
     * @param {Array} positionsData - Array of position objects
     */
    updatePositions(positionsData) {
        if (!this.positionsList) {
            return;
        }

        // Clear existing positions
        this.positionsList.innerHTML = '';
        this.positions.clear(); // CRITICAL: Clear map to prevent stale entries

        if (!positionsData || positionsData.length === 0) {
            this.positionsList.innerHTML = '<div class="empty-positions">No open positions</div>';
            this.positions.clear();
            return;
        }

        // Add position cards
        positionsData.forEach(position => {
            this.positions.set(position.option_symbol, position);
            const card = this.createPositionCard(position);
            this.positionsList.appendChild(card);
        });
    }

    /**
     * Create position card element
     * @param {Object} position - Position data
     * @returns {HTMLElement} Position card
     */
    createPositionCard(position) {
        const card = document.createElement('div');
        card.className = 'position-card';
        card.dataset.symbol = position.option_symbol;

        // Add visual indicator for untracked positions
        if (!position.is_tracked) {
            card.classList.add('untracked');
        }

        // Calculate P&L percentage
        const pnlPercent = position.unrealized_pnl_pct || 0;
        const pnlClass = position.unrealized_pnl >= 0 ? 'positive' : 'negative';
        const isOption = position.asset_type !== 'stock';
        const typeLabel = isOption ? position.contract_type : 'STOCK';
        const typeClass = isOption ? position.contract_type.toLowerCase() : 'stock';
        const formatMoney = (value) => {
            const numeric = Number(value);
            return Number.isFinite(numeric) ? `$${numeric.toFixed(2)}` : 'N/A';
        };

        // Format expiry date
        const expiryDate = isOption && position.option_symbol ?
            this.extractExpiryFromSymbol(position.option_symbol) : 'N/A';
        const detailsHtml = isOption ? `
                <div class="detail-item">
                    <div class="detail-label">Strike</div>
                    <div class="detail-value">${formatMoney(position.strike)}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Expiry</div>
                    <div class="detail-value">${expiryDate}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">DTE</div>
                    <div class="detail-value">${position.dte || 'N/A'}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Contracts</div>
                    <div class="detail-value">${position.remaining_contracts}/${position.total_contracts}</div>
                </div>
        ` : `
                <div class="detail-item">
                    <div class="detail-label">Shares</div>
                    <div class="detail-value">${position.remaining_contracts}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Source</div>
                    <div class="detail-value">Broker</div>
                </div>
        `;
        const levelsHtml = isOption ? `
            <div class="position-levels">
                <div class="level-item entry">
                    <span class="level-dot"></span>
                    <span class="level-label">Entry:</span>
                    <span class="level-value">${formatMoney(position.underlying_entry_price)}</span>
                </div>
                ${position.stop_loss_price ? `
                    <div class="level-item sl">
                        <span class="level-dot"></span>
                        <span class="level-label">SL:</span>
                        <span class="level-value">${formatMoney(position.stop_loss_price)}</span>
                    </div>
                ` : ''}
                ${position.take_profit_price ? `
                    <div class="level-item tp">
                        <span class="level-dot"></span>
                        <span class="level-label">TP:</span>
                        <span class="level-value">${formatMoney(position.take_profit_price)}</span>
                    </div>
                ` : ''}
            </div>
        ` : '';
        const actionsHtml = position.is_tracked ? `
            <div class="position-actions">
                <button class="action-btn" onclick="window.PositionTracker.sellContracts('${position.option_symbol}', 1)">
                    Sell 1
                </button>
                <button class="action-btn sell" onclick="window.PositionTracker.sellContracts('${position.option_symbol}', ${position.remaining_contracts})">
                    Sell All
                </button>
            </div>
        ` : `
            <div class="position-actions">
                <span class="text-muted">External broker position</span>
            </div>
        `;

        card.innerHTML = `
            <div class="position-header">
                <div class="position-title">
                    <span class="position-type ${typeClass}">${typeLabel}</span>
                    <span class="position-symbol">${position.symbol}</span>
                    ${!position.is_tracked ? '<span class="external-badge" title="External position (not opened in this platform)">⚠️</span>' : ''}
                </div>
                <div class="header-right-actions" style="display: flex; align-items: flex-start; gap: 10px;">
                    <div class="position-pnl">
                        <div class="pnl-amount ${pnlClass}">
                            ${position.unrealized_pnl >= 0 ? '+' : ''}$${position.unrealized_pnl.toFixed(2)}
                        </div>
                        <div class="pnl-percent">(${pnlPercent >= 0 ? '+' : ''}${pnlPercent.toFixed(2)}%)</div>
                    </div>
                    ${position.is_tracked ? `<button class="close-position-btn" title="Close Position" onclick="event.stopPropagation(); window.PositionTracker.sellContracts('${position.option_symbol}', ${position.remaining_contracts})">×</button>` : ''}
                </div>
            </div>

            <div class="position-details">
                ${detailsHtml}
                <div class="detail-item">
                    <div class="detail-label">Entry</div>
                    <div class="detail-value">${formatMoney(position.entry_price)}</div>
                </div>
                <div class="detail-item">
                    <div class="detail-label">Current</div>
                    <div class="detail-value">${formatMoney(position.current_price)}</div>
                </div>
            </div>

            ${levelsHtml}
            ${actionsHtml}
        `;

        // Click to highlight on chart AND switch symbol
        card.addEventListener('click', (e) => {
            // Don't navigate if clicking action buttons
            if (e.target.closest('.action-btn') || e.target.closest('.close-position-btn')) {
                return;
            }
            this.highlightPosition(position.option_symbol, position.symbol);
        });

        return card;
    }

    /**
     * Sell contracts for a position
     * @param {string} optionSymbol - Option symbol
     * @param {number} contracts - Number of contracts to sell
     */
    async sellContracts(optionSymbol, contracts) {
        try {
            console.log(`Closing ${contracts} contracts of ${optionSymbol}`);

            const result = await window.ApiClient.closePosition(optionSymbol, contracts);

            if (result.success) {
                console.log('Position closed successfully:', result);
                window.Toast.success(`Closed ${contracts} contract(s) successfully!`, 3000);

                // Refresh positions
                await this.refreshPositions();
            } else {
                console.error('Failed to close position:', result);
                window.Toast.error(`Failed to close position: ${result.error}`, 5000);
            }

        } catch (error) {
            console.error('Error closing position:', error);
            window.Toast.error(`Error: ${error.message}`, 5000);
        }
    }

    /**
     * Close all positions
     */
    async closeAllPositions() {
        const positions = Array.from(this.positions.values());

        if (positions.length === 0) {
            window.Toast.warning('No open positions to close', 3000);
            return;
        }

        console.log(`Closing ${positions.length} position(s)...`);

        // Show progress toast
        const progressToastId = window.Toast.info(`Closing ${positions.length} position(s)...`, 0);

        let successCount = 0;
        let errorCount = 0;

        for (const position of positions) {
            try {
                const result = await window.ApiClient.closePosition(
                    position.option_symbol,
                    position.remaining_contracts
                );

                if (result.success) {
                    successCount++;
                } else {
                    errorCount++;
                }

                // Small delay between orders
                await new Promise(resolve => setTimeout(resolve, 500));

            } catch (error) {
                console.error(`Error closing ${position.option_symbol}:`, error);
                errorCount++;
            }
        }

        // Dismiss progress toast
        window.Toast.dismiss(progressToastId);

        // Show result
        if (errorCount === 0) {
            window.Toast.success(`Successfully closed all ${successCount} position(s)!`, 4000);
        } else {
            window.Toast.warning(`Closed ${successCount} position(s). ${errorCount} failed.`, 5000);
        }

        // Refresh positions
        await this.refreshPositions();
    }

    /**
     * Highlight position on chart and switch to its symbol
     * @param {string} optionSymbol - Option symbol to highlight
     * @param {string} underlyingSymbol - Underlying symbol (SPY, QQQ, etc.)
     */
    highlightPosition(optionSymbol, underlyingSymbol) {
        // Remove previous highlights
        document.querySelectorAll('.position-card.selected').forEach(card => {
            card.classList.remove('selected');
        });

        // Add highlight
        const card = document.querySelector(`[data-symbol="${optionSymbol}"]`);
        if (card) {
            card.classList.add('selected');
        }

        // Switch chart to this symbol if different from current
        if (underlyingSymbol && underlyingSymbol !== window.App?.currentSymbol) {
            this.switchToSymbol(underlyingSymbol);
        }

        console.log(`Highlighted position: ${optionSymbol}`);
    }

    /**
     * Switch chart to a different symbol
     * @param {string} symbol - Symbol to switch to (SPY, QQQ, etc.)
     */
    switchToSymbol(symbol) {
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

        console.log(`Switched chart to ${symbol}`);
    }

    /**
     * Extract expiry date from option symbol
     * @param {string} optionSymbol - OCC format option symbol
     * @returns {string} Formatted expiry date
     */
    extractExpiryFromSymbol(optionSymbol) {
        try {
            // OCC format: SPY260126C00688000
            // Extract date portion (characters after ticker, 6 digits YYMMDD)
            const match = optionSymbol.match(/[A-Z]+(\d{6})[CP]/);
            if (match) {
                const dateStr = match[1]; // e.g., "260126"
                const year = '20' + dateStr.substring(0, 2);
                const month = dateStr.substring(2, 4);
                const day = dateStr.substring(4, 6);
                return `${month}/${day}/${year}`;
            }
            return 'N/A';
        } catch (error) {
            return 'N/A';
        }
    }

    /**
     * Sync positions with chart (add price lines)
     * Uses diff-based approach to avoid flickering
     * @param {Array} positions - Array of position objects
     */
    syncWithChart(positions) {
        if (!window.PriceLineManager) {
            console.warn('PositionTracker: PriceLineManager not available, skipping chart sync');
            return;
        }

        // Wait for chart to be ready before syncing
        if (!this.chartReady && !window.App?.currentSymbol) {
            console.warn('PositionTracker: Chart not ready yet, will sync after chart:symbol_loaded event');
            return;
        }

        // Safety: If no positions, clear all price lines
        if (!positions || positions.length === 0) {
            window.PriceLineManager.clearAll();
            return;
        }

        // Get current position symbols
        const currentSymbols = new Set(positions.map(p => p.option_symbol));

        // Get previously tracked symbols
        const previousSymbols = new Set(this.positions.keys());

        // Remove lines for positions that no longer exist
        previousSymbols.forEach(symbol => {
            if (!currentSymbols.has(symbol)) {
                window.PriceLineManager.removePosition(symbol);
                console.log(`Removed price lines for closed position: ${symbol}`);
            }
        });

        // Add/update lines for each position
        positions.forEach(position => {
            if (position.asset_type === 'stock') {
                window.PriceLineManager.removePosition(position.option_symbol);
                return;
            }

            // ONLY sync lines for the current symbol being viewed on the chart
            if (position.symbol !== window.App?.currentSymbol) {
                // Remove line if it was previously there but symbol changed
                window.PriceLineManager.removePosition(position.option_symbol);
                console.log(`PositionTracker: Skipping position ${position.option_symbol} - underlying ${position.symbol} doesn't match chart symbol ${window.App?.currentSymbol}`);
                return;
            }

            console.log(`PositionTracker: Syncing position ${position.option_symbol} for ${position.symbol}`);


            // Entry line (always update to show current contracts)
            window.PriceLineManager.addEntryLine(
                position.option_symbol,
                position.underlying_entry_price,
                position.remaining_contracts,
                position.entry_price,
                position.contract_type
            );

            // Stop loss line
            const slLineId = `sl_${position.option_symbol}`;
            const isDraggingSL = window.DragHandles?.isDraggingLine(slLineId);

            if (position.stop_loss_price && !isDraggingSL) {
                window.PriceLineManager.addStopLossLine(
                    position.option_symbol,
                    position.stop_loss_price,
                    position.contract_type
                );
            }

            // Take profit line
            const tpLineId = `tp_${position.option_symbol}`;
            const isDraggingTP = window.DragHandles?.isDraggingLine(tpLineId);

            if (position.take_profit_price && !isDraggingTP) {
                window.PriceLineManager.addTakeProfitLine(
                    position.option_symbol,
                    position.take_profit_price,
                    position.contract_type
                );
            }
        });
    }

    /**
     * Update day P&L display
     */
    async updateDayPnL() {
        try {
            const response = await window.ApiClient.getDayPnL();

            if (!response || !this.dayPnLEl) {
                return;
            }

            const pnl = response.day_pnl || 0;
            const pnlValue = this.dayPnLEl.querySelector('.pnl-value');

            if (pnlValue) {
                pnlValue.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}`;
                pnlValue.className = `pnl-value ${pnl >= 0 ? 'positive' : 'negative'}`;
            }

        } catch (error) {
            console.error('Error updating day P&L:', error);
        }
    }

    /**
     * Destroy position tracker
     */
    destroy() {
        this.stopPolling();
        this.positions.clear();
    }
}

// Global instance (initialized in main.js)
window.PositionTracker = null;
