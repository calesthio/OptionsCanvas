/**
 * TradingPanel - Manages the trading panel UI and order placement logic
 * Handles strike selection, DTE, position sizing, and order execution
 */

class TradingPanel {
    constructor() {
        this.contractType = 'CALL';
        this.strikeOffset = 0;
        this.currentSymbol = 'SPY';
        this.currentPrice = 0;
        this.atmStrike = 0;
        this.selectedStrike = 0;
        this.dte = 0;
        this.positionSize = 1000;
        this.symbolConfig = null;
        // Actual strike list from the broker for current (symbol, DTE, type).
        // Authoritative — replaces increment-math snapping. Without this,
        // symbols like MSTR (whose weekly strike grid is $2.50 in some
        // expirations and irregular in others) end up trying to trade
        // strikes the broker doesn't actually list, and orders fail at
        // submission with "Strike $X not available".
        this.validStrikes = [];
        this.validStrikesKey = null;   // `${symbol}_${dte}_${type}`
        this.isReady = false;

        this.initializeElements();
        this.attachEventListeners();
        this.updateUI();
    }

    /**
     * Initialize DOM element references
     */
    initializeElements() {
        // Contract type tabs
        this.callTab = document.querySelector('[data-type="CALL"]');
        this.putTab = document.querySelector('[data-type="PUT"]');

        // Strike controls
        this.strikeDownBtn = document.getElementById('strikeDown');
        this.strikeUpBtn = document.getElementById('strikeUp');
        this.strikePriceEl = document.getElementById('strikePrice');
        this.strikeOffsetEl = document.getElementById('strikeOffset');

        // DTE selector
        this.dteSelect = document.getElementById('dteSelect');

        // Position size
        this.positionSizeInput = document.getElementById('positionSize');
        this.contractsQtyEl = document.getElementById('contractsQty');
        this.optionPremiumEl = document.getElementById('optionPremium');

        // SL/TP
        this.stopLossInput = document.getElementById('stopLoss');
        this.takeProfitInput = document.getElementById('takeProfit');

        // Order type
        this.orderTypeSelect = document.getElementById('orderType');
        this.limitPriceSection = document.getElementById('limitPriceSection');
        this.limitPriceInput = document.getElementById('limitPrice');
        this.triggerPriceLabel = document.getElementById('triggerPriceLabel');

        // Order execution type (radio buttons)
        this.orderExecutionRadios = document.querySelectorAll('input[name="orderExecution"]');

        // Order preview
        this.previewContract = document.getElementById('previewContract');
        this.previewQty = document.getElementById('previewQty');
        this.previewCost = document.getElementById('previewCost');

        // Execute button
        this.executeBtn = document.getElementById('executeBtn');
        this.executeBtnText = this.executeBtn.querySelector('.btn-text');

        // Quick actions
        this.closeAllBtn = document.getElementById('closeAllBtn');
    }

    /**
     * Attach event listeners
     */
    attachEventListeners() {
        // Contract type tabs
        this.callTab?.addEventListener('click', () => this.setContractType('CALL'));
        this.putTab?.addEventListener('click', () => this.setContractType('PUT'));

        // Strike adjustment
        this.strikeDownBtn?.addEventListener('click', () => this.adjustStrike(-1));
        this.strikeUpBtn?.addEventListener('click', () => this.adjustStrike(1));

        // DTE change
        this.dteSelect?.addEventListener('change', (e) => {
            this.dte = parseInt(e.target.value);
            // Strike grid varies by expiration — refresh actual strikes
            // before the next preview so the selected strike snaps to a
            // value the broker will accept.
            this.loadValidStrikes().then(() => this.updateOrderPreview());
            // Emit event to notify other components about DTE change
            window.EventBus?.emit('trading_panel:dte_changed', { dte: this.dte });
        });

        // Position size change
        this.positionSizeInput?.addEventListener('input', (e) => {
            this.positionSize = parseFloat(e.target.value) || 0;
            this.updateOrderPreview();
        });

        // Order type change
        this.orderTypeSelect?.addEventListener('change', (e) => {
            const isLimit = e.target.value === 'limit';
            if (this.limitPriceSection) {
                this.limitPriceSection.style.display = isLimit ? 'block' : 'none';
            }

            // Update explanation text
            const orderTypeExplanation = document.getElementById('orderTypeExplanation');
            if (orderTypeExplanation) {
                const explanations = {
                    'market': 'Places order immediately at current market conditions',
                    'limit': 'Waits for underlying price to reach trigger level before placing order'
                };
                orderTypeExplanation.textContent = explanations[e.target.value] || '';
            }
        });

        // Order execution type change (radio buttons - no explanation needed as it's in the UI)
        this.orderExecutionRadios?.forEach(radio => {
            radio.addEventListener('change', () => {
                // Just for logging/debugging
                console.log('Order execution changed to:', radio.value);
            });
        });

        // Execute button
        this.executeBtn?.addEventListener('click', () => this.executeOrder());

        // Close all positions
        this.closeAllBtn?.addEventListener('click', () => this.closeAllPositions());

        // Listen for symbol changes.
        //
        // We use an AbortController per "symbol context" so that any in-flight
        // requests from the previous symbol (getSymbolConfig, getSymbolContracts,
        // getOptionQuote) are cancelled at the network layer when the user
        // switches symbols. Without this, a slow response for AAPL could land
        // after the user has already moved to MRVL and overwrite the panel
        // state with stale data — which can cause real money to flow into
        // the wrong contract if they click Buy in that window. See the
        // industry pattern: AbortController + correlation-ID guards. The
        // controller is paired with a `requestedSymbol` check inside each
        // async function for belt-and-suspenders (some operations may slip
        // past the abort if it fires between `await` and `.then`).
        this._symbolAborter = null;
        window.EventBus.on('chart:symbol_loaded', (data) => {
            // Cancel everything in-flight for the previous symbol
            this._symbolAborter?.abort();
            this._symbolAborter = new AbortController();

            this.isReady = false;
            this.currentSymbol = data.symbol;
            window.ChartTradingController?.setTradingSnapshot(this.getTradingSnapshot());
            this.loadSymbolConfig();
            this.updateTriggerPriceLabel();
        });

        // Listen for bar updates to update current price
        window.EventBus.on('chart:bar_update', (data) => {
            if (data.symbol === this.currentSymbol) {
                this.currentPrice = data.bar.close;
                this.calculateStrike();
            }
        });
    }

    /**
     * Set contract type (CALL or PUT)
     * @param {string} type - 'CALL' or 'PUT'
     */
    setContractType(type) {
        this.contractType = type;

        // Update tab UI
        this.callTab?.classList.toggle('active', type === 'CALL');
        this.putTab?.classList.toggle('active', type === 'PUT');

        // Update execute button
        if (this.executeBtn) {
            this.executeBtn.classList.toggle('put', type === 'PUT');
            this.executeBtnText.textContent = `Buy ${type}`;
        }

        // PUT and CALL chains can have slightly different strike grids on
        // some symbols (rare but real), so re-fetch the strike list whenever
        // the contract type changes.
        this.loadValidStrikes().then(() => this.updateOrderPreview());
    }

    /**
     * Adjust strike offset by one position in the broker's actual strike
     * list (when we have it). Falls back to increment-math when the strike
     * list hasn't loaded yet — keeps the UI responsive while still snapping
     * to a real strike once the broker responds.
     * @param {number} direction - -1 for down, +1 for up
     */
    adjustStrike(direction) {
        if (!this.symbolConfig) {
            console.warn('Symbol config not loaded');
            return;
        }

        this.strikeOffset += direction;

        if (this.validStrikes && this.validStrikes.length > 0) {
            // ATM index = strike in the list closest to current price.
            const atmIdx = this._nearestStrikeIndex(this.currentPrice);
            const targetIdx = Math.min(
                this.validStrikes.length - 1,
                Math.max(0, atmIdx + this.strikeOffset)
            );
            this.selectedStrike = this.validStrikes[targetIdx];
        } else {
            // Fallback only — increment math, won't always land on a real strike.
            const increment = this.symbolConfig.strike_increment;
            this.selectedStrike = this.atmStrike + (this.strikeOffset * increment);
        }

        // Update UI
        this.strikePriceEl.textContent = `$${this.selectedStrike.toFixed(2)}`;
        this.strikeOffsetEl.querySelector('span').textContent =
            `Offset: ${this.strikeOffset >= 0 ? '+' : ''}${this.strikeOffset}`;

        this.updateOrderPreview();
    }

    /**
     * Find the index of the strike closest to `price` in this.validStrikes.
     * Linear scan is fine — strike lists are O(100) entries.
     */
    _nearestStrikeIndex(price) {
        if (!this.validStrikes || this.validStrikes.length === 0) return -1;
        let bestIdx = 0;
        let bestDiff = Math.abs(this.validStrikes[0] - price);
        for (let i = 1; i < this.validStrikes.length; i++) {
            const d = Math.abs(this.validStrikes[i] - price);
            if (d < bestDiff) {
                bestDiff = d;
                bestIdx = i;
            }
        }
        return bestIdx;
    }

    /**
     * Compute the selected strike from current price + offset.
     *
     * Preferred path: snap to nearest strike in the broker's actual list
     * (this.validStrikes), then step by index for the offset. This is the
     * ONLY correct way for symbols whose strike grid varies by expiration
     * (MSTR weeklies, low-priced names with mixed grids).
     *
     * Fallback path: increment math, used only when the strike list hasn't
     * arrived yet. The fallback may land on a non-existent strike; the
     * subsequent loadValidStrikes() call re-snaps it to a real one.
     */
    calculateStrike() {
        if (!this.symbolConfig || !this.currentPrice) {
            return;
        }

        if (this.validStrikes && this.validStrikes.length > 0) {
            const atmIdx = this._nearestStrikeIndex(this.currentPrice);
            this.atmStrike = this.validStrikes[atmIdx];
            const targetIdx = Math.min(
                this.validStrikes.length - 1,
                Math.max(0, atmIdx + this.strikeOffset)
            );
            this.selectedStrike = this.validStrikes[targetIdx];
        } else {
            const increment = this.symbolConfig.strike_increment;
            this.atmStrike = Math.round(this.currentPrice / increment) * increment;
            this.selectedStrike = this.atmStrike + (this.strikeOffset * increment);
        }

        // Update UI
        this.strikePriceEl.textContent = `$${this.selectedStrike.toFixed(2)}`;
    }

    /**
     * Fetch the broker's actual strike list for (currentSymbol, dte,
     * contractType) and re-snap the selected strike to a real value.
     * Idempotent + cancellable via this._symbolAborter.
     */
    async loadValidStrikes() {
        if (!this.currentSymbol || this.dte === undefined || this.dte === null) return;
        const type = (this.contractType || 'CALL').toLowerCase();
        const key = `${this.currentSymbol}_${this.dte}_${type}`;
        const signal = this._symbolAborter?.signal;
        const requestedSymbol = this.currentSymbol;
        const requestedDte = this.dte;
        const requestedType = type;

        try {
            const resp = await window.ApiClient.getSymbolStrikes(
                requestedSymbol, requestedDte, requestedType, { signal }
            );
            // Correlation-ID guard — same pattern as loadValidContracts.
            if (requestedSymbol !== this.currentSymbol ||
                requestedDte !== this.dte ||
                requestedType !== (this.contractType || 'CALL').toLowerCase()) {
                console.log(`loadValidStrikes: stale (${key}, now ${this.currentSymbol}_${this.dte}_${(this.contractType||'').toLowerCase()})`);
                return;
            }
            this.validStrikes = Array.isArray(resp?.strikes) ? resp.strikes : [];
            this.validStrikesKey = key;
            console.log(`Strike list for ${key}: ${this.validStrikes.length} strikes`);

            // Re-snap whatever the user was looking at to a strike that
            // actually exists. Preserves their +/- offset intent.
            this.calculateStrike();
            this.strikeOffsetEl.querySelector('span').textContent =
                `Offset: ${this.strikeOffset >= 0 ? '+' : ''}${this.strikeOffset}`;
            await this.updateOrderPreview();
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            console.warn('loadValidStrikes failed; falling back to increment math:', error);
            // Leave validStrikes alone — keep whatever we had, or empty.
        }
    }

    /**
     * Load symbol configuration. Cancellable via this._symbolAborter so a
     * rapid symbol switch doesn't leave a stale config landing into state.
     */
    async loadSymbolConfig() {
        // Capture the abort signal + the symbol at entry. The signal cancels
        // the network requests; the correlation check (requestedSymbol vs
        // this.currentSymbol) handles the case where abort fires between
        // `await` resolution and the `.then` body.
        const signal = this._symbolAborter?.signal;
        const requestedSymbol = this.currentSymbol;

        const isStale = () => requestedSymbol !== this.currentSymbol;

        try {
            this.symbolConfig = await window.ApiClient.getSymbolConfig(
                requestedSymbol, null, { signal }
            );
            if (isStale()) return;
            console.log('Symbol config loaded:', this.symbolConfig);

            this.currentPrice = this.symbolConfig.current_price;

            // Reset stale strike list from the PREVIOUS symbol before any
            // calculateStrike() runs — otherwise we'd briefly snap to a
            // strike from the wrong symbol's grid.
            this.validStrikes = [];
            this.validStrikesKey = null;

            await this.loadValidContracts();
            if (isStale()) return;

            // Now that DTE is set by loadValidContracts(), fetch the real
            // strike grid for this (symbol, DTE, type) and snap to it.
            await this.loadValidStrikes();
            if (isStale()) return;

            this.calculateStrike();
            await this.updateOrderPreview();
            if (isStale()) return;

            this.isReady = true;
            const snapshot = this.getTradingSnapshot();
            window.ChartTradingController?.setTradingSnapshot(snapshot);
            window.EventBus?.emit('trading_panel:ready', snapshot);

        } catch (error) {
            // Aborts are EXPECTED on symbol switching — don't treat as errors.
            if (error.name === 'AbortError') {
                console.log(`loadSymbolConfig aborted (was: ${requestedSymbol}, now: ${this.currentSymbol})`);
                return;
            }
            this.isReady = false;
            window.ChartTradingController?.setTradingSnapshot(this.getTradingSnapshot());
            console.error('Error loading symbol config:', error);
        }
    }

    /**
     * Build a stable snapshot of the current trading state.
     * Returned object is the contract consumed by ChartTradingController.
     */
    getTradingSnapshot() {
        const premium = Number(this.lastQuote?.mark || this.lastQuote?.last || 0);
        const contractsText = (this.contractsQtyEl?.textContent || '').trim();
        const contracts = Number(contractsText) || 0;

        return {
            symbol: this.currentSymbol,
            currentPrice: Number(this.currentPrice),
            strike: Number(this.selectedStrike),
            dte: Number(this.dte),
            premium,
            contracts,
            contractType: this.contractType,
            panelReady: this.isReady === true
        };
    }

    /**
     * Load and populate valid tradable contracts
     */
    async loadValidContracts() {
        // Capture the symbol AT REQUEST TIME — if the user switches symbols while
        // this fetch is in flight, the response that lands later belongs to the
        // OLD symbol and must NOT overwrite the dropdown for the NEW one.
        const requestedSymbol = this.currentSymbol;
        const signal = this._symbolAborter?.signal;
        try {
            const contractsData = await window.ApiClient.getSymbolContracts(
                requestedSymbol, false, { signal }
            );
            console.log('Valid contracts loaded:', contractsData);

            // Correlation-ID guard: even with AbortController, a response can
            // slip through the abort window. Reject anything for a stale symbol.
            if (requestedSymbol !== this.currentSymbol) {
                console.log(`loadValidContracts: stale response for ${requestedSymbol} (now on ${this.currentSymbol}), ignoring`);
                return;
            }

            const contracts = contractsData.contracts || [];

            // Persist the list so executeOrder() can pre-flight validate the
            // selected DTE against the actual broker chain — catches stale
            // DTE values that survive a symbol switch.
            this.validContracts = contracts;
            this.validContractsForSymbol = requestedSymbol;

            // Update DTE dropdown
            if (this.dteSelect && contracts.length > 0) {
                // Save current selection
                const currentDte = parseInt(this.dteSelect.value);

                // Clear existing options
                this.dteSelect.innerHTML = '';

                // Populate with valid contracts
                contracts.forEach(contract => {
                    const option = document.createElement('option');
                    option.value = contract.dte;
                    option.textContent = `${contract.dte} DTE - ${contract.expiration_display}`;
                    option.dataset.expiration = contract.expiration;
                    this.dteSelect.appendChild(option);
                });

                // Try to restore previous selection or select first
                const matchingOption = Array.from(this.dteSelect.options).find(
                    opt => parseInt(opt.value) === currentDte
                );
                if (matchingOption) {
                    this.dteSelect.value = currentDte;
                } else {
                    // DTE not available for this symbol, reset to first option
                    this.dteSelect.selectedIndex = 0;
                    const newDte = parseInt(this.dteSelect.value);

                    // Show warning to user if DTE changed
                    if (currentDte && newDte !== currentDte) {
                        console.warn(`DTE ${currentDte} not available for ${this.currentSymbol}. Reset to ${newDte} DTE.`);
                        window.Toast?.show(
                            `DTE changed from ${currentDte} to ${newDte} for ${this.currentSymbol}`,
                            'warning',
                            3000
                        );
                    }
                }

                // Update internal DTE value
                this.dte = parseInt(this.dteSelect.value);

                // Emit event to notify other components about DTE change
                window.EventBus?.emit('trading_panel:dte_changed', { dte: this.dte });

                console.log(`Populated ${contracts.length} contracts for ${this.currentSymbol}`);
            } else if (contracts.length === 0) {
                console.warn(`No valid contracts found for ${this.currentSymbol}`);
                if (this.dteSelect) {
                    this.dteSelect.innerHTML = '<option value="">No contracts available</option>';
                }
            }

        } catch (error) {
            // Re-throw aborts so the top-level loadSymbolConfig handler swallows
            // them quietly. Treating an abort as an "error" here would leave
            // isReady=false on the new symbol after symbol switching.
            if (error.name === 'AbortError') throw error;
            console.error('Error loading valid contracts:', error);
        }
    }

    /**
     * Update order preview
     */
    async updateOrderPreview() {
        if (!this.symbolConfig || !this.selectedStrike) {
            return;
        }

        // Capture the symbol context — if the user switches symbols while the
        // option-quote request is in flight, we MUST NOT let a stale quote
        // overwrite this.lastQuote (which would cascade into wrong premium,
        // wrong contract count, wrong P&L projections, etc.).
        const requestedSymbol = this.currentSymbol;
        const signal = this._symbolAborter?.signal;

        try {
            // Get option symbol
            const optionSymbol = this.formatOptionSymbol();

            // Fetch real-time option quote
            let premium = 2.50; // Fallback estimate
            let premiumSource = 'Est.'; // Indicator of estimate vs real

            try {
                const quoteResponse = await window.ApiClient.getOptionQuote(
                    optionSymbol, { signal }
                );
                if (requestedSymbol !== this.currentSymbol) return;  // stale

                this.lastQuote = quoteResponse; // Store for other components to use

                if (quoteResponse.success && quoteResponse.mark > 0) {
                    premium = quoteResponse.mark; // Use mark price (midpoint)
                    premiumSource = ''; // Real quote, no prefix
                } else if (quoteResponse.success && quoteResponse.last > 0) {
                    premium = quoteResponse.last; // Fallback to last trade
                    premiumSource = 'Last: ';
                } else {
                    premiumSource = 'Est.'; // No quote available
                }
            } catch (quoteError) {
                if (quoteError.name === 'AbortError') throw quoteError;
                console.warn('Could not fetch option quote, using estimate:', quoteError);
                premiumSource = 'Est.';
            }

            const costPerContract = premium * 100;
            const contracts = Math.floor(this.positionSize / costPerContract);

            // Update contracts display
            if (this.contractsQtyEl) {
                this.contractsQtyEl.textContent = contracts;
            }
            if (this.optionPremiumEl) {
                this.optionPremiumEl.textContent = `${premiumSource}$${premium.toFixed(2)}`;
            }

            // Update preview
            if (this.previewContract) {
                this.previewContract.textContent = optionSymbol;
            }
            if (this.previewQty) {
                this.previewQty.textContent = `${contracts} contract${contracts !== 1 ? 's' : ''}`;
            }
            if (this.previewCost) {
                const totalCost = contracts * costPerContract;
                this.previewCost.textContent = `$${totalCost.toFixed(2)}`;
            }

            // Emit update event for synced components
            if (window.EventBus) {
                window.EventBus.emit('trading_panel:update', { quote: this.lastQuote });
            }

            // Keep the on-chart controller's snapshot in sync with the latest
            // strike, premium, and contract count so readiness reflects reality.
            if (this.isReady) {
                window.ChartTradingController?.setTradingSnapshot(this.getTradingSnapshot());
            }

        } catch (error) {
            // Aborts during symbol switch should propagate quietly to the
            // top-level handler. Only real errors get logged.
            if (error.name === 'AbortError') throw error;
            console.error('Error updating preview:', error);
        }
    }

    /**
     * Calculate next valid trading day (skipping weekends)
     * @param {number} daysToExpiration - Days to expiration
     * @returns {Date} Next valid trading date
     */
    calculateExpirationDate(daysToExpiration) {
        const today = new Date();
        let expDate = new Date(today);
        let tradingDaysAdded = 0;

        // Add trading days, skipping weekends
        while (tradingDaysAdded < daysToExpiration) {
            expDate.setDate(expDate.getDate() + 1);
            const dayOfWeek = expDate.getDay();

            // Skip weekends (0 = Sunday, 6 = Saturday)
            if (dayOfWeek !== 0 && dayOfWeek !== 6) {
                tradingDaysAdded++;
            }
        }

        // If we end up on a weekend (shouldn't happen with above logic, but safety check)
        while (expDate.getDay() === 0 || expDate.getDay() === 6) {
            expDate.setDate(expDate.getDate() + 1);
        }

        return expDate;
    }

    /**
     * Format option symbol (simplified OCC format)
     * @returns {string} Option symbol
     */
    formatOptionSymbol() {
        // Simplified format: SYMBOL + DATE + TYPE + STRIKE
        // Real OCC format: SPY260115C00595000

        // Get the actual expiration date from the selected DTE option
        const selectedOption = this.dteSelect?.options[this.dteSelect.selectedIndex];
        const expirationStr = selectedOption?.dataset.expiration;

        let year, month, day;

        if (expirationStr) {
            // Use the actual expiration date from the contract (YYYY-MM-DD format)
            const parts = expirationStr.split('-');
            year = parts[0].slice(2); // YY
            month = parts[1]; // MM
            day = parts[2]; // DD
        } else {
            // Fallback to calculation if expiration not available
            const expDate = this.calculateExpirationDate(this.dte);
            year = expDate.getFullYear().toString().slice(2);
            month = (expDate.getMonth() + 1).toString().padStart(2, '0');
            day = expDate.getDate().toString().padStart(2, '0');
        }

        const type = this.contractType === 'CALL' ? 'C' : 'P';
        const strike = (this.selectedStrike * 1000).toString().padStart(8, '0');

        return `${this.currentSymbol}${year}${month}${day}${type}${strike}`;
    }

    /**
     * Execute order
     */
    async executeOrder() {
        // Pre-flight: the selected DTE must actually exist in the current
        // symbol's chain. The dropdown is filtered, but a race during symbol
        // switching can leave the DTE value stale (the new symbol's
        // loadValidContracts hasn't completed yet, or the previous symbol's
        // value carried over). Fail fast with a clear message rather than
        // letting the backend reject the order with a vague "Could not find
        // suitable option contract".
        if (this.validContracts && this.validContractsForSymbol === this.currentSymbol) {
            const validDtes = this.validContracts.map(c => c.dte);
            if (validDtes.length > 0 && !validDtes.includes(this.dte)) {
                const nearest = validDtes.reduce(
                    (a, b) => Math.abs(b - this.dte) < Math.abs(a - this.dte) ? b : a
                );
                window.Toast?.warning(
                    `DTE=${this.dte} not available for ${this.currentSymbol}. ` +
                    `Valid: ${validDtes.join(', ')}. Try DTE=${nearest}.`,
                    6000
                );
                return;
            }
        }

        // Check if connected to WebSocket (optional safety check)
        if (window.DataStream && !window.DataStream.isConnected()) {
            window.Toast.warning('WebSocket disconnected - order placement may be slower', 3000);
        }

        // Disable button
        this.executeBtn.disabled = true;
        this.executeBtnText.textContent = 'Placing Order...';

        try {
            // Prepare order data
            const orderData = {
                symbol: this.currentSymbol,
                contract_type: this.contractType,
                dte: this.dte,
                strike: this.selectedStrike,  // Send the calculated strike from frontend
                position_size: this.positionSize
            };

            // Add SL/TP if provided
            const stopLoss = parseFloat(this.stopLossInput.value);
            const takeProfit = parseFloat(this.takeProfitInput.value);

            if (!isNaN(stopLoss) && stopLoss > 0) {
                orderData.stop_loss_price = stopLoss;
            }

            if (!isNaN(takeProfit) && takeProfit > 0) {
                orderData.take_profit_price = takeProfit;
            }

            // Add order type
            const orderType = this.orderTypeSelect.value;
            if (orderType === 'limit') {
                orderData.order_type = 'equity_limit';
                const limitPrice = parseFloat(this.limitPriceInput.value);
                if (isNaN(limitPrice) || limitPrice <= 0) {
                    window.Toast.warning('Please enter a valid limit price');
                    return;
                }
                orderData.equity_limit_price = limitPrice;
            } else {
                orderData.order_type = 'equity_market';
            }

            // Add order execution type (limit or market for option order)
            const selectedExecution = Array.from(this.orderExecutionRadios || []).find(radio => radio.checked);
            orderData.option_order_type = selectedExecution?.value || 'limit';

            console.log('Placing order:', orderData);

            // Place order with 10-second timeout
            const timeoutPromise = new Promise((_, reject) =>
                setTimeout(() => reject(new Error('Order placement timed out after 10 seconds')), 10000)
            );
            const result = await Promise.race([
                window.ApiClient.openPosition(orderData),
                timeoutPromise
            ]);

            if (result.success) {
                console.log('Order placed successfully:', result);
                window.Toast.success(`Order ${result.status}! ${result.message}`, 4000);

                // Clear SL/TP inputs
                this.stopLossInput.value = '';
                this.takeProfitInput.value = '';

                // Emit event
                window.EventBus.emit('order:placed', result);
            } else {
                console.error('Order failed:', result);
                window.Toast.error(`Order failed: ${result.error}`, 5000);
            }

        } catch (error) {
            console.error('Error placing order:', error);
            window.Toast.error(`Error: ${error.message}`, 5000);
        } finally {
            // Re-enable button
            this.executeBtn.disabled = false;
            this.executeBtnText.textContent = `Buy ${this.contractType}`;
        }
    }

    /**
     * Close all positions
     */
    async closeAllPositions() {
        window.Toast.confirm(
            'Are you sure you want to close ALL open positions?',
            () => {
                try {
                    // Emit event to trigger position closure
                    window.EventBus.emit('positions:close_all');
                } catch (error) {
                    console.error('Error closing all positions:', error);
                    window.Toast.error(`Error: ${error.message}`, 5000);
                }
            }
        );
    }

    /**
     * Update trigger price label to show current symbol
     */
    updateTriggerPriceLabel() {
        if (this.triggerPriceLabel && this.currentSymbol) {
            this.triggerPriceLabel.textContent = `Trigger Price (${this.currentSymbol} Price)`;
        }
    }

    /**
     * Update UI state
     */
    updateUI() {
        // Load saved position size
        const savedSize = window.Settings.get('defaultPositionSize');
        if (savedSize && this.positionSizeInput) {
            this.positionSizeInput.value = savedSize;
            this.positionSize = savedSize;
        }

        // Set initial DTE
        this.dte = parseInt(this.dteSelect?.value || 0);

        // Update preview
        this.updateOrderPreview();
    }
}

// Global instance (initialized in main.js)
window.TradingPanel = null;
