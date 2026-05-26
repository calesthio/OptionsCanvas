/**
 * OrderPanelOnChart - TradingView-style order panel on price line
 * Compact panel with SL/TP buttons that expand when dragged
 * @version 5.1 - Fixed color glitch and projection updates
 */

class OrderPanelOnChart {
    constructor(chartManager, tradingPanel, chartTradingController = null) {
        this.chartManager = chartManager;
        this.tradingPanel = tradingPanel;
        // Controller is optional for backward compat; falls back to window global
        // (set by the ESM module load) and finally to a legacy readiness check.
        this.controller = chartTradingController || window.ChartTradingController || null;
        this.enabled = false;

        // Current state
        this.currentPrice = null;
        this.slPrice = null;
        this.tpPrice = null;
        this.slActive = false; // Whether SL has been set
        this.tpActive = false; // Whether TP has been set

        // UI elements
        this.panelContainer = null;
        this.slButton = null;
        this.tpButton = null;
        this.slMarker = null;
        this.tpMarker = null;

        // Price lines on chart
        this.priceLines = {
            sl: null,
            tp: null,
            entry: null
        };

        // Invisible chart-overlay hit areas that make the price lines
        // themselves draggable (TradingView-style). Keyed by type.
        this.lineHitAreas = {
            sl: null,
            tp: null
        };

        // Limit-trigger entry state. When entryTriggerActive is true the Buy
        // pill is anchored to entryTriggerPrice (not the live price) and the
        // side panel is in limit-order mode with the trigger pre-filled.
        this.entryTriggerPrice = null;
        this.entryTriggerActive = false;

        // Dragging state
        this.isDragging = false;
        this.dragTarget = null; // 'sl' or 'tp'
        this.dragTargetEl = null; // The element being dragged (marker)
        this.dragStartY = 0;
        this.dragStartPrice = 0;

        // Animation & Performance
        this.rafId = null;
        this.chartRect = null;

        // Pricing Calculator
        this.bsCalculator = window.BlackScholesCalculator ? new window.BlackScholesCalculator() : null;

        // Bind handlers
        this.onPointerDown = this.handlePointerDown.bind(this);
        this.onPointerMove = this.handlePointerMove.bind(this);
        this.onPointerUp = this.handlePointerUp.bind(this);
        this.onChartResize = this.updatePositions.bind(this);

        console.log('OrderPanelOnChart initialized (Seamless Dragging v5.1)');
    }

    /**
     * Enable the order panel
     */
    enable() {
        if (this.enabled) return;

        // Wait for chart to be ready
        setTimeout(() => {
            this.updateCurrentPrice();

            if (!this.currentPrice) {
                console.warn('No current price available, retrying...');
                setTimeout(() => this.enable(), 500);
                return;
            }

            // Create panel with Buy, SL, TP buttons
            this.createPanel();

            // Add event listeners
            window.addEventListener('resize', this.onChartResize);

            // Listen for Trading Panel changes
            window.EventBus?.on('trading_panel:update', this.onChartResize);
            window.EventBus?.on('trading_panel:ready', () => {
                this.syncTradingReadiness();
                this.updateProjections();
            });

            // Listen for DTE changes to stay in sync
            window.EventBus?.on('trading_panel:dte_changed', (data) => {
                console.log('OrderPanelOnChart: DTE changed to', data.dte);
                this.updateProjections();
            });

            // Listen for symbol changes - CRITICAL for showing SL/TP on any symbol
            window.EventBus?.on('chart:symbol_loaded', () => {
                console.log('OrderPanelOnChart: Symbol changed, resetting panel');
                this.resetForNewSymbol();
            });

            // Listen for SL/TP confirmed via drag - clear preview lines to avoid duplicates
            window.EventBus?.on('draghandle:dropped', (data) => {
                console.log('OrderPanelOnChart: SL/TP confirmed via drag, clearing preview');
                if (data.type === 'stop_loss') {
                    this.removeMarker('sl');
                } else if (data.type === 'take_profit') {
                    this.removeMarker('tp');
                }
            });

            // Listen for chart scroll/scale to update positions
            if (this.chartManager.chart) {
                this.chartManager.chart.timeScale().subscribeVisibleTimeRangeChange(() => {
                    this.updatePositions();
                });
            }

            // Listen for price updates
            window.EventBus?.on('chart:bar_update', () => {
                this.updateCurrentPrice();
            });

            this.enabled = true;
            console.log('Order panel enabled on price line at price:', this.currentPrice);
        }, 100);
    }

    /**
     * Reset panel for a new symbol - clears SL/TP and recreates panel
     */
    resetForNewSymbol() {
        // Clear existing SL/TP markers and lines
        this.removeMarker('sl');
        this.removeMarker('tp');

        // Drop any limit-trigger pin from the previous symbol.
        this.clearEntryTrigger();

        // Reset state
        this.slPrice = null;
        this.tpPrice = null;
        this.slActive = false;
        this.tpActive = false;

        // Update current price for new symbol
        this.updateCurrentPrice();

        // Recreate panel at new position
        if (this.panelContainer) {
            this.updatePanelPosition();
        }
    }

    /**
     * Disable the order panel
     */
    disable() {
        if (!this.enabled) return;

        // Remove UI
        this.removeElement(this.panelContainer);
        this.removeElement(this.slMarker);
        this.removeElement(this.tpMarker);

        // Remove price lines (also removes their hit-area overlays)
        this.removePriceLines();

        // Remove event listeners
        window.removeEventListener('resize', this.onChartResize);
        window.EventBus?.off('trading_panel:update', this.onChartResize);

        this.enabled = false;
        console.log('Order panel disabled');
    }

    removeElement(el) {
        if (el && el.parentNode) {
            el.parentNode.removeChild(el);
        }
    }

    /**
     * Create the panel with Buy, SL, TP buttons
     */
    createPanel() {
        this.panelContainer = document.createElement('div');
        this.panelContainer.className = 'order-panel-on-chart';
        this.panelContainer.style.cssText = `
            position: fixed;
            z-index: 10000;
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(15, 20, 25, 0.95);
            border: 1px solid var(--border, #2d3748);
            border-radius: 4px;
            padding: 5px 8px;
            pointer-events: none; /* Allow events to pass through container, buttons specific */
            box-shadow: 0 2px 8px rgba(0,0,0,0.3);
            will-change: top, right;
        `;

        // Buy "grip" — visual hint of the draggable handle.
        const buyGrip = document.createElement('div');
        buyGrip.className = 'buy-grip';
        buyGrip.title = 'Drag to preview entry level';
        buyGrip.style.cssText = `
            color: rgba(255,255,255,0.8);
            font-size: 14px;
            cursor: grab;
            user-select: none;
            pointer-events: auto;
            padding: 0 2px;
            touch-action: none;
        `;
        buyGrip.textContent = '⋮⋮';
        buyGrip.addEventListener('pointerdown', (e) => this.handleBuyGripDown(e));
        this.buyGrip = buyGrip;

        // Buy button — click fires the order; press-and-drag past the threshold
        // turns into a visual-only level preview (no order side-effect).
        const buyBtn = document.createElement('button');
        buyBtn.textContent = '🚀 Buy';
        buyBtn.style.cssText = `
            background: #0ecb81;
            color: white;
            border: none;
            border-radius: 3px;
            padding: 4px 12px;
            font-size: 13px;
            font-weight: 600;
            cursor: grab;
            pointer-events: auto;
            touch-action: none;
            user-select: none;
        `;
        buyBtn.onclick = (e) => {
            // Suppress click that follows a drag.
            if (this._buySuppressClick) {
                this._buySuppressClick = false;
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            this.executeOrder();
        };
        buyBtn.addEventListener('pointerdown', (e) => this.handleBuyGripDown(e));
        this.buyButton = buyBtn;

        // Price display
        const priceDisplay = document.createElement('div');
        priceDisplay.style.cssText = `
            font-weight: 600;
            color: white;
            font-size: 13px;
            min-width: 60px;
            pointer-events: auto;
        `;
        priceDisplay.textContent = `$${this.currentPrice.toFixed(2)}`;
        this.priceDisplay = priceDisplay;

        // TP button (initially collapsed)
        this.tpButton = this.createInlinePLButton('TP', '#0ecb81', 'tp');

        // SL button (initially collapsed)
        this.slButton = this.createInlinePLButton('SL', '#f6465d', 'sl');

        this.panelContainer.appendChild(buyGrip);
        this.panelContainer.appendChild(buyBtn);
        this.panelContainer.appendChild(priceDisplay);
        this.panelContainer.appendChild(this.tpButton);
        this.panelContainer.appendChild(this.slButton);

        document.body.appendChild(this.panelContainer);

        // Position panel
        this.updatePanelPosition();
        this.syncTradingReadiness();
    }

    /**
     * Create inline SL/TP button (in panel)
     */
    createInlinePLButton(label, color, type) {
        const btn = document.createElement('div');
        btn.className = `pl-btn ${type}-btn`;
        btn.dataset.type = type;
        btn.style.cssText = `
            background: ${color}30;
            border: 1px solid ${color};
            border-radius: 3px;
            padding: 3px 10px;
            font-size: 12px;
            font-weight: 600;
            color: ${color};
            cursor: grab;
            user-select: none;
            min-width: 35px;
            text-align: center;
            pointer-events: auto;
            touch-action: none;
        `;
        btn.textContent = label;

        // Start drag on pointer down
        btn.addEventListener('pointerdown', this.onPointerDown);

        return btn;
    }

    /**
     * Create draggable marker that appears when dragging
     */
    createDragMarker(label, color, type, initialPrice) {
        const marker = document.createElement('div');
        marker.className = `price-marker ${type}-marker`;
        marker.dataset.type = type; // Identify drag target

        marker.style.cssText = `
            position: fixed;
            z-index: 10001; /* Above panel */
            display: flex;
            align-items: center;
            gap: 8px;
            background: ${color};
            border: 2px solid ${color};
            border-radius: 4px;
            padding: 6px 12px;
            font-size: 13px;
            font-weight: 700;
            color: white;
            cursor: grab;
            user-select: none;
            box-shadow: 0 2px 8px rgba(0,0,0,0.4);
            pointer-events: auto;
            touch-action: none;
            will-change: transform;
        `;

        // Inner HTML structure with projections
        marker.innerHTML = `
            <span style="opacity:0.7; cursor: grab; font-size:14px;">⋮⋮</span>
            <span style="font-size:12px;">${label}</span>
            <span class="price-val" style="font-size:13px; font-weight:700;">$${initialPrice.toFixed(2)}</span>
            <div class="projections" style="display:flex; flex-direction:column; font-size:11px; font-weight:500; margin-left:8px; padding-left:8px; border-left:1px solid rgba(255,255,255,0.3); line-height:1.3;">
                <span class="opt-price">Opt: --</span>
                <span class="pnl-val">P&L: --</span>
            </div>
            <button class="close-marker" style="margin-left:6px; background:none; border:none; color:white; cursor:pointer; opacity:0.7; font-size:18px; line-height:1;">×</button>
        `;

        // Add close handler
        const closeBtn = marker.querySelector('.close-marker');
        closeBtn.addEventListener('pointerdown', (e) => {
            e.stopPropagation(); // Prevent drag start
            this.removeMarker(type);
        });

        // Add drag handler to the marker itself (for re-dragging)
        marker.addEventListener('pointerdown', this.onPointerDown);

        return marker;
    }

    /**
     * Visual-only drag on the Buy grip. Follows the cursor while held but
     * makes no controller, state, or order changes. On release the ghost is
     * removed and the panel snaps back to the live price line.
     */
    handleBuyGripDown(e) {
        if (e.button !== 0) return;

        const src = e.currentTarget;
        const startX = e.clientX;
        const startY = e.clientY;
        const DRAG_THRESHOLD_PX = 4;
        let dragging = false;
        let lastPrice = null;

        const panel = this.panelContainer;
        const origRight = panel.style.right;

        const onMove = (ev) => {
            const dx = ev.clientX - startX;
            const dy = ev.clientY - startY;
            if (!dragging && (dx * dx + dy * dy) >= DRAG_THRESHOLD_PX * DRAG_THRESHOLD_PX) {
                dragging = true;
                src.setPointerCapture?.(e.pointerId);
                src.style.cursor = 'grabbing';
                if (this.buyButton) this.buyButton.style.cursor = 'grabbing';
                ev.preventDefault?.();
            }
            if (!dragging) return;

            const panelRect = panel.getBoundingClientRect();
            panel.style.top = `${ev.clientY - panelRect.height / 2}px`;
            panel.style.right = origRight;

            const price = this.clientYToPrice(ev.clientY);
            if (Number.isFinite(price)) {
                lastPrice = price;
                if (this.priceDisplay) this.priceDisplay.textContent = `$${price.toFixed(2)}`;
            }
        };

        const onUp = (ev) => {
            document.removeEventListener('pointermove', onMove);
            document.removeEventListener('pointerup', onUp);
            try { src.releasePointerCapture?.(ev.pointerId); } catch (_) {}
            src.style.cursor = 'grab';
            if (this.buyButton) this.buyButton.style.cursor = 'grab';

            if (dragging) {
                this._buySuppressClick = true;
                // Decide between limit-trigger and revert-to-market based on
                // how far the drop is from the live price. Snap-back threshold
                // is 0.1% of current price (min $0.05) so tiny accidental
                // moves still revert to market.
                const live = Number(this.currentPrice) || 0;
                const snapBack = Math.max(0.05, live * 0.001);
                if (Number.isFinite(lastPrice) && Math.abs(lastPrice - live) > snapBack) {
                    this.setEntryTrigger(lastPrice);
                } else {
                    this.clearEntryTrigger();
                }
            }
        };

        document.addEventListener('pointermove', onMove);
        document.addEventListener('pointerup', onUp);
    }

    /**
     * Activate limit-trigger entry at `price`. Pins the Buy pill there,
     * flips the side panel into limit-order mode with the trigger pre-filled,
     * and draws a dashed entry line on the chart.
     */
    setEntryTrigger(price) {
        this.entryTriggerActive = true;
        this.entryTriggerPrice = price;

        // Sync side panel: order type → limit + trigger price.
        const orderTypeEl = document.getElementById('orderType');
        if (orderTypeEl) {
            orderTypeEl.value = 'limit';
            orderTypeEl.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const limitPriceEl = document.getElementById('limitPrice');
        if (limitPriceEl) {
            limitPriceEl.value = price.toFixed(2);
            limitPriceEl.dispatchEvent(new Event('input', { bubbles: true }));
        }

        // Pin the panel to the trigger Y and update its label.
        if (this.priceDisplay) this.priceDisplay.textContent = `$${price.toFixed(2)}`;
        this.updatePanelPosition();

        // Draw entry price line (dashed, neutral blue).
        this.updateEntryPriceLine(price);
    }

    /**
     * Revert to market order (clears trigger and the entry chart line).
     */
    clearEntryTrigger() {
        const wasActive = this.entryTriggerActive;
        this.entryTriggerActive = false;
        this.entryTriggerPrice = null;

        if (wasActive) {
            const orderTypeEl = document.getElementById('orderType');
            if (orderTypeEl && orderTypeEl.value !== 'market') {
                orderTypeEl.value = 'market';
                orderTypeEl.dispatchEvent(new Event('change', { bubbles: true }));
            }
            const limitPriceEl = document.getElementById('limitPrice');
            if (limitPriceEl) {
                limitPriceEl.value = '';
                limitPriceEl.dispatchEvent(new Event('input', { bubbles: true }));
            }
        }

        // Remove entry chart line.
        const series = this.chartManager.getSeries();
        if (series && this.priceLines.entry) {
            try { series.removePriceLine(this.priceLines.entry); } catch (e) {}
            this.priceLines.entry = null;
        }

        // Snap panel back to the live price.
        this.updatePanelPosition();
    }

    updateEntryPriceLine(price) {
        const series = this.chartManager.getSeries();
        if (!series) return;
        try {
            if (this.priceLines.entry) {
                this.priceLines.entry.applyOptions({ price, color: '#3b82f6', lineWidth: 2, lineStyle: 2, title: 'ENTRY' });
                return;
            }
            this.priceLines.entry = series.createPriceLine({
                price,
                color: '#3b82f6',
                lineWidth: 2,
                lineStyle: 2,
                axisLabelVisible: true,
                title: 'ENTRY'
            });
        } catch (e) {}
    }

    /**
     * Handle Pointer Down - Start Dragging
     */
    handlePointerDown(e) {
        if (!this.isTradingReady()) {
            window.Toast?.warning('Trading controls are still loading', 2000);
            return;
        }

        // Only left click
        if (e.button !== 0) return;

        e.preventDefault();

        const target = e.currentTarget;
        const type = target.dataset.type; // 'sl' or 'tp'

        if (!type) return;

        this.isDragging = true;
        this.dragTarget = type;
        this.dragStartY = e.clientY;

        // Mirror drag start into the controller (single source of truth).
        const kind = type === 'sl' ? 'stop' : 'target';
        this.controller?.startDrag?.(kind, this.currentPrice);

        // Capture pointer for seamless tracking
        target.setPointerCapture(e.pointerId);
        target.style.cursor = 'grabbing';

        // Add global move/up listeners (backup for capture)
        document.addEventListener('pointermove', this.onPointerMove);
        document.addEventListener('pointerup', this.onPointerUp);

        // Cache chart metrics for initial positioning. Price is still resolved
        // through the series transform during moves so scale changes do not drift.
        this.chartRect = this.chartManager.container.getBoundingClientRect();

        // Determine start price and which element acts as the visual drag target.
        // Three entry points:
        //  1) Inline panel button (.pl-btn) — start a fresh drag at current price.
        //  2) Existing marker pill (.price-marker) — continue editing that marker.
        //  3) Chart-line hit-area overlay (.order-line-hitarea) — drag the LINE,
        //     mirror onto the existing marker pill (never style the hit-area).
        const fromHitArea = target.classList.contains('order-line-hitarea');
        const fromPanelBtn = target.classList.contains('pl-btn');

        if (fromPanelBtn) {
            this.dragStartPrice = this.currentPrice;

            // Create marker immediately at start position
            if (type === 'sl') {
                if (!this.slMarker) {
                    this.slMarker = this.createDragMarker('SL', '#f6465d', 'sl', this.currentPrice);
                    document.body.appendChild(this.slMarker);
                }
                this.dragTargetEl = this.slMarker;
                this.slButton.style.display = 'none'; // Hide button
            } else {
                if (!this.tpMarker) {
                    this.tpMarker = this.createDragMarker('TP', '#0ecb81', 'tp', this.currentPrice);
                    document.body.appendChild(this.tpMarker);
                }
                this.dragTargetEl = this.tpMarker;
                this.tpButton.style.display = 'none'; // Hide button
            }

            // Position marker initially
            this.updateMarkerVisuals(this.currentPrice);

        } else if (fromHitArea) {
            // Drag started on the on-chart line itself. The hit-area is just an
            // event surface — never let updateMarkerVisuals restyle it (that's
            // what produced the wide colored bands). Always route the drag onto
            // the existing marker pill, creating one if it doesn't exist yet.
            const startPrice = type === 'sl' ? this.slPrice : this.tpPrice;
            this.dragStartPrice = Number.isFinite(startPrice) ? startPrice : this.currentPrice;

            if (type === 'sl') {
                if (!this.slMarker) {
                    this.slMarker = this.createDragMarker('SL', '#f6465d', 'sl', this.dragStartPrice);
                    document.body.appendChild(this.slMarker);
                    this.slButton && (this.slButton.style.display = 'none');
                }
                this.dragTargetEl = this.slMarker;
            } else {
                if (!this.tpMarker) {
                    this.tpMarker = this.createDragMarker('TP', '#0ecb81', 'tp', this.dragStartPrice);
                    document.body.appendChild(this.tpMarker);
                    this.tpButton && (this.tpButton.style.display = 'none');
                }
                this.dragTargetEl = this.tpMarker;
            }

            this.updateMarkerVisuals(this.dragStartPrice);

        } else {
            // Started from existing marker pill
            this.dragTargetEl = target;
            this.dragStartPrice = type === 'sl' ? this.slPrice : this.tpPrice;
        }

        console.log(`Started dragging ${type} from ${this.dragStartPrice}`);
    }

    /**
     * Handle Pointer Move - Dragging Logic
     */
    handlePointerMove(e) {
        if (!this.isDragging) return;

        // Use requestAnimationFrame for smooth visuals
        if (this.rafId) return;

        this.rafId = requestAnimationFrame(() => {
            const newPrice = this.clientYToPrice(e.clientY);
            if (newPrice === null || !Number.isFinite(newPrice)) {
                this.rafId = null;
                return;
            }

            // Update state
            if (this.dragTarget === 'sl') {
                this.slPrice = newPrice;
            } else {
                this.tpPrice = newPrice;
            }

            // Mirror move into the controller so external observers (tests,
            // future tooling) see the same drag stream.
            this.controller?.moveDrag?.(newPrice);

            // Update Visuals
            this.updateMarkerVisuals(newPrice);

            this.rafId = null;
        });
    }

    /**
     * Update Marker Position and Style
     */
    updateMarkerVisuals(price) {
        if (!this.dragTargetEl) return;

        this.chartRect = this.chartManager.container.getBoundingClientRect();

        const y = this.priceToY(price);
        // Get type from element dataset to ensure logic is correct even when not actively dragging (e.g. resize)
        const type = this.dragTargetEl.dataset.type;

        if (y !== null && !isNaN(y)) {
            const absoluteY = this.chartRect.top + y;
            const rightOffset = window.innerWidth - this.chartRect.right + 65; // Align with panel

            this.dragTargetEl.style.top = `${absoluteY - 14}px`;
            this.dragTargetEl.style.right = `${rightOffset}px`;

            // Update price text
            const priceVal = this.dragTargetEl.querySelector('.price-val');
            if (priceVal) priceVal.textContent = `$${price.toFixed(2)}`;

            // Validation
            const contractType = this.tradingPanel?.contractType || 'CALL';
            const isValid = this.validatePrice(type, price, contractType); // Use derived type, not dragTarget

            const color = type === 'sl' ? '#f6465d' : '#0ecb81';

            if (!isValid) {
                this.dragTargetEl.style.background = '#ff4444';
                this.dragTargetEl.style.opacity = '0.8';
            } else {
                this.dragTargetEl.style.background = color;
                this.dragTargetEl.style.opacity = '1';
            }

            // Update Price Line on Chart
            this.updateChartPriceLine(type, price, isValid);

            // Update projections (explicit call to ensure check loop)
            this.updateProjections(price, type);
        }
    }

    /**
     * Calculate and display Black-Scholes projections
     */
    updateProjections(targetPrice, type) {
        if (!this.bsCalculator) return;

        // Resolve type and marker if not passed
        if (!type) type = this.dragTarget;
        if (!type && this.dragTargetEl) type = this.dragTargetEl.dataset.type;

        let marker = this.dragTargetEl;
        // If updating from resize/scroll, dragTargetEl might not be set for this specific marker
        if (!marker || marker.dataset.type !== type) {
            marker = type === 'sl' ? this.slMarker : this.tpMarker;
        }

        if (!marker || !type) return;

        // Get constants from TradingPanel
        const tp = this.tradingPanel;
        if (!tp) return;

        const strike = tp.selectedStrike;
        const dte = tp.dte;
        const contractType = tp.contractType;

        const quote = tp.lastQuote || {};
        const quotePrice = Number(quote.mark || quote.last || 0);
        const hasRealQuote = quote.success && Number.isFinite(quotePrice) && quotePrice > 0;

        // Get IV from last quote or use default
        let iv = 0.3; // Default 30%
        if (quote.iv) iv = quote.iv;

        // Calculate Time to Expiry in Years
        const timeToExpiry = (dte === 0 ? 0.5 : dte) / 365.0; // 0DTE treated as half day remaining for safety

        // Calculate Projected Option Price
        const projectedOptPrice = this.bsCalculator.estimatePriceAtTarget(
            targetPrice,
            strike,
            timeToExpiry,
            0.045, // Risk free
            iv,
            contractType
        );

        // Update UI
        const optPriceEl = marker.querySelector('.opt-price');
        const pnlValEl = marker.querySelector('.pnl-val');

        if (optPriceEl) {
            optPriceEl.textContent = Number.isFinite(projectedOptPrice) && projectedOptPrice >= 0
                ? `Opt: $${projectedOptPrice.toFixed(2)}`
                : 'Opt: --';
        }

        if (pnlValEl) {
            if (!hasRealQuote || !Number.isFinite(projectedOptPrice) || projectedOptPrice < 0) {
                pnlValEl.textContent = 'P&L: --';
                pnlValEl.style.color = '#d6d9df';
                pnlValEl.style.fontWeight = '600';
                return;
            }

            // P&L must be computed against a SAME-MODEL baseline, not the
            // broker's bid/ask mid. Black-Scholes theoretical price can drift
            // from market mark (different IV, skew, time-of-day spread), so
            // (BS_at_target - market_mark) gives nonsense signs when the
            // baseline disagrees by more than the projected move — e.g. an SL
            // on a long call showing "+$37" because BS> mark even at the lower
            // underlying. Fix: anchor the baseline to BS at the CURRENT
            // underlying so both sides of the diff come from the same model.
            const currentUnderlying = Number(this.currentPrice) || 0;
            const baselineOptPrice = (currentUnderlying > 0)
                ? this.bsCalculator.estimatePriceAtTarget(
                    currentUnderlying, strike, timeToExpiry, 0.045, iv, contractType,
                  )
                : quotePrice;

            // Position sizing still uses the real entry cost (market mark),
            // not the model price — that's the actual dollars you'd pay.
            const contracts = Math.floor(tp.positionSize / (quotePrice * 100));
            const pnl = (projectedOptPrice - baselineOptPrice) * contracts * 100;
            const prefix = pnl >= 0 ? '+' : '';
            pnlValEl.textContent = `${prefix}$${pnl.toFixed(0)}`;
            pnlValEl.style.color = pnl >= 0 ? '#ccffcc' : '#ffcccc'; // High contrast
            pnlValEl.style.fontWeight = 'bold';
        }
    }

    /**
     * Handle Pointer Up - Stop Dragging
     */
    handlePointerUp(e) {
        if (!this.isDragging) return;

        this.isDragging = false;

        // Release listeners
        document.removeEventListener('pointermove', this.onPointerMove);
        document.removeEventListener('pointerup', this.onPointerUp);

        if (e.target.releasePointerCapture) {
            e.target.releasePointerCapture(e.pointerId);
            e.target.style.cursor = 'grab';
        }

        // Final Validation
        const contractType = this.tradingPanel?.contractType || 'CALL';
        const price = this.dragTarget === 'sl' ? this.slPrice : this.tpPrice;
        const isValid = this.validatePrice(this.dragTarget, price, contractType);

        if (!isValid) {
            // Invalid position: Remove marker, restore panel button
            this.removeMarker(this.dragTarget);
            window.Toast?.error(`${this.dragTarget.toUpperCase()} invalid for ${contractType}`, 2000);
        } else {
            // Valid position: Keep marker, Update Inputs
            if (this.dragTarget === 'sl') {
                this.slActive = true;
                const slInput = document.getElementById('stopLoss');
                if (slInput) slInput.value = price.toFixed(2);
            } else {
                this.tpActive = true;
                const tpInput = document.getElementById('takeProfit');
                if (tpInput) tpInput.value = price.toFixed(2);
            }
        }

        this.dragTarget = null;
        this.dragTargetEl = null;

        // Settle drag in the controller.
        this.controller?.endDrag?.();

        // Force one last update to ensure visuals are consistent
        this.updatePositions();
    }

    /**
     * Remove marker and reset state
     */
    removeMarker(type) {
        if (type === 'sl') {
            this.removeElement(this.slMarker);
            this.slMarker = null;
            this.slActive = false;
            this.slButton.style.display = 'block'; // Show panel button

            // Clear chart line
            if (this.priceLines.sl) {
                this.chartManager.getSeries()?.removePriceLine(this.priceLines.sl);
                this.priceLines.sl = null;
            }
            this.removeLineHitArea('sl');

            // Clear input
            const slInput = document.getElementById('stopLoss');
            if (slInput) slInput.value = '';

        } else {
            this.removeElement(this.tpMarker);
            this.tpMarker = null;
            this.tpActive = false;
            this.tpButton.style.display = 'block'; // Show panel button

            // Clear chart line
            if (this.priceLines.tp) {
                this.chartManager.getSeries()?.removePriceLine(this.priceLines.tp);
                this.priceLines.tp = null;
            }
            this.removeLineHitArea('tp');

            // Clear input
            const tpInput = document.getElementById('takeProfit');
            if (tpInput) tpInput.value = '';
        }
    }

    /**
     * Validate SL/TP price
     */
    validatePrice(type, price, contractType) {
        if (type === 'sl') {
            return contractType === 'CALL' ? price < this.currentPrice : price > this.currentPrice;
        } else if (type === 'tp') {
            return contractType === 'CALL' ? price > this.currentPrice : price < this.currentPrice;
        }
        return true;
    }

    updatePanelPosition() {
        if (!this.panelContainer || !this.currentPrice) return;

        // When a limit-trigger is active, anchor the panel to the trigger
        // price; otherwise it tracks the live price line.
        const anchorPrice = (this.entryTriggerActive && Number.isFinite(this.entryTriggerPrice))
            ? this.entryTriggerPrice
            : this.currentPrice;

        const chartRect = this.chartManager.container.getBoundingClientRect();
        const y = this.priceToY(anchorPrice);

        if (y !== null && !isNaN(y)) {
            const absoluteY = chartRect.top + y;
            const rightOffset = window.innerWidth - chartRect.right + 65;

            this.panelContainer.style.top = `${absoluteY - 14}px`;
            this.panelContainer.style.right = `${rightOffset}px`;
        }

        if (this.priceDisplay) {
            this.priceDisplay.textContent = `$${anchorPrice.toFixed(2)}`;
        }

        // Keep the entry chart line in sync when active.
        if (this.entryTriggerActive && Number.isFinite(this.entryTriggerPrice)) {
            this.updateEntryPriceLine(this.entryTriggerPrice);
        }

        this.syncTradingReadiness();
    }

    isTradingReady() {
        // Prefer the controller's canSubmit() as the single source of truth.
        if (this.controller && typeof this.controller.canSubmit === 'function') {
            return this.controller.canSubmit() === true;
        }
        // Legacy fallback if controller is not wired.
        // 0 DTE is a valid trading case (same-day SPY/QQQ/IWM expirations).
        // `tp.isReady` already gates against the uninitialized state.
        const tp = this.tradingPanel;
        return !!(tp && tp.isReady && tp.symbolConfig && tp.selectedStrike > 0 && Number.isFinite(tp.dte) && tp.dte >= 0);
    }

    syncTradingReadiness() {
        const ready = this.isTradingReady();

        if (this.buyButton) {
            this.buyButton.disabled = !ready;
            this.buyButton.style.opacity = ready ? '1' : '0.45';
            this.buyButton.style.cursor = ready ? 'pointer' : 'not-allowed';
            this.buyButton.title = ready ? 'Place order' : 'Trading controls are still loading';
        }

        [this.slButton, this.tpButton].forEach((button) => {
            if (!button) return;
            button.style.opacity = ready ? '1' : '0.45';
            button.style.cursor = ready ? 'grab' : 'not-allowed';
            button.style.pointerEvents = ready ? 'auto' : 'none';
            button.title = ready ? '' : 'Trading controls are still loading';
        });
    }

    updatePositions() {
        if (!this.enabled) return;

        // Update Panel
        this.updatePanelPosition();

        // Update Markers (Sticky behavior)
        if (this.slActive && this.slMarker && this.slPrice) {
            this.chartRect = this.chartManager.container.getBoundingClientRect();
            this.dragTargetEl = this.slMarker;
            this.updateMarkerVisuals(this.slPrice);
        }
        if (this.tpActive && this.tpMarker && this.tpPrice) {
            this.chartRect = this.chartManager.container.getBoundingClientRect();
            this.dragTargetEl = this.tpMarker;
            this.updateMarkerVisuals(this.tpPrice);
        }

        // Keep line hit-areas anchored to their lines after scroll/zoom/resize.
        if (this.priceLines.sl && this.slPrice) this.updateLineHitArea('sl', this.slPrice);
        if (this.priceLines.tp && this.tpPrice) this.updateLineHitArea('tp', this.tpPrice);
        // Don't reset to null here, otherwise updateMarkerVisuals can't use it.
        // Actually, updateMarkerVisuals uses this.dragTargetEl, which I just set above.
        // So that pattern works.
        this.dragTargetEl = null; // Clean up after update
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

    clientYToPrice(clientY) {
        const series = this.chartManager.getSeries();
        if (!series) return null;
        const chartRect = this.chartManager.container.getBoundingClientRect();
        const y = clientY - chartRect.top;

        try {
            return series.coordinateToPrice(y);
        } catch (e) {
            return null;
        }
    }

    updateCurrentPrice() {
        const series = this.chartManager.getSeries();
        if (!series) return;
        try {
            const data = series.data();
            if (data && data.length > 0) {
                this.currentPrice = data[data.length - 1].close;
                this.updatePanelPosition();
            }
        } catch (e) { }
    }

    updateChartPriceLine(type, price, isValid) {
        const series = this.chartManager.getSeries();
        if (!series) return;

        const colors = {
            sl: isValid ? '#f6465d' : '#ff0000',
            tp: isValid ? '#0ecb81' : '#ff0000'
        };

        try {
            if (this.priceLines[type]) {
                this.priceLines[type].applyOptions({
                    price: price,
                    color: colors[type],
                    lineWidth: 3,
                    lineStyle: isValid ? 2 : 3,
                    title: type.toUpperCase()
                });
                this.updateLineHitArea(type, price);
                return;
            }

            this.priceLines[type] = series.createPriceLine({
                price: price,
                color: colors[type],
                lineWidth: 3,
                lineStyle: isValid ? 2 : 3, // DASHED valid : LargeDashed invalid
                axisLabelVisible: true,
                title: type.toUpperCase()
            });
            this.ensureLineHitArea(type);
            this.updateLineHitArea(type, price);
        } catch (e) { }
    }

    removePriceLines() {
        const series = this.chartManager.getSeries();
        if (!series) return;
        for (const type in this.priceLines) {
            if (this.priceLines[type]) {
                try { series.removePriceLine(this.priceLines[type]); } catch (e) { }
                this.priceLines[type] = null;
            }
            this.removeLineHitArea(type);
        }
    }

    /**
     * Create an invisible chart-overlay div for the given line type so the user
     * can grab and drag the line itself (TradingView-style), not just the inline
     * panel button. The overlay reuses the same pointerdown handler.
     */
    ensureLineHitArea(type) {
        if (this.lineHitAreas[type]) return this.lineHitAreas[type];
        const hit = document.createElement('div');
        hit.className = `order-line-hitarea ${type}-hitarea`;
        hit.dataset.type = type;
        hit.style.cssText = `
            position: fixed;
            left: 0;
            height: 14px;
            z-index: 9998;
            background: transparent;
            cursor: ns-resize;
            pointer-events: auto;
            touch-action: none;
            user-select: none;
        `;
        hit.addEventListener('pointerdown', this.onPointerDown);
        document.body.appendChild(hit);
        this.lineHitAreas[type] = hit;
        return hit;
    }

    /**
     * Position the hit-area overlay to match the on-chart price line for `type`.
     * The container element (#chartView) can report a 0×0 rect even though the
     * inner chart canvas is laid out at full size — fall back to the first
     * child for width/left in that case.
     */
    updateLineHitArea(type, price) {
        const hit = this.lineHitAreas[type];
        if (!hit) return;
        const container = this.chartManager.container;
        let rect = container.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) {
            const inner = container.firstElementChild;
            if (inner) rect = inner.getBoundingClientRect();
        }
        const y = this.priceToY(price);
        if (y === null || isNaN(y) || rect.width === 0) {
            hit.style.display = 'none';
            return;
        }
        hit.style.display = 'block';
        hit.style.top = `${rect.top + y - 7}px`;
        hit.style.left = `${rect.left}px`;
        hit.style.width = `${rect.width}px`;
    }

    removeLineHitArea(type) {
        const hit = this.lineHitAreas[type];
        if (!hit) return;
        hit.removeEventListener('pointerdown', this.onPointerDown);
        this.removeElement(hit);
        this.lineHitAreas[type] = null;
    }

    executeOrder() {
        if (!this.isTradingReady()) {
            window.Toast?.warning('Trading controls are still loading', 2000);
            return;
        }

        const executeBtn = document.getElementById('executeBtn');
        if (executeBtn) {
            // Log current DTE state for debugging sync issues
            const currentDte = this.tradingPanel?.dte;
            console.log('OrderPanelOnChart executing order with TradingPanel DTE:', currentDte);

            // Verify SL/TP prices if set
            if (this.slPrice) {
                console.log('  SL Price:', this.slPrice);
            }
            if (this.tpPrice) {
                console.log('  TP Price:', this.tpPrice);
            }

            executeBtn.click();
        }
    }
}

// Make globally available
window.OrderPanelOnChart = OrderPanelOnChart;
