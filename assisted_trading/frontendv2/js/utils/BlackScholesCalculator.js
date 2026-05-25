/**
 * BlackScholesCalculator.js
 * Utility for calculating option prices and Greeks using Black-Scholes model.
 * Used for estimating prices at SL/TP levels and as fallback when API Greeks are missing.
 */

class BlackScholesCalculator {
    constructor() {
        // Standard constants
        this.RISK_FREE_RATE = 0.045; // 4.5% default
    }

    /**
     * Standard Normal Cumulative Distribution Function (CDF)
     * using approximation
     */
    normalCDF(x) {
        if (x < 0) return 1 - this.normalCDF(-x);

        const b1 = 0.319381530;
        const b2 = -0.356563782;
        const b3 = 1.781477937;
        const b4 = -1.821255978;
        const b5 = 1.330274429;
        const p = 0.2316419;
        const c = 0.39894228;

        const t = 1 / (1 + p * x);
        const term = ((((b5 * t + b4) * t + b3) * t + b2) * t + b1) * t;

        return 1 - c * Math.exp(-x * x / 2) * term;
    }

    /**
     * Standard Normal Probability Density Function (PDF)
     */
    normalPDF(x) {
        return Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);
    }

    /**
     * Calculate d1 and d2 parameters
     */
    calculateD1D2(S, K, T, r, sigma) {
        // Prevent division by zero
        if (T <= 0 || sigma <= 0) return { d1: 0, d2: 0 };

        const d1 = (Math.log(S / K) + (r + sigma * sigma / 2) * T) / (sigma * Math.sqrt(T));
        const d2 = d1 - sigma * Math.sqrt(T);

        return { d1, d2 };
    }

    /**
     * Calculate Call Option Price
     * @param {number} S - Current underlying price
     * @param {number} K - Strike price
     * @param {number} T - Time to expiration in years
     * @param {number} r - Risk-free rate (decimal)
     * @param {number} sigma - Volatility (decimal)
     */
    calculateCallPrice(S, K, T, r, sigma) {
        if (T <= 0) return Math.max(0, S - K); // Intrinsic value at expiry

        const { d1, d2 } = this.calculateD1D2(S, K, T, r, sigma);
        return S * this.normalCDF(d1) - K * Math.exp(-r * T) * this.normalCDF(d2);
    }

    /**
     * Calculate Put Option Price
     */
    calculatePutPrice(S, K, T, r, sigma) {
        if (T <= 0) return Math.max(0, K - S); // Intrinsic value at expiry

        const { d1, d2 } = this.calculateD1D2(S, K, T, r, sigma);
        return K * Math.exp(-r * T) * this.normalCDF(-d2) - S * this.normalCDF(-d1);
    }

    /**
     * Calculate Delta (Sensitivity to price change)
     */
    calculateDelta(S, K, T, r, sigma, optionType = 'CALL') {
        if (T <= 0) {
            if (optionType === 'CALL') return S > K ? 1 : 0;
            return S < K ? -1 : 0;
        }

        const { d1 } = this.calculateD1D2(S, K, T, r, sigma);
        if (optionType === 'CALL') {
            return this.normalCDF(d1);
        } else {
            return this.normalCDF(d1) - 1;
        }
    }

    /**
     * Calculate Gamma (Rate of change of delta)
     * Same for Calls and Puts
     */
    calculateGamma(S, K, T, r, sigma) {
        if (T <= 0 || S <= 0 || sigma <= 0) return 0;

        const { d1 } = this.calculateD1D2(S, K, T, r, sigma);
        return this.normalPDF(d1) / (S * sigma * Math.sqrt(T));
    }

    /**
     * Calculate Theta (Time decay)
     * @returns {number} Daily theta (decay per day)
     */
    calculateTheta(S, K, T, r, sigma, optionType = 'CALL') {
        if (T <= 0) return 0;

        const { d1, d2 } = this.calculateD1D2(S, K, T, r, sigma);
        const term1 = -(S * this.normalPDF(d1) * sigma) / (2 * Math.sqrt(T));

        let result;
        if (optionType === 'CALL') {
            const term2 = r * K * Math.exp(-r * T) * this.normalCDF(d2);
            result = term1 - term2;
        } else {
            const term2 = r * K * Math.exp(-r * T) * this.normalCDF(-d2);
            result = term1 + term2;
        }

        // Return daily theta (divide annual theta by 365)
        return result / 365;
    }

    /**
     * Calculate Vega (Sensitivity to volatility)
     * Same for Calls and Puts
     * @returns {number} Vega (% change in price for 1% change in volatility)
     */
    calculateVega(S, K, T, r, sigma) {
        if (T <= 0) return 0;

        const { d1 } = this.calculateD1D2(S, K, T, r, sigma);
        // Vega is typically expressed as change per 1% vol change, so divide estimate by 100
        return (S * Math.sqrt(T) * this.normalPDF(d1)) / 100;
    }

    /**
     * Estimate option price at a specific underlying price target
     * Assumes constant IV and time (snapshot)
     */
    estimatePriceAtTarget(targetUnderlyingPrice, K, T, r, sigma, optionType) {
        if (optionType === 'CALL') {
            return this.calculateCallPrice(targetUnderlyingPrice, K, T, r, sigma);
        } else {
            return this.calculatePutPrice(targetUnderlyingPrice, K, T, r, sigma);
        }
    }
}

// Make globally available
window.BlackScholesCalculator = BlackScholesCalculator;