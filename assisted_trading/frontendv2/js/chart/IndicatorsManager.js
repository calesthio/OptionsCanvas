/**
 * IndicatorsManager - Manages technical indicators on the chart
 * Handles adding/removing indicators and maintaining their state
 */

class IndicatorsManager {
    constructor(chartManager) {
        this.chartManager = chartManager;
        this.indicators = new Map();  // Map of indicator_id -> {series, type, params}
        this.volumeChart = null;
        this.volumeSeries = null;
        this.rsiChart = null;
        this.rsiSeries = null;

        // Store references to reference lines
        this.rsiLines = {
            upper: null,
            lower: null
        };

        // Setup resize handler for indicator panes
        this.setupResizeHandler();
    }

    /**
     * Setup window resize handler to update indicator pane dimensions
     */
    setupResizeHandler() {
        window.addEventListener('resize', () => {
            this.handleResize();
        });
    }

    /**
     * Handle window resize - update all indicator pane dimensions
     */
    handleResize() {
        const chartContainer = document.getElementById('chartView');
        if (!chartContainer) return;

        const chartWidth = chartContainer.clientWidth;
        const chartHeight = chartContainer.clientHeight;

        // Resize volume pane (20% of chart height)
        if (this.volumeChart) {
            const volumeHeight = Math.max(60, Math.floor(chartHeight * 0.20));
            const volumeContainer = document.getElementById('volumeChart');
            if (volumeContainer) {
                volumeContainer.style.height = `${volumeHeight}px`;
            }
            this.volumeChart.applyOptions({
                width: chartWidth,
                height: volumeHeight,
            });
        }

        // Resize RSI pane (keep at 150px for now - can make this responsive too)
        if (this.rsiChart) {
            const rsiHeight = 150;
            const rsiContainer = document.getElementById('rsiChart');
            if (rsiContainer) {
                rsiContainer.style.height = `${rsiHeight}px`;
            }
            this.rsiChart.applyOptions({
                width: chartWidth,
                height: rsiHeight,
            });
        }
    }

    /**
     * Add volume histogram in separate pane (TradingView style)
     */
    addVolumeHistogram() {
        if (this.volumeSeries) {
            console.log('Volume histogram already exists');
            return;
        }

        const chartContainer = document.getElementById('chartView');
        if (!chartContainer) {
            console.error('Chart container not found');
            return;
        }

        // Create separate chart pane for volume (before RSI if it exists)
        const volumeContainer = document.createElement('div');
        volumeContainer.id = 'volumeChart';

        // Calculate responsive height: 20% of chart container height
        const chartHeight = chartContainer.clientHeight;
        const volumeHeight = Math.max(60, Math.floor(chartHeight * 0.20)); // Min 60px, max 20% of chart

        volumeContainer.style.height = `${volumeHeight}px`;
        volumeContainer.style.width = '100%';
        volumeContainer.style.marginTop = '2px';

        // Insert after main chart but before RSI (if exists)
        const rsiChart = document.getElementById('rsiChart');
        if (rsiChart) {
            chartContainer.parentNode.insertBefore(volumeContainer, rsiChart);
        } else {
            chartContainer.parentNode.appendChild(volumeContainer);
        }

        // Create volume chart with matching theme
        this.volumeChart = LightweightCharts.createChart(volumeContainer, {
            width: chartContainer.clientWidth,
            height: volumeHeight,
            layout: {
                background: { type: 'solid', color: getComputedStyle(document.body).getPropertyValue('--primary-bg').trim() || '#0f1419' },
                textColor: '#a8aeb8',
            },
            grid: {
                vertLines: { color: '#2b3139' },
                horzLines: { color: '#2b3139' },
            },
            rightPriceScale: {
                borderColor: '#2b3139',
                scaleMargins: {
                    top: 0.1,
                    bottom: 0.1,
                },
            },
            timeScale: {
                borderColor: '#2b3139',
                visible: false,  // Hide time scale on volume pane
                timeVisible: false,
            },
            crosshair: {
                vertLine: {
                    visible: true,
                    labelVisible: false,
                },
                horzLine: {
                    visible: false,
                },
            },
        });

        // Add volume histogram series
        this.volumeSeries = this.volumeChart.addSeries(LightweightCharts.HistogramSeries, {
            color: '#26a69a',
            priceFormat: {
                type: 'volume',
            },
            priceScaleId: 'right',
        });

        // Load volume data
        this.updateVolumeData();

        this.indicators.set('volume', {
            chart: this.volumeChart,
            series: this.volumeSeries,
            type: 'volume',
            params: {}
        });

        console.log('Volume histogram added in separate pane');

        // Sync time scales with main chart
        this.syncTimeScales();
    }

    /**
     * Remove volume histogram
     */
    removeVolumeHistogram() {
        if (!this.volumeChart) return;

        const volumeContainer = document.getElementById('volumeChart');
        if (volumeContainer) {
            volumeContainer.remove();
        }

        this.volumeChart.remove();
        this.volumeChart = null;
        this.volumeSeries = null;
        this.indicators.delete('volume');

        console.log('Volume histogram removed');
    }

    /**
     * Update volume data from main series data
     */
    updateVolumeData() {
        if (!this.volumeSeries) return;

        // Get current symbol's bars
        const symbol = this.chartManager.getCurrentSymbol();
        if (!symbol) return;

        // Fetch bars and update volume
        window.ApiClient.getHistoricalBars(symbol, {
            timeframe: this.chartManager.getCurrentTimeframe(),
            limit: 1000
        }).then(response => {
            if (response && response.bars) {
                const volumeData = window.TechnicalIndicators.prepareVolumeHistogram(response.bars);
                this.volumeSeries.setData(volumeData);
            }
        }).catch(error => {
            console.error('Error updating volume data:', error);
        });
    }

    /**
     * Update volume bar in real-time
     * @param {Object} barData - Bar data with volume
     */
    updateVolumeBar(barData) {
        if (!this.volumeSeries) return;

        try {
            const color = barData.bar.close >= barData.bar.open ? '#0ecb8180' : '#f6465d80';

            // Ensure time is a valid Unix timestamp (number)
            const time = typeof barData.bar.time === 'number' ? barData.bar.time : parseInt(barData.bar.time);

            this.volumeSeries.update({
                time: time,
                value: barData.bar.volume,
                color: color
            });
        } catch (error) {
            // Silently ignore volume update errors to prevent spam
            // This can happen when updates come out of order
        }
    }

    /**
     * Add RSI indicator in separate pane
     * @param {number} period - RSI period (default: 14)
     */
    addRSI(period = 14) {
        if (this.rsiSeries) {
            console.log('RSI already exists');
            return;
        }

        const chartContainer = document.getElementById('chartView');
        if (!chartContainer) return;

        // Create separate chart for RSI
        const rsiContainer = document.createElement('div');
        rsiContainer.id = 'rsiChart';
        rsiContainer.style.height = '150px';
        rsiContainer.style.width = '100%';

        chartContainer.parentNode.appendChild(rsiContainer);

        this.rsiChart = LightweightCharts.createChart(rsiContainer, {
            width: chartContainer.clientWidth,
            height: 150,
            layout: {
                background: { type: 'solid', color: getComputedStyle(document.body).getPropertyValue('--primary-bg').trim() || '#0f1419' },
                textColor: '#a8aeb8',
            },
            grid: {
                vertLines: { color: '#2b3139' },
                horzLines: { color: '#2b3139' },
            },
            rightPriceScale: {
                borderColor: '#2b3139',
            },
            timeScale: {
                borderColor: '#2b3139',
                visible: true,
                timeVisible: false,
            },
        });

        // Add RSI line series
        this.rsiSeries = this.rsiChart.addSeries(LightweightCharts.LineSeries, {
            color: '#9b59b6',
            lineWidth: 2,
            priceScaleId: 'right',
        });

        // Add reference lines at 70 and 30
        this.rsiLines.upper = this.rsiSeries.createPriceLine({
            price: 70,
            color: '#f6465d',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'Overbought',
        });

        this.rsiLines.lower = this.rsiSeries.createPriceLine({
            price: 30,
            color: '#0ecb81',
            lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true,
            title: 'Oversold',
        });

        // Set RSI scale to 0-100
        this.rsiChart.priceScale('right').applyOptions({
            scaleMargins: {
                top: 0.1,
                bottom: 0.1,
            },
            autoScale: true,  // Enable auto-scaling for RSI
        });

        // Calculate and set RSI data
        this.updateRSIData(period);

        this.indicators.set('rsi', {
            chart: this.rsiChart,
            series: this.rsiSeries,
            type: 'rsi',
            params: { period }
        });

        console.log('RSI indicator added');

        // Sync time scales
        this.syncTimeScales();
    }

    /**
     * Remove RSI indicator
     */
    removeRSI() {
        if (!this.rsiChart) return;

        const rsiContainer = document.getElementById('rsiChart');
        if (rsiContainer) {
            rsiContainer.remove();
        }

        this.rsiChart.remove();
        this.rsiChart = null;
        this.rsiSeries = null;
        this.rsiLines.upper = null;
        this.rsiLines.lower = null;
        this.indicators.delete('rsi');

        console.log('RSI indicator removed');
    }

    /**
     * Update RSI data
     */
    updateRSIData(period = 14) {
        if (!this.rsiSeries) return;

        const symbol = this.chartManager.getCurrentSymbol();
        if (!symbol) return;

        window.ApiClient.getHistoricalBars(symbol, {
            timeframe: this.chartManager.getCurrentTimeframe(),
            limit: 1000
        }).then(response => {
            if (response && response.bars) {
                const rsiData = window.TechnicalIndicators.calculateRSI(response.bars, period);
                console.log('RSI data calculated:', rsiData.length, 'points');
                console.log('Sample RSI values:', rsiData.slice(0, 3), rsiData.slice(-3));
                this.rsiSeries.setData(rsiData);
                console.log('RSI data set successfully');
            }
        }).catch(error => {
            console.error('Error updating RSI data:', error);
        });
    }

    /**
     * Add SMA indicator
     * @param {number} period - SMA period
     * @param {string} color - Line color
     * @param {number} lineStyle - Line style (0=solid, 1=dotted, 2=dashed)
     */
    addSMA(period, color = '#2196F3', lineStyle = 2) {
        const id = `sma_${period}`;
        if (this.indicators.has(id)) {
            console.log(`SMA ${period} already exists`);
            return;
        }

        const chart = this.chartManager.getChart();
        const series = chart.addSeries(LightweightCharts.LineSeries, {
            color: color,
            lineWidth: 2,
            lineStyle: lineStyle,  // 2 = Dashed
            priceLineVisible: false,
            lastValueVisible: false,
        });

        this.indicators.set(id, {
            series: series,
            type: 'sma',
            params: { period }
        });

        this.updateSMAData(id, period);
        console.log(`SMA ${period} added`);
    }

    /**
     * Add EMA indicator
     * @param {number} period - EMA period
     * @param {string} color - Line color
     */
    addEMA(period, color) {
        const id = `ema_${period}`;
        if (this.indicators.has(id)) {
            console.log(`EMA ${period} already exists`);
            return;
        }

        const chart = this.chartManager.getChart();
        const series = chart.addSeries(LightweightCharts.LineSeries, {
            color: color,
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
        });

        this.indicators.set(id, {
            series: series,
            type: 'ema',
            params: { period }
        });

        this.updateEMAData(id, period);
        console.log(`EMA ${period} added`);
    }

    /**
     * Add VWAP indicator
     */
    addVWAP() {
        const id = 'vwap';
        if (this.indicators.has(id)) {
            console.log('VWAP already exists');
            return;
        }

        const chart = this.chartManager.getChart();
        const series = chart.addSeries(LightweightCharts.LineSeries, {
            color: '#E91E63',  // Pink
            lineWidth: 2,
            lineStyle: 3,  // Dotted
            priceLineVisible: false,
            lastValueVisible: false,
        });

        this.indicators.set(id, {
            series: series,
            type: 'vwap',
            params: {}
        });

        this.updateVWAPData();
        console.log('VWAP added');
    }

    /**
     * Update SMA data
     */
    updateSMAData(id, period) {
        const indicator = this.indicators.get(id);
        if (!indicator) return;

        const symbol = this.chartManager.getCurrentSymbol();
        if (!symbol) return;

        window.ApiClient.getHistoricalBars(symbol, {
            timeframe: this.chartManager.getCurrentTimeframe(),
            limit: 1000
        }).then(response => {
            if (response && response.bars) {
                const smaData = window.TechnicalIndicators.calculateSMA(response.bars, period);
                indicator.series.setData(smaData);
            }
        }).catch(error => {
            console.error('Error updating SMA data:', error);
        });
    }

    /**
     * Update EMA data
     */
    updateEMAData(id, period) {
        const indicator = this.indicators.get(id);
        if (!indicator) return;

        const symbol = this.chartManager.getCurrentSymbol();
        if (!symbol) return;

        window.ApiClient.getHistoricalBars(symbol, {
            timeframe: this.chartManager.getCurrentTimeframe(),
            limit: 1000
        }).then(response => {
            if (response && response.bars) {
                const emaData = window.TechnicalIndicators.calculateEMA(response.bars, period);
                indicator.series.setData(emaData);
            }
        }).catch(error => {
            console.error('Error updating EMA data:', error);
        });
    }

    /**
     * Update VWAP data
     */
    updateVWAPData() {
        const indicator = this.indicators.get('vwap');
        if (!indicator) return;

        const symbol = this.chartManager.getCurrentSymbol();
        if (!symbol) return;

        window.ApiClient.getHistoricalBars(symbol, {
            timeframe: this.chartManager.getCurrentTimeframe(),
            limit: 1000
        }).then(response => {
            if (response && response.bars) {
                const vwapData = window.TechnicalIndicators.calculateVWAP(response.bars);
                indicator.series.setData(vwapData);
            }
        }).catch(error => {
            console.error('Error updating VWAP data:', error);
        });
    }

    /**
     * Remove indicator by ID
     */
    removeIndicator(id) {
        const indicator = this.indicators.get(id);
        if (!indicator) return;

        if (indicator.type === 'rsi') {
            this.removeRSI();
        } else if (indicator.type === 'volume') {
            this.removeVolumeHistogram();
        } else {
            const chart = this.chartManager.getChart();
            chart.removeSeries(indicator.series);
            this.indicators.delete(id);
        }

        console.log(`Indicator ${id} removed`);
    }

    /**
     * Refresh all indicators (called when symbol or timeframe changes)
     */
    refreshAll() {
        for (const [id, indicator] of this.indicators) {
            if (indicator.type === 'sma') {
                this.updateSMAData(id, indicator.params.period);
            } else if (indicator.type === 'ema') {
                this.updateEMAData(id, indicator.params.period);
            } else if (indicator.type === 'vwap') {
                this.updateVWAPData();
            } else if (indicator.type === 'rsi') {
                this.updateRSIData(indicator.params.period);
            } else if (indicator.type === 'volume') {
                this.updateVolumeData();
            }
        }
    }

    /**
     * Sync time scales between main chart and indicator panes (volume, RSI)
     */
    syncTimeScales() {
        const mainChart = this.chartManager.getChart();
        if (!mainChart) return;

        // Sync main chart to volume chart
        if (this.volumeChart) {
            mainChart.timeScale().subscribeVisibleLogicalRangeChange((timeRange) => {
                if (timeRange && this.volumeChart) {
                    this.volumeChart.timeScale().setVisibleLogicalRange(timeRange);
                }
            });

            this.volumeChart.timeScale().subscribeVisibleLogicalRangeChange((timeRange) => {
                if (timeRange) {
                    mainChart.timeScale().setVisibleLogicalRange(timeRange);
                }
            });
        }

        // Sync main chart to RSI chart
        if (this.rsiChart) {
            mainChart.timeScale().subscribeVisibleLogicalRangeChange((timeRange) => {
                if (timeRange && this.rsiChart) {
                    this.rsiChart.timeScale().setVisibleLogicalRange(timeRange);
                }
            });

            this.rsiChart.timeScale().subscribeVisibleLogicalRangeChange((timeRange) => {
                if (timeRange) {
                    mainChart.timeScale().setVisibleLogicalRange(timeRange);
                }
            });
        }
    }

    /**
     * Get list of active indicators
     */
    getActiveIndicators() {
        return Array.from(this.indicators.keys());
    }

    /**
     * Check if indicator is active
     */
    isActive(id) {
        return this.indicators.has(id);
    }
}

// Make globally available
window.IndicatorsManager = IndicatorsManager;
