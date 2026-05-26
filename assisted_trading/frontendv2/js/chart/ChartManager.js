/**
 * ChartManager - Manages TradingView Lightweight Charts instance
 * Handles chart creation, data loading, and real-time updates
 * @version 1.1 - Fixed v5.0.0 compatibility
 */

class ChartManager {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.chart = null;
        this.candlestickSeries = null;
        this.currentSymbol = null;
        this.currentTimeframe = '5Min';
        this.isLoading = false;

        // Don't auto-initialize, let main.js call it
    }

    /**
     * Initialize chart
     */
    async initialize() {
        if (!this.container) {
            console.error(`Container #${this.containerId} not found`);
            return;
        }

        console.log(`Initializing chart in #${this.containerId}. Dimensions: ${this.container.clientWidth}x${this.container.clientHeight}`);

        // Clear any existing content
        this.container.innerHTML = '';

        // Helper to safely get color or default
        const getColor = (varName, defaultColor) => {
            const val = getComputedStyle(document.body).getPropertyValue(varName).trim();
            return val || defaultColor;
        };

        // Create chart instance
        this.chart = LightweightCharts.createChart(this.container, {
            width: this.container.clientWidth || 800,
            height: this.container.clientHeight || 500,
            autoSize: true,
            layout: {
                background: { type: 'solid', color: getColor('--primary-bg', '#0f1419') },
                textColor: getColor('--text-secondary', '#a8aeb8'),
            },
            grid: {
                vertLines: { color: getColor('--border', '#2b3139') },
                horzLines: { color: getColor('--border', '#2b3139') },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    color: '#a8aeb8',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                },
                horzLine: {
                    color: '#a8aeb8',
                    width: 1,
                    style: LightweightCharts.LineStyle.Dashed,
                },
            },
            rightPriceScale: {
                borderColor: getColor('--border', '#2b3139'),
            },
            timeScale: {
                borderColor: getColor('--border', '#2b3139'),
                timeVisible: true,
                secondsVisible: false,
            },
        });

        // Add candlestick series
        // v5.0.0 API uses addSeries(SeriesType, options)
        this.candlestickSeries = this.chart.addSeries(LightweightCharts.CandlestickSeries, {
            upColor: '#0ecb81',
            downColor: '#f6465d',
            borderUpColor: '#0ecb81',
            borderDownColor: '#f6465d',
            wickUpColor: '#0ecb81',
            wickDownColor: '#f6465d',
        });

        // Handle window resize
        window.addEventListener('resize', () => {
            this.chart.applyOptions({
                width: this.container.clientWidth,
                height: this.container.clientHeight,
            });
        });

        // Handle crosshair move (show price info)
        this.chart.subscribeCrosshairMove((param) => {
            if (param.time) {
                const price = param.seriesData.get(this.candlestickSeries);
                if (price) {
                    this.updatePriceInfo(price.close);
                }
            }
        });

        console.log('Chart initialized');
    }

    /**
     * Set chart timezone
     * @param {string} timezone - Timezone identifier
     */
    setTimezone(timezone) {
        if (!this.chart) return;

        this.currentTimezone = timezone;

        const timeFormatter = (time) => {
            try {
                const date = new Date(time * 1000);
                const options = {
                    hour: '2-digit',
                    minute: '2-digit',
                    hour12: false,
                    timeZone: timezone === 'local' ? undefined : timezone
                };
                return new Intl.DateTimeFormat('en-US', options).format(date);
            } catch (e) {
                console.warn('Time format error:', e);
                return '';
            }
        };

        this.chart.applyOptions({
            localization: {
                timeFormatter: timeFormatter,
            },
            timeScale: {
                tickMarkFormatter: (time, tickMarkType, locale) => {
                    try {
                        const date = new Date(time * 1000);
                        const options = {
                            hour: '2-digit',
                            minute: '2-digit',
                            hour12: false,
                            timeZone: timezone === 'local' ? undefined : timezone
                        };
                        return new Intl.DateTimeFormat('en-US', options).format(date);
                    } catch (e) {
                        return '';
                    }
                }
            }
        });
    }

    /**
     * Load chart data for a symbol
     * @param {string} symbol - Symbol to load
     * @param {string} timeframe - Timeframe
     */
    async loadSymbol(symbol, timeframe = null) {
        if (this.isLoading) {
            console.log('Chart is already loading...');
            return;
        }

        if (timeframe) {
            this.currentTimeframe = timeframe;
        }

        this.isLoading = true;

        console.log(`Loading ${symbol} ${this.currentTimeframe} data...`);

        try {
            // Unsubscribe from previous symbol BEFORE updating currentSymbol
            if (this.currentSymbol && this.currentSymbol !== symbol) {
                window.DataStream.unsubscribeChart(this.currentSymbol, this.currentTimeframe);
            }

            // NOW update the current symbol
            this.currentSymbol = symbol;

            // Fetch historical data
            const response = await window.ApiClient.getHistoricalBars(symbol, {
                timeframe: this.currentTimeframe,
                limit: 1000
            });

            if (!response || !response.bars) {
                throw new Error('No data received');
            }

            console.log(`ChartManager: Received ${response.bars.length} bars for ${symbol}`);

            // Clear existing data
            console.log(`ChartManager: Clearing existing chart data...`);
            this.candlestickSeries.setData([]);

            // Set new data
            console.log(`ChartManager: Setting ${response.bars.length} bars for ${symbol}...`);
            this.candlestickSeries.setData(response.bars);

            // Verify data was set
            const seriesData = this.candlestickSeries.data();
            console.log(`ChartManager: Series now has ${seriesData.length} bars after setData`);

            // Fit content to show all data. timeScale().fitContent() only
            // resets the TIME axis. The PRICE axis retains the previous
            // symbol's range — switching from SPY ($750) to AMZN ($268)
            // leaves the price axis at 744-755, so all AMZN bars end up
            // off-screen and the chart looks blank. Force the right price
            // scale back into autoScale mode so it re-fits to the new data.
            console.log(`ChartManager: Fitting content...`);
            this.chart.timeScale().fitContent();
            try {
                this.chart.priceScale('right').applyOptions({ autoScale: true });
            } catch (e) {
                // Some Lightweight Charts versions expose this differently;
                // not catastrophic if it fails, but log so we know.
                console.warn('ChartManager: could not autoScale price axis:', e);
            }

            console.log(`Loaded ${response.bars.length} bars for ${symbol}. Range: ${new Date(response.bars[0].time * 1000).toISOString()} to ${new Date(response.bars[response.bars.length - 1].time * 1000).toISOString()}`);

            // Subscribe to real-time updates
            if (window.DataStream.isConnected()) {
                window.DataStream.subscribeChart(symbol, this.currentTimeframe);
            }

            // Emit event
            window.EventBus.emit('chart:symbol_loaded', {
                symbol: symbol,
                timeframe: this.currentTimeframe,
                bars: response.bars
            });

            // Update price info
            if (response.bars.length > 0) {
                const lastBar = response.bars[response.bars.length - 1];
                this.updatePriceInfo(lastBar.close);
            }

        } catch (error) {
            console.error('Error loading chart data:', error);
            window.EventBus.emit('chart:error', { symbol, error });
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Update chart with new bar data (real-time)
     * @param {Object} barData - Bar data from WebSocket
     */
    updateBar(barData) {
        if (!this.candlestickSeries) {
            return;
        }

        // Only update if it's for the current symbol
        if (barData.symbol !== this.currentSymbol || barData.timeframe !== this.currentTimeframe) {
            return;
        }

        // Update the bar
        this.candlestickSeries.update(barData.bar);

        // Update price info
        this.updatePriceInfo(barData.bar.close);
    }

    /**
     * Update price info display
     * @param {number} price - Current price
     */
    updatePriceInfo(price) {
        const priceElement = document.querySelector('.chart-price');
        if (priceElement) {
            priceElement.textContent = `$${price.toFixed(2)}`;
        }
    }

    /**
     * Change timeframe
     * @param {string} timeframe - New timeframe
     */
    changeTimeframe(timeframe) {
        if (this.currentTimeframe === timeframe) {
            return;
        }

        console.log(`Changing timeframe to ${timeframe}`);

        this.currentTimeframe = timeframe;

        // Reload chart data
        if (this.currentSymbol) {
            this.loadSymbol(this.currentSymbol, timeframe);
        }
    }

    /**
     * Get chart instance
     * @returns {Object} Chart instance
     */
    getChart() {
        return this.chart;
    }

    /**
     * Get candlestick series
     * @returns {Object} Candlestick series
     */
    getSeries() {
        return this.candlestickSeries;
    }

    /**
     * Get current symbol
     * @returns {string} Current symbol
     */
    getCurrentSymbol() {
        return this.currentSymbol;
    }

    /**
     * Get current timeframe
     * @returns {string} Current timeframe
     */
    getCurrentTimeframe() {
        return this.currentTimeframe;
    }

    /**
     * Destroy chart
     */
    destroy() {
        if (this.chart) {
            this.chart.remove();
            this.chart = null;
            this.candlestickSeries = null;
        }
    }
}

// Create global instance (initialized in main.js)
window.ChartManager = null;
