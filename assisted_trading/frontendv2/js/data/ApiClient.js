/**
 * ApiClient - Handles all REST API communication with backend
 */

class ApiClient {
    constructor(baseUrl = window.location.origin) {
        this.baseUrl = baseUrl;
        // CSRF token is rendered into <meta name="csrf-token"> by the server.
        // Required on every state-changing request — without it, the backend
        // returns 403. Stops a malicious page the user happens to visit from
        // POSTing to localhost:5001 in their name. See backend/security.py.
        const meta = document.querySelector('meta[name="csrf-token"]');
        this.csrfToken = meta ? meta.getAttribute('content') : '';
        if (!this.csrfToken) {
            console.warn('ApiClient: no CSRF token found — POSTs will be rejected');
        }
    }

    /**
     * Make a GET request
     * @param {string} endpoint - API endpoint
     * @param {Object} params - Query parameters
     * @returns {Promise<Object>} Response data
     */
    async get(endpoint, params = {}) {
        try {
            const url = new URL(`${this.baseUrl}${endpoint}`);
            Object.keys(params).forEach(key => {
                if (params[key] !== null && params[key] !== undefined) {
                    url.searchParams.append(key, params[key]);
                }
            });

            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API GET error (${endpoint}):`, error);
            throw error;
        }
    }

    /**
     * Make a POST request
     * @param {string} endpoint - API endpoint
     * @param {Object} data - Request body
     * @returns {Promise<Object>} Response data
     */
    async post(endpoint, data = {}) {
        try {
            const response = await fetch(`${this.baseUrl}${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': this.csrfToken,
                },
                body: JSON.stringify(data)
            });

            if (!response.ok) {
                const errorData = await response.json().catch(() => null);
                throw new Error(errorData?.error || `HTTP error! status: ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API POST error (${endpoint}):`, error);
            throw error;
        }
    }

    // ========== Health & Status ==========

    /**
     * Health check
     * @returns {Promise<Object>} Health status
     */
    async healthCheck() {
        return this.get('/api/health');
    }

    /**
     * Get broker information
     * @returns {Promise<Object>} Broker info
     */
    async getBrokerInfo() {
        return this.get('/api/broker/info');
    }

    /**
     * Get frontend configuration
     * @returns {Promise<Object>} Config with symbols, contract_types, etc.
     */
    async getConfig() {
        return this.get('/api/config');
    }

    // ========== Chart Data ==========

    /**
     * Get historical chart data
     * @param {string} symbol - Symbol to fetch
     * @param {Object} options - Options (timeframe, limit, start, end)
     * @returns {Promise<Object>} Chart data
     */
    async getHistoricalBars(symbol, options = {}) {
        return this.get(`/api/chart/historical/${symbol}`, {
            timeframe: options.timeframe || '5Min',
            limit: options.limit || 1000,
            start: options.start,
            end: options.end
        });
    }

    /**
     * Get valid tradable contracts for a symbol
     * @param {string} symbol - Symbol
     * @param {boolean} refresh - Force refresh cache
     * @returns {Promise<Object>} Valid contracts with DTE and expiration dates
     */
    async getSymbolContracts(symbol, refresh = false) {
        return this.get(`/api/symbol/contracts/${symbol}`, { refresh: refresh.toString() });
    }

    /**
     * Get symbol configuration (tick sizes, strike increments)
     * @param {string} symbol - Symbol
     * @param {number} price - Current price (optional)
     * @returns {Promise<Object>} Symbol config
     */
    async getSymbolConfig(symbol, price = null) {
        const params = {};
        if (price !== null) {
            params.price = price;
        }
        return this.get(`/api/symbol/config/${symbol}`, params);
    }

    /**
     * Get real-time option quote
     * @param {string} optionSymbol - OCC option symbol
     * @returns {Promise<Object>} Option quote with bid, ask, last, mark
     */
    async getOptionQuote(optionSymbol) {
        return this.get(`/api/option/quote/${optionSymbol}`);
    }

    // ========== Trading Operations ==========

    /**
     * Open a new position
     * @param {Object} data - Position data
     * @returns {Promise<Object>} Result
     */
    async openPosition(data) {
        return this.post('/api/open_position', data);
    }

    /**
     * Close a position
     * @param {string} optionSymbol - Option symbol
     * @param {number} contracts - Number of contracts to close
     * @returns {Promise<Object>} Result
     */
    async getOrders() {
        return this.get('/api/orders');
    }

    async closePosition(optionSymbol, contracts) {
        return this.post('/api/close_position', {
            option_symbol: optionSymbol,
            contracts: contracts
        });
    }

    /**
     * Update stop loss and/or take profit
     * @param {string} optionSymbol - Option symbol
     * @param {number} stopLoss - New stop loss (optional)
     * @param {number} takeProfit - New take profit (optional)
     * @returns {Promise<Object>} Result
     */
    async updateStopLossTakeProfit(optionSymbol, stopLoss = null, takeProfit = null) {
        const data = { option_symbol: optionSymbol };

        if (stopLoss !== null) {
            data.stop_loss_price = stopLoss;
        }

        if (takeProfit !== null) {
            data.take_profit_price = takeProfit;
        }

        return this.post('/api/position/update_sl_tp', data);
    }

    /**
     * Get all positions
     * @returns {Promise<Object>} Positions data
     */
    async getPositions() {
        return this.get('/api/position');
    }

    /**
     * Get day P&L
     * @returns {Promise<Object>} Day P&L data
     */
    async getDayPnL() {
        return this.get('/api/day_pnl');
    }

    /**
     * Get trading journal
     * @param {string} date - Date filter (optional)
     * @returns {Promise<Object>} Journal data
     */
    async getJournal(date = null) {
        const params = {};
        if (date) {
            params.date = date;
        }
        return this.get('/api/journal', params);
    }

    /**
     * Cancel a pending order
     * @param {string} orderId - Order ID
     * @returns {Promise<Object>} Result
     */
    async cancelPendingOrder(orderId) {
        return this.post('/api/cancel_pending_order', {
            order_id: orderId
        });
    }
}

// Create singleton instance
window.ApiClient = new ApiClient();
