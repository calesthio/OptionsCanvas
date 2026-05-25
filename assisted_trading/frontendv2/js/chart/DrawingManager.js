/**
 * DrawingManager - Manages drawing tools (trend lines, horizontal rays)
 * Provides TradingView-like drawing capabilities
 */

class DrawingManager {
    constructor(chartManager) {
        this.chartManager = chartManager;
        this.chart = chartManager.getChart();
        this.series = chartManager.getSeries();

        this.drawings = new Map();  // Map of drawing_id -> {type, data, series}
        this.currentTool = null;  // 'trendline' | 'hline' | null
        this.isDrawing = false;
        this.drawingStart = null;
        this.selectedDrawing = null;  // Currently selected drawing ID for deletion

        this.setupDrawingHandlers();
    }

    /**
     * Setup mouse handlers for drawing
     */
    setupDrawingHandlers() {
        const container = document.getElementById('chartView');
        if (!container) return;

        // Click handler for starting/ending drawings
        container.addEventListener('click', (e) => {
            if (!this.currentTool) return;

            const rect = container.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            if (this.currentTool === 'hline') {
                // Horizontal line only needs one click
                this.addHorizontalLine(y);
                this.setTool(null);  // Deactivate tool after use
            } else if (this.currentTool === 'trendline') {
                if (!this.isDrawing) {
                    // First click - start drawing
                    this.startTrendLine(x, y);
                } else {
                    // Second click - complete drawing
                    this.completeTrendLine(x, y);
                }
            }
        });

        // Mouse move handler for showing preview
        container.addEventListener('mousemove', (e) => {
            if (!this.isDrawing || this.currentTool !== 'trendline') return;

            const rect = container.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            this.updateTrendLinePreview(x, y);
        });

        // Escape key to cancel drawing
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isDrawing) {
                this.cancelDrawing();
            }
        });
    }

    /**
     * Set current drawing tool
     * @param {string} tool - 'trendline' | 'hline' | null
     */
    setTool(tool) {
        this.currentTool = tool;

        // Update tool button states
        document.querySelectorAll('.tool-btn').forEach(btn => {
            btn.classList.remove('active');
        });

        if (tool === 'trendline') {
            document.getElementById('trendlineBtn')?.classList.add('active');
        } else if (tool === 'hline') {
            document.getElementById('hlineBtn')?.classList.add('active');
        }

        // Change cursor
        const chartView = document.getElementById('chartView');
        if (chartView) {
            chartView.style.cursor = tool ? 'crosshair' : 'default';
        }

        console.log('Drawing tool set to:', tool || 'none');
    }

    /**
     * Add horizontal line (ray)
     * @param {number} clientY - Y coordinate in pixels
     */
    addHorizontalLine(clientY) {
        const chart = this.chartManager.getChart();
        const series = this.chartManager.getSeries();

        // Convert client Y to price
        const price = series.coordinateToPrice(clientY);
        if (price === null) return;

        // Create price line
        const priceLine = series.createPriceLine({
            price: price,
            color: '#3861fb',  // Blue
            lineWidth: 2,
            lineStyle: LightweightCharts.LineStyle.Solid,
            axisLabelVisible: true,
            title: `${price.toFixed(2)}`,
        });

        const id = `hline_${Date.now()}`;
        this.drawings.set(id, {
            type: 'hline',
            priceLine: priceLine,
            price: price
        });

        // Auto-select the newly created drawing
        this.selectedDrawing = id;

        console.log(`Horizontal line added at ${price.toFixed(2)}`);
    }

    /**
     * Start drawing trend line
     * @param {number} x - X coordinate
     * @param {number} y - Y coordinate
     */
    startTrendLine(x, y) {
        const timeScale = this.chart.timeScale();
        const series = this.chartManager.getSeries();

        // Convert coordinates to time and price
        const time = timeScale.coordinateToTime(x);
        const price = series.coordinateToPrice(y);

        if (time === null || price === null) return;

        this.isDrawing = true;
        this.drawingStart = { time, price, x, y };

        console.log('Trend line started at:', time, price);
    }

    /**
     * Update trend line preview while dragging
     * @param {number} x - Current X coordinate
     * @param {number} y - Current Y coordinate
     */
    updateTrendLinePreview(x, y) {
        // Remove previous preview if exists
        if (this.previewLine) {
            this.chart.removeSeries(this.previewLine);
        }

        const timeScale = this.chart.timeScale();
        const series = this.chartManager.getSeries();

        const time = timeScale.coordinateToTime(x);
        const price = series.coordinateToPrice(y);

        if (time === null || price === null || !this.drawingStart) return;

        // Create preview line (TradingView v5.0 API)
        this.previewLine = this.chart.addSeries(LightweightCharts.LineSeries, {
            color: '#3861fb80',  // Semi-transparent blue
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        // Set two points for the line
        this.previewLine.setData([
            { time: this.drawingStart.time, value: this.drawingStart.price },
            { time: time, value: price }
        ]);
    }

    /**
     * Complete trend line drawing
     * @param {number} x - End X coordinate
     * @param {number} y - End Y coordinate
     */
    completeTrendLine(x, y) {
        if (!this.drawingStart) return;

        const timeScale = this.chart.timeScale();
        const series = this.chartManager.getSeries();

        const endTime = timeScale.coordinateToTime(x);
        const endPrice = series.coordinateToPrice(y);

        if (endTime === null || endPrice === null) return;

        // Remove preview
        if (this.previewLine) {
            this.chart.removeSeries(this.previewLine);
            this.previewLine = null;
        }

        // Create actual trend line series (TradingView v5.0 API)
        const trendLineSeries = this.chart.addSeries(LightweightCharts.LineSeries, {
            color: '#3861fb',  // Blue
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        trendLineSeries.setData([
            { time: this.drawingStart.time, value: this.drawingStart.price },
            { time: endTime, value: endPrice }
        ]);

        const id = `trendline_${Date.now()}`;
        this.drawings.set(id, {
            type: 'trendline',
            series: trendLineSeries,
            start: { time: this.drawingStart.time, price: this.drawingStart.price },
            end: { time: endTime, price: endPrice }
        });

        // Auto-select the newly created drawing
        this.selectedDrawing = id;

        console.log('Trend line completed');

        // Reset drawing state
        this.isDrawing = false;
        this.drawingStart = null;
        this.setTool(null);
    }

    /**
     * Cancel current drawing
     */
    cancelDrawing() {
        if (this.previewLine) {
            this.chart.removeSeries(this.previewLine);
            this.previewLine = null;
        }

        this.isDrawing = false;
        this.drawingStart = null;
        this.setTool(null);

        console.log('Drawing cancelled');
    }

    /**
     * Clear all drawings
     */
    clearAll() {
        for (const [id, drawing] of this.drawings) {
            if (drawing.type === 'hline') {
                // In TradingView v5.0, use series.removePriceLine()
                this.series.removePriceLine(drawing.priceLine);
            } else if (drawing.type === 'trendline') {
                this.chart.removeSeries(drawing.series);
            }
        }

        this.drawings.clear();
        console.log('All drawings cleared');
    }

    /**
     * Remove specific drawing
     * @param {string} id - Drawing ID
     */
    removeDrawing(id) {
        const drawing = this.drawings.get(id);
        if (!drawing) return;

        if (drawing.type === 'hline') {
            // In TradingView v5.0, use series.removePriceLine()
            this.series.removePriceLine(drawing.priceLine);
        } else if (drawing.type === 'trendline') {
            this.chart.removeSeries(drawing.series);
        }

        this.drawings.delete(id);
        console.log(`Drawing ${id} removed`);
    }

    /**
     * Delete the currently selected drawing
     */
    deleteSelected() {
        if (!this.selectedDrawing) {
            console.log('No drawing selected to delete');
            return false;
        }

        console.log(`Deleting selected drawing: ${this.selectedDrawing}`);
        this.removeDrawing(this.selectedDrawing);
        this.selectedDrawing = null;
        return true;
    }

    /**
     * Get all drawings (for persistence)
     */
    getAllDrawings() {
        const drawings = [];
        for (const [id, drawing] of this.drawings) {
            drawings.push({
                id,
                type: drawing.type,
                data: drawing.type === 'hline'
                    ? { price: drawing.price }
                    : { start: drawing.start, end: drawing.end }
            });
        }
        return drawings;
    }

    /**
     * Restore drawings from saved data
     * @param {Array} drawings - Array of drawing objects
     */
    restoreDrawings(drawings) {
        this.clearAll();

        for (const drawing of drawings) {
            if (drawing.type === 'hline') {
                // Recreate horizontal line
                const series = this.chartManager.getSeries();
                const priceLine = series.createPriceLine({
                    price: drawing.data.price,
                    color: '#3861fb',
                    lineWidth: 2,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: true,
                    title: `${drawing.data.price.toFixed(2)}`,
                });

                this.drawings.set(drawing.id, {
                    type: 'hline',
                    priceLine: priceLine,
                    price: drawing.data.price
                });
            } else if (drawing.type === 'trendline') {
                // Recreate trend line
                const trendLineSeries = this.chart.addLineSeries({
                    color: '#3861fb',
                    lineWidth: 2,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });

                trendLineSeries.setData([
                    { time: drawing.data.start.time, value: drawing.data.start.price },
                    { time: drawing.data.end.time, value: drawing.data.end.price }
                ]);

                this.drawings.set(drawing.id, {
                    type: 'trendline',
                    series: trendLineSeries,
                    start: drawing.data.start,
                    end: drawing.data.end
                });
            }
        }

        console.log(`Restored ${drawings.length} drawings`);
    }
}

// Make globally available
window.DrawingManager = DrawingManager;
