/**
 * DragHandles - Handles drag-and-drop for SL/TP price lines
 * Implements full pointer tracking and coordinate conversion for price line dragging
 * Optimized with Pointer Events API, throttling, and visual feedback
 * @version 2.0 - Enhanced with TradingView-level interactions
 */

class DragHandles {
    constructor(chartManager, priceLineManager) {
        this.chartManager = chartManager;
        this.priceLineManager = priceLineManager;
        this.isDragging = false;
        this.currentLineId = null;
        this.dragStartPrice = null;
        this.enabled = false;
        this.hoveredLine = null;

        // Throttle settings for performance
        this.lastUpdateTime = 0;
        this.updateInterval = 16; // ~60fps

        // Pointer event handlers (bound to this)
        this.onPointerDown = this.handlePointerDown.bind(this);
        this.onPointerMove = this.handlePointerMove.bind(this);
        this.onPointerUp = this.handlePointerUp.bind(this);
        this.onPointerCancel = this.handlePointerUp.bind(this);

        console.log('DragHandles v2.0 initialized with Pointer Events API');
    }

    /**
     * Enable drag handles with Pointer Events API
     */
    enable() {
        if (this.enabled) return;

        const chart = this.chartManager.getChart();
        if (!chart) {
            console.error('Chart not initialized');
            return;
        }

        // Get the chart container element
        const chartContainer = this.chartManager.container;
        if (!chartContainer) {
            console.error('Chart container not found');
            return;
        }

        // Add Pointer Event listeners (supports mouse, touch, and pen)
        chartContainer.addEventListener('pointerdown', this.onPointerDown);
        chartContainer.addEventListener('pointermove', this.onPointerMove);
        chartContainer.addEventListener('pointerup', this.onPointerUp);
        chartContainer.addEventListener('pointercancel', this.onPointerCancel);
        chartContainer.addEventListener('pointerleave', this.onPointerUp);

        // Disable default touch actions for smoother dragging
        chartContainer.style.touchAction = 'none';

        this.enabled = true;
        console.log('Drag handles enabled with Pointer Events API');
    }

    /**
     * Disable drag handles
     */
    disable() {
        if (!this.enabled) return;

        const chartContainer = this.chartManager.container;
        if (chartContainer) {
            chartContainer.removeEventListener('pointerdown', this.onPointerDown);
            chartContainer.removeEventListener('pointermove', this.onPointerMove);
            chartContainer.removeEventListener('pointerup', this.onPointerUp);
            chartContainer.removeEventListener('pointercancel', this.onPointerCancel);
            chartContainer.removeEventListener('pointerleave', this.onPointerUp);

            // Re-enable default touch actions
            chartContainer.style.touchAction = 'auto';
        }

        this.enabled = false;
        console.log('Drag handles disabled');
    }

    /**
     * Handle pointer down - initiate drag from line or price axis label
     * Uses tight threshold to avoid false positives from general chart clicks
     */
    handlePointerDown(event) {
        const chart = this.chartManager.getChart();
        if (!chart) return;

        // Ignore events from UI elements outside chart
        const target = event.target;
        if (target.closest('.bottom-resize-handle') ||
            target.closest('.bottom-panels-container') ||
            target.closest('.trading-panel') ||
            target.closest('.order-panel-on-chart') ||
            target.closest('.price-marker')) {
            return;
        }

        const rect = this.chartManager.container.getBoundingClientRect();
        const x = event.clientX - rect.left;
        const y = event.clientY - rect.top;

        // Ignore if clicking outside chart bounds
        if (y < 0 || y > rect.height || x < 0 || x > rect.width) {
            return;
        }

        // Convert Y coordinate to price
        const price = this.coordinateToPrice(y);
        if (price === null) return;

        // Check if clicking near any draggable line
        const draggableLines = this.priceLineManager.getDraggableLines();
        // TIGHT threshold - only trigger if cursor is very close to the line
        const threshold = this.getPriceThreshold() * 0.8;

        for (const lineData of draggableLines) {
            const linePriceDiff = Math.abs(lineData.price - price);

            if (linePriceDiff <= threshold) {
                // Start dragging this line
                this.startDrag(lineData.lineId, lineData.price);
                this.setCursor('grabbing');
                event.preventDefault();
                event.stopPropagation(); // Prevent chart from handling this
                return;
            }
        }
    }

    /**
     * Handle pointer move - update line position while dragging + hover detection
     */
    handlePointerMove(event) {
        const rect = this.chartManager.container.getBoundingClientRect();
        const y = event.clientY - rect.top;
        const x = event.clientX - rect.left;

        // Ignore if outside chart
        if (y < 0 || y > rect.height || x < 0 || x > rect.width) {
            if (this.hoveredLine !== null) {
                this.hoveredLine = null;
                this.setCursor('default');
            }
            return;
        }

        // Convert Y coordinate to price
        const price = this.coordinateToPrice(y);
        if (price === null) return;

        // Handle dragging with throttling
        if (this.isDragging) {
            // Throttle updates for performance (60fps max)
            const now = Date.now();
            if (now - this.lastUpdateTime < this.updateInterval) {
                return;
            }
            this.lastUpdateTime = now;

            // Update the line position visually
            this.moveDrag(price);
        } else {
            // Check for hover over draggable lines (anywhere on chart)
            this.checkHover(price);
        }
    }

    /**
     * Handle pointer up - finish dragging (ENHANCED)
     */
    handlePointerUp(event) {
        if (!this.isDragging) {
            this.setCursor('default');
            return;
        }

        const rect = this.chartManager.container.getBoundingClientRect();
        const y = event.clientY - rect.top;

        // Convert Y coordinate to price
        const finalPrice = this.coordinateToPrice(y);
        if (finalPrice === null) {
            this.isDragging = false;
            this.currentLineId = null;
            this.setCursor('default');
            return;
        }

        // End the drag
        this.endDrag(finalPrice);
        this.setCursor('default');
    }

    /**
     * Check if hovering over a draggable line and update cursor
     * Uses slightly larger threshold than click detection for smoother UX
     */
    checkHover(price) {
        const draggableLines = this.priceLineManager.getDraggableLines();
        // Hover threshold slightly larger than click threshold (1.2x vs 0.8x)
        const threshold = this.getPriceThreshold() * 1.2;

        let foundHover = false;
        for (const lineData of draggableLines) {
            const linePriceDiff = Math.abs(lineData.price - price);

            if (linePriceDiff <= threshold) {
                if (this.hoveredLine !== lineData.lineId) {
                    this.hoveredLine = lineData.lineId;
                    this.setCursor('grab');
                }
                foundHover = true;
                return;
            }
        }

        if (!foundHover && this.hoveredLine !== null) {
            this.hoveredLine = null;
            this.setCursor('default');
        }
    }

    /**
     * Set cursor style
     */
    setCursor(cursorType) {
        const chartContainer = this.chartManager.container;
        if (!chartContainer) return;

        const cursorMap = {
            'default': 'default',
            'grab': 'grab',
            'grabbing': 'grabbing',
            'crosshair': 'crosshair'
        };

        chartContainer.style.cursor = cursorMap[cursorType] || 'default';
    }

    /**
     * Convert Y coordinate to price value
     */
    coordinateToPrice(y) {
        const chart = this.chartManager.getChart();
        if (!chart) return null;

        try {
            const series = this.chartManager.getSeries();
            if (!series) return null;

            // In TradingView Lightweight Charts v5.0, use series.coordinateToPrice directly
            const price = series.coordinateToPrice(y);
            return price;
        } catch (error) {
            console.error('Error converting coordinate to price:', error);
            return null;
        }
    }

    /**
     * Get the price threshold for detecting line clicks
     * Returns a price value (not pixels)
     */
    getPriceThreshold() {
        const chart = this.chartManager.getChart();
        if (!chart) return 0.5;

        try {
            const series = this.chartManager.getSeries();
            if (!series) return 0.5;

            const priceScale = series.priceScale();
            if (!priceScale) return 0.5;

            // Convert 10 pixels to price difference
            const price1 = priceScale.coordinateToPrice(0);
            const price2 = priceScale.coordinateToPrice(10);

            return Math.abs(price2 - price1);
        } catch (error) {
            return 0.5; // Default threshold
        }
    }

    /**
     * Handle drag move (OPTIMIZED - uses applyOptions instead of recreating line)
     * @param {number} newPrice - New price from pointer position
     */
    moveDrag(newPrice) {
        if (!this.isDragging || !this.currentLineId) {
            return;
        }

        // Get line data
        const lineData = this.priceLineManager.getLine(this.currentLineId);
        if (!lineData || !lineData.priceLine) return;

        // CRITICAL OPTIMIZATION: Use applyOptions to update price directly
        // instead of removing and recreating the entire line
        try {
            lineData.priceLine.applyOptions({ price: newPrice });
            lineData.price = newPrice; // Update internal tracking
        } catch (error) {
            // Fallback to old method if applyOptions fails
            console.warn('applyOptions failed, using fallback:', error);
            this.priceLineManager.updateLinePrice(this.currentLineId, newPrice);
        }
    }

    /**
     * Check if a specific line is currently being dragged
     * @param {string} lineId 
     */
    isDraggingLine(lineId) {
        return this.isDragging && this.currentLineId === lineId;
    }

    /**
     * Handle drag end
     * @param {number} finalPrice - Final price after drag
     */
    async endDrag(finalPrice) {
        if (!this.isDragging || !this.currentLineId) {
            return;
        }

        const lineId = this.currentLineId;
        const startPrice = this.dragStartPrice;
        this.isDragging = false;
        this.currentLineId = null;

        console.log(`Ended dragging ${lineId} at $${finalPrice}`);

        // Get line data
        const lineData = this.priceLineManager.getLine(lineId);
        if (!lineData) return;

        // 1. Validate the new price
        const isValid = this.validatePrice(lineData.type, finalPrice, lineData.contractType);
        if (!isValid) {
            window.Toast?.error(`${lineData.type.toUpperCase()} invalid level. Reverting.`, 3000);
            this.revertLine(lineId, startPrice);
            return;
        }

        // 2. Show confirmation UI
        this.showConfirmationUI(lineId, finalPrice, lineData, startPrice);
    }

    /**
     * Validate SL/TP price against current price
     */
    validatePrice(type, price, contractType) {
        // We need the current price of the underlying
        if (!window.TradingPanel || !window.TradingPanel.lastUnderlyingPrice) return true;

        const currentPrice = window.TradingPanel.lastUnderlyingPrice;
        if (type === 'stop_loss') {
            return contractType === 'CALL' ? price < currentPrice : price > currentPrice;
        } else if (type === 'take_profit') {
            return contractType === 'CALL' ? price > currentPrice : price < currentPrice;
        }
        return true;
    }

    /**
     * Show confirmation buttons on the chart
     */
    showConfirmationUI(lineId, newPrice, lineData, startPrice) {
        // Remove any existing confirmation UI
        this.clearConfirmationUI();

        const container = document.createElement('div');
        container.className = 'drag-confirm-container';
        container.id = 'drag-confirm-ui';

        // Position it near the price line
        const chartRect = this.chartManager.container.getBoundingClientRect();
        const y = this.priceToY(newPrice);
        if (y === null) return;

        const absoluteY = chartRect.top + y;
        const rightOffset = window.innerWidth - chartRect.right + 120; // Positioned near the label

        container.style.top = `${absoluteY - 45}px`;
        container.style.right = `${rightOffset}px`;

        container.innerHTML = `
            <div class="drag-confirm-price">Set ${lineData.type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')}: $${newPrice.toFixed(2)}?</div>
            <div class="drag-confirm-buttons">
                <button class="drag-confirm-btn confirm">Confirm</button>
                <button class="drag-confirm-btn cancel">Cancel</button>
            </div>
        `;

        document.body.appendChild(container);

        // Bind buttons
        container.querySelector('.confirm').onclick = () => this.executeUpdate(lineId, newPrice, lineData);
        container.querySelector('.cancel').onclick = () => {
            this.revertLine(lineId, startPrice);
            this.clearConfirmationUI();
        };

        // Auto-clear after 10 seconds set if user ignores it
        this.confirmTimeout = setTimeout(() => {
            if (document.getElementById('drag-confirm-ui')) {
                this.revertLine(lineId, startPrice);
                this.clearConfirmationUI();
                window.Toast?.info('Update timed out. Reverting.', 2000);
            }
        }, 10000);
    }

    /**
     * Execute the update on backend
     */
    async executeUpdate(lineId, price, lineData) {
        this.clearConfirmationUI();
        window.Toast?.info(`Updating ${lineData.type.split('_').join(' ')}...`, 2000);

        try {
            if (lineData.type === 'stop_loss') {
                await window.ApiClient.updateStopLossTakeProfit(
                    lineData.optionSymbol,
                    price,
                    null
                );
            } else if (lineData.type === 'take_profit') {
                await window.ApiClient.updateStopLossTakeProfit(
                    lineData.optionSymbol,
                    null,
                    price
                );
            }

            window.Toast?.success('Level updated successfully!');

            // Emit event
            window.EventBus.emit('draghandle:dropped', {
                lineId: lineId,
                type: lineData.type,
                optionSymbol: lineData.optionSymbol,
                newPrice: price
            });

        } catch (error) {
            console.error('Error updating SL/TP:', error);
            window.Toast?.error(`Failed to update: ${error.message}`);
            // Revert on error? Or keep? Let's keep for now so they don't lose the drag pos if it was temporary network error
        }
    }

    revertLine(lineId, originalPrice) {
        const lineData = this.priceLineManager.getLine(lineId);
        if (lineData && lineData.priceLine) {
            lineData.priceLine.applyOptions({ price: originalPrice });
            lineData.price = originalPrice;
        }
    }

    clearConfirmationUI() {
        const el = document.getElementById('drag-confirm-ui');
        if (el) el.remove();
        if (this.confirmTimeout) clearTimeout(this.confirmTimeout);
    }

    priceToY(price) {
        const series = this.chartManager.getSeries();
        if (!series) return null;
        try {
            return series.priceToCoordinate(price);
        } catch (e) {
            return null;
        }
    }

    /**
     * Handle drag start
     * @param {string} lineId - Line ID being dragged
     * @param {number} startPrice - Starting price
     */
    startDrag(lineId, startPrice) {
        this.clearConfirmationUI(); // Clear any pending UI
        this.isDragging = true;
        this.currentLineId = lineId;
        this.dragStartPrice = startPrice;
        console.log(`Started dragging ${lineId} from $${startPrice}`);
    }
}

// Global instance (initialized in main.js)
window.DragHandles = null;
