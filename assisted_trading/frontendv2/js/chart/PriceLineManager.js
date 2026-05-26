/**
 * PriceLineManager - Manages price lines on the chart (Entry, SL, TP)
 * Handles creation, updates, and removal of price lines with labels showing contracts
 */

class PriceLineManager {
    constructor(chartManager) {
        this.chartManager = chartManager;
        this.priceLines = new Map();  // Map of lineId -> priceLine object
    }

    /**
     * Add entry price line for a position
     * @param {string} optionSymbol - Option symbol (used as lineId)
     * @param {number} price - Underlying entry price
     * @param {number} contracts - Number of contracts
     * @param {number} entryPremium - Entry premium price
     * @param {string} contractType - 'CALL' or 'PUT'
     */
    addEntryLine(optionSymbol, price, contracts, entryPremium, contractType) {
        const lineId = `entry_${optionSymbol}`;

        // Remove existing line if any
        this.removeLine(lineId);

        const series = this.chartManager.getSeries();
        if (!series) {
            console.error(`PriceLineManager: Cannot add entry line for ${optionSymbol} - chart series not initialized yet. Chart may still be loading.`);
            return;
        }

        // Create label with contracts and premium
        const label = `${contracts}c @ $${entryPremium.toFixed(2)}`;

        const priceLine = series.createPriceLine({
            price: price,
            color: '#3861fb',  // Blue for entry
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: label,
        });

        this.priceLines.set(lineId, {
            priceLine: priceLine,
            type: 'entry',
            optionSymbol: optionSymbol,
            price: price,
            contracts: contracts,
            entryPremium: entryPremium,
            contractType: contractType
        });

        console.log(`Added entry line: ${lineId} at $${price}`);
    }

    /**
     * Add stop loss price line
     * @param {string} optionSymbol - Option symbol
     * @param {number} price - Stop loss price
     * @param {string} contractType - 'CALL' or 'PUT'
     */
    addStopLossLine(optionSymbol, price, contractType, opts = {}) {
        const lineId = `sl_${optionSymbol}`;

        // Remove existing line if any
        this.removeLine(lineId);

        const series = this.chartManager.getSeries();
        if (!series) {
            console.error(`PriceLineManager: Cannot add SL line for ${optionSymbol} - chart series not initialized yet. Chart may still be loading.`);
            return;
        }

        // `pending` = the user clicked "+ SL" to spawn a line but hasn't
        // dragged + confirmed yet. Dashed style signals "this isn't saved
        // yet — drag me." Once the drag/confirm flow persists it, the next
        // PositionTracker.syncWithChart will re-render the line solid.
        const pending = !!opts.pending;
        const priceLine = series.createPriceLine({
            price: price,
            color: '#f6465d',  // Red for stop loss
            lineWidth: 2,
            lineStyle: pending
                ? LightweightCharts.LineStyle.Dashed
                : LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: pending ? 'SL (drag)' : 'SL',
        });

        this.priceLines.set(lineId, {
            priceLine: priceLine,
            type: 'stop_loss',
            optionSymbol: optionSymbol,
            price: price,
            contractType: contractType,
            draggable: true,
            pending: pending,
        });

        console.log(`Added stop loss line: ${lineId} at $${price}${pending ? ' (pending)' : ''}`);
    }

    /**
     * Add take profit price line
     * @param {string} optionSymbol - Option symbol
     * @param {number} price - Take profit price
     * @param {string} contractType - 'CALL' or 'PUT'
     */
    addTakeProfitLine(optionSymbol, price, contractType, opts = {}) {
        const lineId = `tp_${optionSymbol}`;

        // Remove existing line if any
        this.removeLine(lineId);

        const series = this.chartManager.getSeries();
        if (!series) {
            console.error(`PriceLineManager: Cannot add TP line for ${optionSymbol} - chart series not initialized yet. Chart may still be loading.`);
            return;
        }

        const pending = !!opts.pending;
        const priceLine = series.createPriceLine({
            price: price,
            color: '#0ecb81',  // Green for take profit
            lineWidth: 2,
            lineStyle: pending
                ? LightweightCharts.LineStyle.Dashed
                : LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: pending ? 'TP (drag)' : 'TP',
        });

        this.priceLines.set(lineId, {
            priceLine: priceLine,
            type: 'take_profit',
            optionSymbol: optionSymbol,
            price: price,
            contractType: contractType,
            draggable: true,
            pending: pending,
        });

        console.log(`Added take profit line: ${lineId} at $${price}${pending ? ' (pending)' : ''}`);
    }

    /**
     * Add pending order price line
     * @param {Object} order - Order data
     */
    addPendingOrderLine(order) {
        const lineId = `pending_${order.order_id}`;

        // Remove existing line if any
        this.removeLine(lineId);

        const series = this.chartManager.getSeries();
        if (!series) return;

        const priceLine = series.createPriceLine({
            price: order.equity_limit_price,
            color: '#ff9800',  // Orange for pending
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: `ORDER: ${order.contract_type} @ $${order.equity_limit_price.toFixed(2)}`,
        });

        this.priceLines.set(lineId, {
            priceLine: priceLine,
            type: 'pending_order',
            symbol: order.symbol,
            price: order.equity_limit_price,
            orderId: order.order_id,
            draggable: false // Limit orders are currently not draggable by user
        });

        console.log(`Added pending order line: ${lineId} at $${order.equity_limit_price}`);
    }

    /**
     * Update a price line position
     * @param {string} lineId - Line ID
     * @param {number} newPrice - New price
     */
    updateLinePrice(lineId, newPrice) {
        const lineData = this.priceLines.get(lineId);
        if (!lineData) {
            console.warn(`Line ${lineId} not found`);
            return;
        }

        // Remove old line
        const series = this.chartManager.getSeries();
        series.removePriceLine(lineData.priceLine);

        // Create new line with updated price
        if (lineData.type === 'entry') {
            this.addEntryLine(
                lineData.optionSymbol,
                newPrice,
                lineData.contracts,
                lineData.entryPremium,
                lineData.contractType
            );
        } else if (lineData.type === 'stop_loss') {
            this.addStopLossLine(lineData.optionSymbol, newPrice, lineData.contractType);
        } else if (lineData.type === 'take_profit') {
            this.addTakeProfitLine(lineData.optionSymbol, newPrice, lineData.contractType);
        }

        console.log(`Updated ${lineId} to $${newPrice}`);
    }

    /**
     * Remove a price line
     * @param {string} lineId - Line ID
     */
    removeLine(lineId) {
        const lineData = this.priceLines.get(lineId);
        if (!lineData) {
            return;
        }

        const series = this.chartManager.getSeries();
        if (series && lineData.priceLine) {
            try {
                series.removePriceLine(lineData.priceLine);
                console.log(`Successfully removed series line: ${lineId}`);
            } catch (e) {
                console.error(`Failed to remove series line: ${lineId}`, e);
            }
        }

        this.priceLines.delete(lineId);
        console.log(`Removed from map: ${lineId}`);
    }

    /**
     * Remove all lines for a position
     * @param {string} optionSymbol - Option symbol
     */
    removePosition(optionSymbol) {
        this.removeLine(`entry_${optionSymbol}`);
        this.removeLine(`sl_${optionSymbol}`);
        this.removeLine(`tp_${optionSymbol}`);
    }

    /**
     * Remove all price lines
     */
    clearAll() {
        const series = this.chartManager.getSeries();
        if (!series) {
            return;
        }

        this.priceLines.forEach((lineData, lineId) => {
            if (lineData.priceLine) {
                series.removePriceLine(lineData.priceLine);
            }
        });

        this.priceLines.clear();
        console.log('Cleared all price lines');
    }

    /**
     * Get line data
     * @param {string} lineId - Line ID
     * @returns {Object} Line data
     */
    getLine(lineId) {
        return this.priceLines.get(lineId);
    }

    /**
     * Get all draggable lines (SL and TP)
     * @returns {Array} Array of draggable line data
     */
    getDraggableLines() {
        const draggable = [];
        this.priceLines.forEach((lineData, lineId) => {
            if (lineData.draggable) {
                draggable.push({
                    lineId: lineId,
                    ...lineData
                });
            }
        });
        return draggable;
    }
}

// Global instance (initialized in main.js)
window.PriceLineManager = null;
