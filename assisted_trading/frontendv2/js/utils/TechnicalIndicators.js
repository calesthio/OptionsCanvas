/**
 * TechnicalIndicators - Professional-grade technical indicator calculations
 * Calculations match TradingView implementations
 */

class TechnicalIndicators {
    /**
     * Calculate Simple Moving Average (SMA)
     * @param {Array} data - Array of {time, value} or bars with 'close'
     * @param {number} period - SMA period
     * @returns {Array} Array of {time, value}
     */
    static calculateSMA(data, period) {
        const result = [];

        for (let i = period - 1; i < data.length; i++) {
            let sum = 0;
            for (let j = 0; j < period; j++) {
                const val = data[i - j].close !== undefined ? data[i - j].close : data[i - j].value;
                sum += val;
            }

            result.push({
                time: data[i].time,
                value: sum / period
            });
        }

        return result;
    }

    /**
     * Calculate Exponential Moving Average (EMA)
     * @param {Array} data - Array of {time, value} or bars with 'close'
     * @param {number} period - EMA period
     * @returns {Array} Array of {time, value}
     */
    static calculateEMA(data, period) {
        const result = [];
        const multiplier = 2 / (period + 1);

        if (data.length < period) return result;

        // Start with SMA for first value
        let sum = 0;
        for (let i = 0; i < period; i++) {
            const val = data[i].close !== undefined ? data[i].close : data[i].value;
            sum += val;
        }
        const sma = sum / period;

        result.push({
            time: data[period - 1].time,
            value: sma
        });

        // Calculate EMA for subsequent values
        for (let i = period; i < data.length; i++) {
            const val = data[i].close !== undefined ? data[i].close : data[i].value;
            const ema = (val - result[result.length - 1].value) * multiplier + result[result.length - 1].value;

            result.push({
                time: data[i].time,
                value: ema
            });
        }

        return result;
    }

    /**
     * Calculate RSI (Relative Strength Index)
     * @param {Array} data - Array of bars with 'close'
     * @param {number} period - RSI period (default: 14)
     * @returns {Array} Array of {time, value}
     */
    static calculateRSI(data, period = 14) {
        const result = [];
        const gains = [];
        const losses = [];

        // Calculate price changes
        for (let i = 1; i < data.length; i++) {
            const change = data[i].close - data[i - 1].close;
            gains.push(change > 0 ? change : 0);
            losses.push(change < 0 ? -change : 0);
        }

        if (gains.length < period) return result;

        // Calculate initial average gain and loss (SMA)
        let avgGain = 0;
        let avgLoss = 0;
        for (let i = 0; i < period; i++) {
            avgGain += gains[i];
            avgLoss += losses[i];
        }
        avgGain /= period;
        avgLoss /= period;

        // First RSI value
        const rs1 = avgLoss === 0 ? 100 : avgGain / avgLoss;
        const rsi1 = 100 - (100 / (1 + rs1));
        result.push({
            time: data[period].time,
            value: rsi1
        });

        // Calculate subsequent RSI values using smoothed moving average
        for (let i = period; i < gains.length; i++) {
            avgGain = (avgGain * (period - 1) + gains[i]) / period;
            avgLoss = (avgLoss * (period - 1) + losses[i]) / period;

            const rs = avgLoss === 0 ? 100 : avgGain / avgLoss;
            const rsi = 100 - (100 / (1 + rs));

            result.push({
                time: data[i + 1].time,
                value: rsi
            });
        }

        return result;
    }

    /**
     * Calculate VWAP (Volume Weighted Average Price)
     * Resets at start of each day
     * @param {Array} data - Array of bars with OHLCV
     * @returns {Array} Array of {time, value}
     */
    static calculateVWAP(data) {
        const result = [];
        let cumulativeTPV = 0;  // Typical Price * Volume
        let cumulativeVolume = 0;
        let currentDay = null;

        for (let i = 0; i < data.length; i++) {
            const bar = data[i];
            const date = new Date(bar.time * 1000);
            const day = date.toDateString();

            // Reset on new day
            if (day !== currentDay) {
                cumulativeTPV = 0;
                cumulativeVolume = 0;
                currentDay = day;
            }

            // Typical Price = (High + Low + Close) / 3
            const typicalPrice = (bar.high + bar.low + bar.close) / 3;

            cumulativeTPV += typicalPrice * bar.volume;
            cumulativeVolume += bar.volume;

            const vwap = cumulativeVolume === 0 ? bar.close : cumulativeTPV / cumulativeVolume;

            result.push({
                time: bar.time,
                value: vwap
            });
        }

        return result;
    }

    /**
     * Prepare volume data for histogram
     * Colors based on candle direction
     * @param {Array} data - Array of bars with OHLCV
     * @returns {Array} Array of {time, value, color}
     */
    static prepareVolumeHistogram(data) {
        const result = [];

        for (let i = 0; i < data.length; i++) {
            const bar = data[i];
            const color = bar.close >= bar.open ? '#0ecb8180' : '#f6465d80';  // Green or red with transparency

            result.push({
                time: bar.time,
                value: bar.volume,
                color: color
            });
        }

        return result;
    }
}

// Make globally available
window.TechnicalIndicators = TechnicalIndicators;
