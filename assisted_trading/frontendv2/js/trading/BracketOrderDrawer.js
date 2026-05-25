/**
 * BracketOrderDrawer - Click-and-drag bracket order placement
 * TradingView-style: Click entry → Drag for TP → Auto-calculate SL with visual preview
 * @version 1.0 - Revolutionary one-gesture bracket order creation
 */

class BracketOrderDrawer {
    constructor(chartManager, tradingPanel) {
        this.chartManager = chartManager;
        this.tradingPanel = tradingPanel;
        this.isDrawing = false;
        this.enabled = false;
        this.entryPrice = null;
        this.currentPrice = null;
        this.contractType = 'CALL'; // Will be determined by drag direction

        // Preview lines
        this.previewLines = {
            entry: null,
            sl: null,
            tp: null
        };

        // Floating tooltip
        this.tooltip = null;

        // Default risk:reward ratio
        this.defaultRiskRewardRatio = 2.0;

        // Pointer event handlers
        this.onPointerDown = this.handlePointerDown.bind(this);
        this.onPointerMove = this.handlePointerMove.bind(this);
        this.onPointerUp = this.handlePointerUp.bind(this);
        this.onPointerCancel = this.handlePointerCancel.bind(this);

        console.log('BracketOrderDrawer initialized');
    }

    /**
     * Enable bracket order drawing mode
     */
    enable() {
        if (this.enabled) return;

        const container = this.chartManager.container;
        if (!container) {
            console.error('Chart container not found');
            return;
        }

        // Add event listeners
        container.addEventListener('pointerdown', this.onPointerDown);
        container.addEventListener('pointermove', this.onPointerMove);
        container.addEventListener('pointerup', this.onPointerUp);
        container.addEventListener('pointercancel', this.onPointerCancel);

        // Change cursor to indicate drawing mode
        container.style.cursor = 'crosshair';
        container.style.touchAction = 'none';

        this.enabled = true;
        console.log('Bracket order drawing enabled');

        // Show instruction toast
        if (window.Toast) {
            window.Toast.info('Click on chart to set entry, then drag to set TP/SL', 4000);
        }
    }

    /**
     * Disable bracket order drawing mode
     */
    disable() {
        if (!this.enabled) return;

        const container = this.chartManager.container;
        if (container) {
            container.removeEventListener('pointerdown', this.onPointerDown);
            container.removeEventListener('pointermove', this.onPointerMove);
            container.removeEventListener('pointerup', this.onPointerUp);
            container.removeEventListener('pointercancel', this.onPointerCancel);

            container.style.cursor = 'default';
            container.style.touchAction = 'auto';
        }

        // Clear any ongoing drawing
        this.cancelDrawing();

        this.enabled = false;
        console.log('Bracket order drawing disabled');
    }

    /**
     * Handle pointer down - start drawing
     */
    handlePointerDown(event) {
        if (!this.enabled) return;

        const price = this.getPriceFromEvent(event);
        if (price === null) return;

        // Start bracket order
        this.startBracketOrder(price);
        event.preventDefault();
    }

    /**
     * Handle pointer move - update preview
     */
    handlePointerMove(event) {
        if (!this.isDrawing) return;

        const price = this.getPriceFromEvent(event);
        if (price === null) return;

        this.currentPrice = price;
        this.updateBracketPreview();
    }

    /**
     * Handle pointer up - complete order
     */
    handlePointerUp(event) {
        if (!this.isDrawing) return;

        const price = this.getPriceFromEvent(event);
        if (price === null) {
            this.cancelDrawing();
            return;
        }

        this.completeBracketOrder(price);
        event.preventDefault();
    }

    /**
     * Handle pointer cancel
     */
    handlePointerCancel(event) {
        this.cancelDrawing();
    }

    /**
     * Get price from pointer event
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
     * Start bracket order
     */
    startBracketOrder(price) {
        this.isDrawing = true;
        this.entryPrice = price;
        this.currentPrice = price;

        // Create entry preview line
        this.createPreviewLine('entry', price, '#3861fb', 'Entry');

        // Create tooltip
        this.createTooltip();

        console.log(`Started bracket order at $${price.toFixed(2)}`);
    }

    /**
     * Update bracket preview
     */
    updateBracketPreview() {
        if (!this.entryPrice || !this.currentPrice) return;

        const dragDistance = this.currentPrice - this.entryPrice;

        // Determine contract type from drag direction
        if (dragDistance > 0) {
            // Dragging up = bullish = CALL
            this.contractType = 'CALL';
            const tpPrice = this.currentPrice;
            const slPrice = this.entryPrice - (dragDistance / this.defaultRiskRewardRatio);

            this.updatePreviewLine('tp', tpPrice, '#0ecb81', 'TP');
            this.updatePreviewLine('sl', slPrice, '#f6465d', 'SL');

        } else if (dragDistance < 0) {
            // Dragging down = bearish = PUT
            this.contractType = 'PUT';
            const tpPrice = this.currentPrice;
            const slPrice = this.entryPrice + (Math.abs(dragDistance) / this.defaultRiskRewardRatio);

            this.updatePreviewLine('tp', tpPrice, '#0ecb81', 'TP');
            this.updatePreviewLine('sl', slPrice, '#f6465d', 'SL');
        }

        // Update tooltip
        this.updateTooltip();
    }

    /**
     * Create preview price line
     */
    createPreviewLine(type, price, color, title) {
        const series = this.chartManager.getSeries();
        if (!series) return;

        // Remove existing line if any
        if (this.previewLines[type]) {
            try {
                series.removePriceLine(this.previewLines[type]);
            } catch (e) {}
        }

        // Create new line
        this.previewLines[type] = series.createPriceLine({
            price: price,
            color: color + '80', // Semi-transparent
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: title,
        });
    }

    /**
     * Update preview price line
     */
    updatePreviewLine(type, price, color, title) {
        if (!this.previewLines[type]) {
            this.createPreviewLine(type, price, color, title);
        } else {
            try {
                this.previewLines[type].applyOptions({ price: price });
            } catch (e) {
                this.createPreviewLine(type, price, color, title);
            }
        }
    }

    /**
     * Create floating tooltip
     */
    createTooltip() {
        // Create tooltip element
        this.tooltip = document.createElement('div');
        this.tooltip.className = 'bracket-order-tooltip';
        this.tooltip.style.cssText = `
            position: fixed;
            background: rgba(15, 20, 25, 0.95);
            border: 1px solid var(--border);
            border-radius: 6px;
            padding: 12px;
            font-size: 12px;
            color: var(--text-primary);
            pointer-events: none;
            z-index: 10000;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;
        document.body.appendChild(this.tooltip);
    }

    /**
     * Update tooltip content and position
     */
    updateTooltip() {
        if (!this.tooltip) return;

        const dragDistance = Math.abs(this.currentPrice - this.entryPrice);
        const risk = dragDistance / this.defaultRiskRewardRatio;
        const reward = dragDistance;
        const riskRewardRatio = reward / risk;

        // Position tooltip near mouse
        const container = this.chartManager.container.getBoundingClientRect();
        this.tooltip.style.left = (container.right - 250) + 'px';
        this.tooltip.style.top = (container.top + 20) + 'px';

        // Update content
        this.tooltip.innerHTML = `
            <div style="font-weight: bold; margin-bottom: 8px; color: ${this.contractType === 'CALL' ? '#0ecb81' : '#f6465d'}">
                ${this.contractType} Bracket Order
            </div>
            <div style="display: grid; grid-template-columns: 80px 1fr; gap: 6px;">
                <div>Entry:</div><div style="font-weight: bold;">$${this.entryPrice.toFixed(2)}</div>
                <div style="color: #0ecb81;">TP:</div><div style="color: #0ecb81; font-weight: bold;">$${(this.contractType === 'CALL' ? this.currentPrice : this.currentPrice).toFixed(2)}</div>
                <div style="color: #f6465d;">SL:</div><div style="color: #f6465d; font-weight: bold;">$${(this.contractType === 'CALL' ? this.entryPrice - risk : this.entryPrice + risk).toFixed(2)}</div>
                <div>Risk:</div><div>$${(risk * 100).toFixed(0)}</div>
                <div>Reward:</div><div>$${(reward * 100).toFixed(0)}</div>
                <div>R:R:</div><div style="color: ${riskRewardRatio >= 2 ? '#0ecb81' : '#FFC107'};">1:${riskRewardRatio.toFixed(1)}</div>
            </div>
        `;
    }

    /**
     * Complete bracket order - submit to trading panel
     */
    completeBracketOrder(finalPrice) {
        if (!this.entryPrice) {
            this.cancelDrawing();
            return;
        }

        const dragDistance = Math.abs(finalPrice - this.entryPrice);
        const risk = dragDistance / this.defaultRiskRewardRatio;

        let tpPrice, slPrice;

        if (finalPrice > this.entryPrice) {
            // CALL
            this.contractType = 'CALL';
            tpPrice = finalPrice;
            slPrice = this.entryPrice - risk;
        } else {
            // PUT
            this.contractType = 'PUT';
            tpPrice = finalPrice;
            slPrice = this.entryPrice + risk;
        }

        console.log(`Bracket order completed: ${this.contractType} @ $${this.entryPrice.toFixed(2)}, TP: $${tpPrice.toFixed(2)}, SL: $${slPrice.toFixed(2)}`);

        // Set values in trading panel
        if (this.tradingPanel) {
            // Set contract type
            this.tradingPanel.setContractType(this.contractType);

            // Set SL/TP values
            const slInput = document.getElementById('stopLoss');
            const tpInput = document.getElementById('takeProfit');

            if (slInput) slInput.value = slPrice.toFixed(2);
            if (tpInput) tpInput.value = tpPrice.toFixed(2);

            // Show success message
            if (window.Toast) {
                window.Toast.success(`Bracket order ready: ${this.contractType} with SL/TP set`, 3000);
            }
        }

        // Clear preview
        this.cancelDrawing();

        // Disable drawing mode after completing one order
        this.disable();
    }

    /**
     * Cancel current drawing
     */
    cancelDrawing() {
        // Remove preview lines
        const series = this.chartManager.getSeries();
        if (series) {
            for (const type in this.previewLines) {
                if (this.previewLines[type]) {
                    try {
                        series.removePriceLine(this.previewLines[type]);
                    } catch (e) {}
                    this.previewLines[type] = null;
                }
            }
        }

        // Remove tooltip
        if (this.tooltip && this.tooltip.parentNode) {
            this.tooltip.parentNode.removeChild(this.tooltip);
            this.tooltip = null;
        }

        // Reset state
        this.isDrawing = false;
        this.entryPrice = null;
        this.currentPrice = null;
    }
}

// Make globally available
window.BracketOrderDrawer = BracketOrderDrawer;
