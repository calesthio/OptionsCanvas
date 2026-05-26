/**
 * PositionPanelOnChart - Floating panel for open positions on the chart
 * Displays P&L and a 'Close' button following the entry line
 */

class PositionPanelOnChart {
    constructor(chartManager) {
        this.chartManager = chartManager;
        this.panels = new Map(); // Map of optionSymbol -> panel element
        this.positions = [];
        this.enabled = true;

        // Bind handlers
        this.onChartResize = this.updatePositions.bind(this);

        // Listen for events
        window.EventBus?.on('chart:bar_update', () => this.updatePositions());
        window.addEventListener('resize', this.onChartResize);

        // Listen for chart scroll/scale
        if (this.chartManager.chart) {
            this.chartManager.chart.timeScale().subscribeVisibleTimeRangeChange(() => {
                this.updatePositions();
            });
        }

        console.log('PositionPanelOnChart initialized');
    }

    /**
     * Sync data from PositionTracker
     * @param {Array} positions - Array of position objects
     */
    syncPositions(positions) {
        this.positions = positions.filter(pos =>
            pos.asset_type !== 'stock' && pos.symbol === window.App?.currentSymbol
        );

        // Symbols in current data
        const currentSymbols = new Set(this.positions.map(p => p.option_symbol));

        // Remove panels for closed positions
        for (const [symbol, panel] of this.panels.entries()) {
            if (!currentSymbols.has(symbol)) {
                this.removePanel(symbol);
            }
        }

        // Create/Update panels for active positions
        this.positions.forEach(pos => {
            if (!this.panels.has(pos.option_symbol)) {
                this.createPanel(pos);
            } else {
                this.updatePanelContent(pos);
            }
        });

        this.updatePositions();
    }

    /**
     * Create a panel for a position
     */
    createPanel(pos) {
        const panel = document.createElement('div');
        panel.className = 'position-panel-on-chart';
        panel.dataset.symbol = pos.option_symbol;

        const color = pos.contract_type === 'CALL' ? '#0ecb81' : '#f6465d';

        panel.style.cssText = `
            position: fixed;
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(15, 20, 25, 0.9);
            border: 1px solid ${color}80;
            border-radius: 4px;
            padding: 4px 8px;
            pointer-events: auto;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
            font-size: 11px;
            color: white;
            white-space: nowrap;
            will-change: transform;
        `;

        this.updatePanelContent_Internal(panel, pos, color);
        document.body.appendChild(panel);
        this.panels.set(pos.option_symbol, panel);
    }

    /**
     * Update panel content
     */
    updatePanelContent(pos) {
        const panel = this.panels.get(pos.option_symbol);
        if (!panel) return;

        const color = pos.contract_type === 'CALL' ? '#0ecb81' : '#f6465d';
        this.updatePanelContent_Internal(panel, pos, color);
    }

    updatePanelContent_Internal(panel, pos, color) {
        const pnl = pos.unrealized_pnl || 0;
        const pnlPct = pos.unrealized_pnl_pct || 0;
        const pnlClass = pnl >= 0 ? 'text-green' : 'text-red';
        const pnlColor = pnl >= 0 ? '#0ecb81' : '#f6465d';

        // Inline "+ SL" / "+ TP" affordance — only when the corresponding
        // level isn't set yet. Outlined (no fill) so they read as secondary
        // to CLOSE. Clicking spawns a draggable dashed price line; the
        // existing DragHandles flow handles drag → confirm → save.
        const hasSL = pos.stop_loss_price != null;
        const hasTP = pos.take_profit_price != null;
        const chipBase = `
            background: transparent;
            border-radius: 3px;
            padding: 1px 6px;
            font-size: 10px;
            font-weight: 600;
            cursor: pointer;
            line-height: 14px;
        `;
        const slChip = hasSL ? '' : `
            <button class="add-sl-btn" title="Drop a draggable SL line" style="
                ${chipBase}
                border: 1px dashed #f6465d;
                color: #f6465d;
            ">+ SL</button>`;
        const tpChip = hasTP ? '' : `
            <button class="add-tp-btn" title="Drop a draggable TP line" style="
                ${chipBase}
                border: 1px dashed #0ecb81;
                color: #0ecb81;
            ">+ TP</button>`;

        panel.innerHTML = `
            <span style="font-weight: bold; padding: 2px 4px; border-radius: 2px; background: ${color}30; color: ${color}">${pos.contract_type}</span>
            <span style="font-weight: 600;">${pos.remaining_contracts}c</span>
            <span style="color: ${pnlColor}; font-weight: bold;">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)}</span>
            <span style="font-size: 9px; opacity: 0.8;">(${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(1)}%)</span>
            ${slChip}
            ${tpChip}
            <button class="close-btn" style="
                background: ${pnlColor};
                color: white;
                border: none;
                border-radius: 3px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: bold;
                cursor: pointer;
                margin-left: 4px;
            ">CLOSE</button>
        `;

        const closeBtn = panel.querySelector('.close-btn');
        closeBtn.onclick = (e) => {
            e.stopPropagation();
            if (window.PositionTracker) {
                window.PositionTracker.sellContracts(pos.option_symbol, pos.remaining_contracts);
            }
        };

        // Wire add-SL / add-TP. innerHTML reassignment above means we have
        // to re-bind every update tick — same pattern as the close button.
        const slBtn = panel.querySelector('.add-sl-btn');
        if (slBtn) {
            slBtn.onclick = (e) => {
                e.stopPropagation();
                this.spawnPendingLevel(pos, 'stop_loss');
            };
        }
        const tpBtn = panel.querySelector('.add-tp-btn');
        if (tpBtn) {
            tpBtn.onclick = (e) => {
                e.stopPropagation();
                this.spawnPendingLevel(pos, 'take_profit');
            };
        }
    }

    /**
     * Drop a draggable, dashed "pending" SL or TP line near the position's
     * underlying entry, then immediately put it into drag mode so it
     * follows the cursor onto the chart. One click on the chart drops it
     * and triggers the existing confirm flow.
     *
     * Anchor: small adverse-side offset from CURRENT underlying price (not
     * entry) so the line is in the user's visual hot zone and always
     * passes DragHandles.validatePrice from the start, even when the
     * position is deep in drawdown.
     */
    spawnPendingLevel(pos, type) {
        if (!window.PriceLineManager) {
            console.warn('spawnPendingLevel: PriceLineManager not ready');
            return;
        }

        // Prefer live underlying price (matches what DragHandles.validatePrice
        // checks against). Fall back to entry if we don't have it yet.
        const current = Number(window.TradingPanel?.lastUnderlyingPrice)
            || Number(pos.underlying_entry_price);
        if (!current || isNaN(current)) {
            window.Toast?.warning('Current price unavailable; cannot spawn line.');
            return;
        }

        // 2% off the current price, on the side validatePrice will accept.
        // Far enough to be obvious; user is meant to drag it where they want.
        const isCall = pos.contract_type === 'CALL';
        let startPrice;
        if (type === 'stop_loss') {
            startPrice = isCall ? current * 0.98 : current * 1.02;
            window.PriceLineManager.addStopLossLine(
                pos.option_symbol, startPrice, pos.contract_type, { pending: true }
            );
        } else {
            startPrice = isCall ? current * 1.02 : current * 0.98;
            window.PriceLineManager.addTakeProfitLine(
                pos.option_symbol, startPrice, pos.contract_type, { pending: true }
            );
        }

        const lineId = type === 'stop_loss'
            ? `sl_${pos.option_symbol}`
            : `tp_${pos.option_symbol}`;

        // Kick into drag mode RIGHT NOW. The chart's pointermove listener
        // will start moving the line as soon as the cursor enters the chart
        // area; pointerup on the chart drops it and pops the confirm UI.
        // This is the "drag the chip onto the chart" UX — no hunting for a
        // tiny line, no precision grab required.
        if (window.DragHandles?.enabled) {
            window.DragHandles.startDrag(lineId, startPrice);
            window.DragHandles.setCursor('grabbing');
        }

        const label = type === 'stop_loss' ? 'Stop Loss' : 'Take Profit';
        window.Toast?.info(
            `Move cursor onto the chart, then click to drop your ${label}.`,
            5000
        );
    }

    /**
     * Update all panel positions
     */
    updatePositions() {
        if (!this.enabled) return;

        const chartRect = this.chartManager.container.getBoundingClientRect();
        const series = this.chartManager.getSeries();
        if (!series) return;

        this.positions.forEach(pos => {
            const panel = this.panels.get(pos.option_symbol);
            if (!panel) return;

            const y = series.priceToCoordinate(pos.underlying_entry_price);
            if (y !== null && !isNaN(y)) {
                const absoluteY = chartRect.top + y;
                // Move it slightly to the left of the other panels or just at a standard offset
                const rightOffset = window.innerWidth - chartRect.right + 180;

                panel.style.top = `${absoluteY - 14}px`;
                panel.style.right = `${rightOffset}px`;
                panel.style.display = 'flex';
            } else {
                panel.style.display = 'none';
            }
        });
    }

    removePanel(symbol) {
        const panel = this.panels.get(symbol);
        if (panel && panel.parentNode) {
            panel.parentNode.removeChild(panel);
        }
        this.panels.delete(symbol);
    }

    clearAll() {
        for (const symbol of this.panels.keys()) {
            this.removePanel(symbol);
        }
    }
}

window.PositionPanelOnChart = PositionPanelOnChart;
