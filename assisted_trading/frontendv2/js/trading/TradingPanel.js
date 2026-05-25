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
            this.updateOrderPreview();
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

        // Listen for symbol changes
        window.EventBus.on('chart:symbol_loaded', (data) => {
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

        this.updateOrderPreview();
    }

    /**
     * Adjust strike offset
     * @param {number} direction - -1 for down, +1 for up
     */
    adjustStrike(direction) {
        if (!this.symbolConfig) {
            console.warn('Symbol config not loaded');
            return;
        }

        const increment = this.symbolConfig.strike_increment;
        this.strikeOffset += direction;

        this.selectedStrike = this.atmStrike + (this.strikeOffset * increment);

        // Update UI
        this.strikePriceEl.textContent = `$${this.selectedStrike.toFixed(2)}`;
        this.strikeOffsetEl.querySelector('span').textContent =
            `Offset: ${this.strikeOffset >= 0 ? '+' : ''}${this.strikeOffset}`;

        this.updateOrderPreview();
    }

    /**
     * Calculate ATM strike from current price
     */
    calculateStrike() {
        if (!this.symbolConfig || !this.currentPrice) {
            return;
        }

        // Round to nearest strike increment
        const increment = this.symbolConfig.strike_increment;
        this.atmStrike = Math.round(this.currentPrice / increment) * increment;
        this.selectedStrike = this.atmStrike + (this.strikeOffset * increment);

        // Update UI
        this.strikePriceEl.textContent = `$${this.selectedStrike.toFixed(2)}`;
    }

    /**
     * Load symbol configuration
     */
    async loadSymbolConfig() {
        try {
            // Load symbol config (tick sizes, etc)
            this.symbolConfig = await window.ApiClient.getSymbolConfig(this.currentSymbol);
            console.log('Symbol config loaded:', this.symbolConfig);

            this.currentPrice = this.symbolConfig.current_price;

            // Load valid contracts for this symbol
            await this.loadValidContracts();

            this.calculateStrike();
            await this.updateOrderPreview();
            this.isReady = true;
            const snapshot = this.getTradingSnapshot();
            window.ChartTradingController?.setTradingSnapshot(snapshot);
            window.EventBus?.emit('trading_panel:ready', snapshot);

        } catch (error) {
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
        try {
            const contractsData = await window.ApiClient.getSymbolContracts(this.currentSymbol);
            console.log('Valid contracts loaded:', contractsData);

            const contracts = contractsData.contracts || [];

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

        try {
            // Get option symbol
            const optionSymbol = this.formatOptionSymbol();

            // Fetch real-time option quote
            let premium = 2.50; // Fallback estimate
            let premiumSource = 'Est.'; // Indicator of estimate vs real

            try {
                const quoteResponse = await window.ApiClient.getOptionQuote(optionSymbol);
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
