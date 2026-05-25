/**
 * SmartDefaults - Intelligent default values for SL/TP based on price action
 * Auto-calculates stop loss and take profit levels using technical analysis
 * @version 1.0 - Smart trading defaults
 */

class SmartDefaults {
    constructor(chartManager) {
        this.chartManager = chartManager;

        // Configuration
        this.config = {
            atrPeriod: 14,
            atrMultiplierSL: 1.5,  // Stop loss 1.5x ATR
            atrMultiplierTP: 3.0,  // Take profit 3x ATR (2:1 R:R)
            swingLookback: 20,     // Look back 20 bars for swing high/low
        };

        console.log('SmartDefaults initialized');
    }

    /**
     * Calculate smart stop loss for a position
     * @param {string} contractType - 'CALL' or 'PUT'
     * @param {number} entryPrice - Entry price
     * @param {Array} bars - Historical price bars
     * @returns {number} Suggested stop loss price
     */
    calculateSmartStopLoss(contractType, entryPrice, bars = null) {
        if (!bars) {
            bars = this.getRecentBars();
        }

        if (!bars || bars.length < this.config.atrPeriod) {
            // Fallback: Use simple percentage
            const fallbackPercent = 0.02; // 2%
            return contractType === 'CALL'
                ? entryPrice * (1 - fallbackPercent)
                : entryPrice * (1 + fallbackPercent);
        }

        // Method 1: ATR-based stop loss
        const atr = this.calculateATR(bars);
        const atrSL = contractType === 'CALL'
            ? entryPrice - (atr * this.config.atrMultiplierSL)
            : entryPrice + (atr * this.config.atrMultiplierSL);

        // Method 2: Swing low/high based
        const swingSL = this.findSwingLevel(bars, contractType);

        // Use the more conservative (closer) stop loss
        if (contractType === 'CALL') {
            return Math.max(atrSL, swingSL);
        } else {
            return Math.min(atrSL, swingSL);
        }
    }

    /**
     * Calculate smart take profit for a position
     * @param {string} contractType - 'CALL' or 'PUT'
     * @param {number} entryPrice - Entry price
     * @param {number} stopLoss - Stop loss price
     * @param {Array} bars - Historical price bars
     * @returns {number} Suggested take profit price
     */
    calculateSmartTakeProfit(contractType, entryPrice, stopLoss, bars = null) {
        if (!bars) {
            bars = this.getRecentBars();
        }

        // Calculate risk
        const risk = Math.abs(entryPrice - stopLoss);

        // Use configured R:R ratio
        const rewardMultiplier = this.config.atrMultiplierTP / this.config.atrMultiplierSL;
        const reward = risk * rewardMultiplier;

        return contractType === 'CALL'
            ? entryPrice + reward
            : entryPrice - reward;
    }

    /**
     * Calculate Average True Range (ATR)
     * @param {Array} bars - Price bars
     * @returns {number} ATR value
     */
    calculateATR(bars) {
        if (!bars || bars.length < this.config.atrPeriod) {
            return 0;
        }

        const trueRanges = [];

        for (let i = 1; i < bars.length; i++) {
            const high = bars[i].high;
            const low = bars[i].low;
            const prevClose = bars[i - 1].close;

            const tr = Math.max(
                high - low,
                Math.abs(high - prevClose),
                Math.abs(low - prevClose)
            );

            trueRanges.push(tr);
        }

        // Calculate ATR as simple moving average of TR
        const recentTR = trueRanges.slice(-this.config.atrPeriod);
        const atr = recentTR.reduce((sum, tr) => sum + tr, 0) / recentTR.length;

        return atr;
    }

    /**
     * Find swing high/low for stop loss placement
     * @param {Array} bars - Price bars
     * @param {string} contractType - 'CALL' or 'PUT'
     * @returns {number} Swing level price
     */
    findSwingLevel(bars, contractType) {
        if (!bars || bars.length < this.config.swingLookback) {
            return contractType === 'CALL' ? bars[bars.length - 1].low : bars[bars.length - 1].high;
        }

        const recentBars = bars.slice(-this.config.swingLookback);

        if (contractType === 'CALL') {
            // Find swing low for CALL stop loss
            return Math.min(...recentBars.map(b => b.low));
        } else {
            // Find swing high for PUT stop loss
            return Math.max(...recentBars.map(b => b.high));
        }
    }

    /**
     * Get recent bars from chart
     * @returns {Array} Recent price bars
     */
    getRecentBars() {
        // Try to get bars from ChartManager or cached data
        if (window.ChartManager && window.ChartManager.getSeries()) {
            // Access cached bars if available
            const eventData = window.ChartManager.lastLoadedData;
            if (eventData && eventData.bars) {
                return eventData.bars;
            }
        }

        // Fallback: Return empty array (will trigger fallback calculations)
        return [];
    }

    /**
     * Apply smart defaults to trading panel
     * @param {string} contractType - 'CALL' or 'PUT'
     */
    async applySmartDefaults(contractType) {
        try {
            // Get current price and bars
            const currentSymbol = this.chartManager.getCurrentSymbol();
            if (!currentSymbol) {
                console.warn('No symbol selected');
                return;
            }

            // Get recent bars
            const bars = this.getRecentBars();

            // Get current price (use last bar close or current quote)
            const currentPrice = bars && bars.length > 0
                ? bars[bars.length - 1].close
                : 0;

            if (!currentPrice) {
                console.warn('Cannot determine current price');
                return;
            }

            // Calculate smart SL
            const smartSL = this.calculateSmartStopLoss(contractType, currentPrice, bars);

            // Calculate smart TP
            const smartTP = this.calculateSmartTakeProfit(contractType, currentPrice, smartSL, bars);

            // Set values in UI
            const slInput = document.getElementById('stopLoss');
            const tpInput = document.getElementById('takeProfit');

            if (slInput) {
                slInput.value = smartSL.toFixed(2);
            }

            if (tpInput) {
                tpInput.value = smartTP.toFixed(2);
            }

            // Show notification
            if (window.Toast) {
                const risk = Math.abs(currentPrice - smartSL);
                const reward = Math.abs(smartTP - currentPrice);
                const rr = reward / risk;

                window.Toast.success(
                    `Smart defaults applied: SL $${smartSL.toFixed(2)}, TP $${smartTP.toFixed(2)} (R:R 1:${rr.toFixed(1)})`,
                    4000
                );
            }

            console.log(`Smart defaults: SL=${smartSL.toFixed(2)}, TP=${smartTP.toFixed(2)}`);

        } catch (error) {
            console.error('Error applying smart defaults:', error);
            if (window.Toast) {
                window.Toast.error('Failed to calculate smart defaults', 3000);
            }
        }
    }

    /**
     * Calculate position size based on risk percentage
     * @param {number} accountBalance - Account balance
     * @param {number} riskPercent - Risk percentage (e.g., 1 for 1%)
     * @param {number} entryPrice - Entry price
     * @param {number} stopLoss - Stop loss price
     * @returns {number} Suggested position size in dollars
     */
    calculatePositionSize(accountBalance, riskPercent, entryPrice, stopLoss) {
        const riskAmount = accountBalance * (riskPercent / 100);
        const riskPerShare = Math.abs(entryPrice - stopLoss);

        // For options, the risk per contract is riskPerShare * 100
        const riskPerContract = riskPerShare * 100;

        // Calculate max contracts based on risk
        const maxContracts = Math.floor(riskAmount / riskPerContract);

        // Assume average option premium of $2.50 (will be updated with real quote)
        const estimatedPremium = 2.50;
        const positionSize = maxContracts * estimatedPremium * 100;

        return Math.max(100, positionSize); // Minimum $100
    }

    /**
     * Update configuration
     * @param {Object} newConfig - Configuration overrides
     */
    updateConfig(newConfig) {
        this.config = { ...this.config, ...newConfig };
        console.log('SmartDefaults config updated:', this.config);
    }
}

// Make globally available
window.SmartDefaults = SmartDefaults;
