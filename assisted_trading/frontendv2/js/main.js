/**
 * Main Application Entry Point
 * Initializes all components and connects them together
 */

// Application state
const App = {
    initialized: false,
    currentSymbol: 'SPY',
    currentTimeframe: '5Min',
};

async function initializeApp() {
    // Prevent double initialization
    if (App.initialized) {
        console.log('App already initialized, skipping...');
        return;
    }

    // Mark as initialized immediately to prevent race conditions
    App.initialized = true;

    console.log('🎨 Initializing OptionsCanvas...');

    try {
        // Initialize Utils
        const eventBus = new EventBus();
        const settings = new Settings();
        const layoutManager = new LayoutManager();

        // Initialize Data Layer
        const apiClient = window.ApiClient;
        const dataStream = window.DataStream;

        // Initialize Chart
        // Use 'chartView' which is the actual div for the chart
        const chartManager = new ChartManager('chartView', dataStream);
        window.ChartManager = chartManager; // Make global

        // Await initialization
        await chartManager.initialize();

        // Timezone handling
        const tzSelect = document.getElementById('timezoneSelect');
        if (tzSelect) {
            // Restore saved timezone or default to Local/PST
            const savedTz = localStorage.getItem('trading_timezone') || 'America/Los_Angeles';
            tzSelect.value = savedTz;
            chartManager.setTimezone(savedTz);

            tzSelect.addEventListener('change', (e) => {
                const newTz = e.target.value;
                localStorage.setItem('trading_timezone', newTz);
                chartManager.setTimezone(newTz);
            });
        }

        // Initialize Trading Components
        const tradingPanel = new TradingPanel(apiClient, dataStream);
        window.TradingPanel = tradingPanel; // Make global

        // Initialize PositionTracker
        const positionTracker = new PositionTracker();
        window.PositionTracker = positionTracker; // Make global

        // Initialize OrderTracker
        const orderTracker = new OrderTracker();
        window.OrderTracker = orderTracker; // Make global

        // Initialize PriceLineManager
        const priceLineManager = new PriceLineManager(chartManager);
        window.PriceLineManager = priceLineManager; // Make global

        // Initialize IndicatorsManager
        const indicatorsManager = new IndicatorsManager(chartManager);
        window.IndicatorsManager = indicatorsManager; // Make global

        // Initialize DrawingManager
        const drawingManager = new DrawingManager(chartManager);
        window.DrawingManager = drawingManager; // Make global

        // Initialize DragHandles for draggable SL/TP lines (kept available for
        // existing-position management but NOT enabled by default — the chart
        // order panel owns SL/TP drag interaction now).
        const dragHandles = new DragHandles(chartManager, priceLineManager);
        window.DragHandles = dragHandles; // Make global

        // Initialize ChartTradingController (single source of truth for on-chart
        // trade interaction state). Loaded as ESM in index.html, exposed on window.
        const ChartTradingControllerCtor = window.ChartTradingController;
        const chartTradingController = new ChartTradingControllerCtor();
        window.ChartTradingController = chartTradingController;

        // Initialize BracketOrderDrawer for click-drag bracket orders
        const bracketOrderDrawer = new BracketOrderDrawer(chartManager, tradingPanel);
        window.BracketOrderDrawer = bracketOrderDrawer; // Make global

        // Initialize ContextMenu for right-click quick actions
        const contextMenu = new ContextMenu(chartManager, tradingPanel);
        window.ContextMenu = contextMenu; // Make global
        contextMenu.enable(); // Enable right-click menu

        // Initialize SmartDefaults for auto SL/TP calculation
        const smartDefaults = new SmartDefaults(chartManager);
        window.SmartDefaults = smartDefaults; // Make global

        // Initialize KeyboardShortcutManager
        const keyboardShortcuts = new KeyboardShortcutManager();
        window.KeyboardShortcuts = keyboardShortcuts; // Make global
        keyboardShortcuts.enable(); // Enable keyboard shortcuts

        // Initialize OrderPanelOnChart for TradingView-style floating panel
        const orderPanelOnChart = new OrderPanelOnChart(chartManager, tradingPanel, chartTradingController);
        window.OrderPanelOnChart = orderPanelOnChart; // Make global

        // Initialize PositionPanelOnChart for on-chart position display
        const positionPanelOnChart = new PositionPanelOnChart(chartManager);
        window.PositionPanelOnChart = positionPanelOnChart; // Make global

        // 4. Setup UI event handlers
        setupUIHandlers();

        // Check backend health (updates UI with BP and Status)
        await checkBackendHealth();

        // Initialize WebSocket for real-time updates
        await initializeWebSocket();

        // 5. Load initial data
        await loadInitialData();
        orderPanelOnChart.enable(); // Enable after chart data is available

        console.log('✅ Application initialized successfully!');

        // Show success message
        showNotification('Connected to trading server', 'success');

    } catch (error) {
        console.error('❌ Failed to initialize application:', error);
        showNotification('Failed to connect to trading server', 'error');
    }
}

/**
 * Check backend health
 */
async function checkBackendHealth() {
    console.log('Checking backend health...');

    try {
        const health = await window.ApiClient.healthCheck();
        console.log('Backend health:', health);

        // Load config and populate symbol dropdown
        const config = await window.ApiClient.getConfig();
        console.log('Config loaded:', config);

        const symbolSelect = document.getElementById('symbolSelect');
        if (symbolSelect && config.symbols && config.symbols.length > 0) {
            // Clear existing options
            symbolSelect.innerHTML = '';

            // Populate with symbols from config
            config.symbols.forEach(symbol => {
                const option = document.createElement('option');
                option.value = symbol;
                option.textContent = symbol;
                symbolSelect.appendChild(option);
            });

            console.log(`Populated ${config.symbols.length} symbols:`, config.symbols.join(', '));
        }

        const brokerInfo = await window.ApiClient.getBrokerInfo();
        console.log('Broker info:', brokerInfo);

        // Render the load-bearing broker pill (paper/live, account, mode badge).
        renderBrokerPill(brokerInfo);

        // Legacy side-panel broker label (kept for now — single source of truth
        // still comes from /api/broker/info).
        const brokerStatus = document.getElementById('brokerStatus');
        if (brokerStatus) {
            const brokerName = brokerStatus.querySelector('.broker-name');
            const connectionDot = brokerStatus.querySelector('.connection-dot');
            if (brokerName) brokerName.textContent = (brokerInfo.broker_type || '').replace('Broker', '');
            if (connectionDot) connectionDot.classList.add('connected');
        }

        // Update account info
        if (brokerInfo.account) {
            const buyingPowerEl = document.querySelector('.buying-power');
            if (buyingPowerEl) {
                const bp = brokerInfo.account.buying_power;
                buyingPowerEl.textContent = `BP: $${parseFloat(bp).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
            }
        }

        // Update market status indicator
        const marketStatus = document.getElementById('marketStatus');
        if (marketStatus) {
            const statusText = marketStatus.querySelector('.status-text');
            const statusDot = marketStatus.querySelector('.status-indicator');

            if (statusText) statusText.textContent = 'Connected';
            if (statusDot) {
                statusDot.style.backgroundColor = 'var(--accent-green, #0ecb81)';
                statusDot.classList.add('connected');
            }
        }

    } catch (error) {
        console.error('Backend health check failed:', error);
        throw error;
    }
}

/**
 * Render the broker pill (broker name, paper/live mode, account last-4)
 * and apply app-wide visual cues for live trading mode.
 */
function renderBrokerPill(brokerInfo) {
    const pill     = document.getElementById('brokerPill');
    const nameEl   = document.getElementById('brokerPillName');
    const modeEl   = document.getElementById('brokerPillMode');
    const acctEl   = document.getElementById('brokerPillAcct');
    if (!pill || !brokerInfo) return;

    const brokerName = (brokerInfo.broker_type || 'Broker').replace('Broker', '');
    const isPaper = !!brokerInfo.paper_trading;
    const acct = (brokerInfo.account && brokerInfo.account.account_number) || '';
    const last4 = acct ? acct.slice(-4) : '';

    nameEl.textContent = brokerName;
    modeEl.textContent = isPaper ? 'Paper' : 'Live';
    acctEl.textContent = last4 ? `…${last4}` : '';

    pill.classList.remove('paper', 'live');
    pill.classList.add(isPaper ? 'paper' : 'live');

    // Whole-app peripheral-vision cue + tab-title prefix when live.
    document.body.classList.toggle('live-mode', !isPaper);
    const baseTitle = 'OptionsCanvas';
    document.title = isPaper ? baseTitle : `[LIVE] ${baseTitle}`;

    // Wire popover (idempotent — safe to re-run on each refresh).
    if (!pill.dataset.bound) {
        pill.dataset.bound = '1';
        const pop = document.getElementById('brokerPopover');
        pill.addEventListener('click', (e) => {
            e.stopPropagation();
            pop.hidden = !pop.hidden;
        });
        document.addEventListener('click', (e) => {
            if (!pop.hidden && !pop.contains(e.target) && e.target !== pill) {
                pop.hidden = true;
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') pop.hidden = true;
        });
    }

    // Fill the popover.
    const setText = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    const fmt$ = (v) => (v == null ? '—' : `$${parseFloat(v).toLocaleString(undefined, { maximumFractionDigits: 2 })}`);
    setText('bpBroker', brokerName);
    setText('bpMode', isPaper ? 'Paper trading (no real money)' : 'LIVE — real money');
    setText('bpAccount', acct || '—');
    if (brokerInfo.account) {
        setText('bpBP', fmt$(brokerInfo.account.buying_power));
        setText('bpPV', fmt$(brokerInfo.account.portfolio_value));
        setText('bpStatus', brokerInfo.account.status || '—');
    }
}

/**
 * Initialize WebSocket connection
 */
async function initializeWebSocket() {
    console.log('Connecting to WebSocket...');

    const wsIndicator = document.getElementById('wsIndicator');

    try {
        await window.DataStream.connect();

        // Update WebSocket status on successful connect
        if (wsIndicator) {
            wsIndicator.classList.remove('disconnected', 'connecting');
            wsIndicator.classList.add('connected');
            wsIndicator.title = 'WebSocket: Connected';
        }

        // Listen for connection events
        window.EventBus.on('websocket:disconnected', () => {
            showNotification('WebSocket disconnected - reconnecting...', 'warning');
            if (wsIndicator) {
                wsIndicator.classList.remove('connected', 'connecting');
                wsIndicator.classList.add('disconnected');
                wsIndicator.title = 'WebSocket: Disconnected';
            }
        });

        window.EventBus.on('websocket:reconnecting', (attemptNumber) => {
            if (wsIndicator) {
                wsIndicator.classList.remove('connected', 'disconnected');
                wsIndicator.classList.add('connecting');
                wsIndicator.title = `WebSocket: Reconnecting (${attemptNumber})...`;
            }
        });

        window.EventBus.on('websocket:reconnected', () => {
            showNotification('WebSocket reconnected', 'success');
            if (wsIndicator) {
                wsIndicator.classList.remove('disconnected', 'connecting');
                wsIndicator.classList.add('connected');
                wsIndicator.title = 'WebSocket: Connected';
            }
        });

        window.EventBus.on('websocket:reconnect_failed', () => {
            showNotification('WebSocket connection failed - using polling', 'error');
            if (wsIndicator) {
                wsIndicator.classList.remove('connected', 'connecting');
                wsIndicator.classList.add('disconnected');
                wsIndicator.title = 'WebSocket: Failed';
            }
        });

        // Listen for bar updates
        window.EventBus.on('chart:bar_update', (data) => {
            if (window.ChartManager) {
                window.ChartManager.updateBar(data);
            }
            // Update volume bar if volume indicator is active
            if (window.IndicatorsManager) {
                window.IndicatorsManager.updateVolumeBar(data);
            }
        });

    } catch (error) {
        console.error('WebSocket connection failed:', error);
        // Continue anyway - polling can work without WebSocket
    }
}

/**
 * Initialize all components
 */
function initializeComponents() {
    console.log('Initializing components...');

    // Initialize ChartManager
    window.ChartManager = new ChartManager('chartView');

    // Initialize PriceLineManager
    window.PriceLineManager = new PriceLineManager(window.ChartManager);

    // NOTE: DragHandles is owned by the main init path (initializeApp). It is
    // not re-instantiated here to avoid shadowing the configured instance and
    // attaching duplicate pointer listeners to the chart container.

    // Initialize TradingPanel
    window.TradingPanel = new TradingPanel();

    // Initialize PositionTracker
    window.PositionTracker = new PositionTracker();

    // Initialize OrderTracker
    console.log('Main: Initializing OrderTracker...');
    window.OrderTracker = new OrderTracker();

    console.log('%c✅ ALL COMPONENTS INITIALIZED', 'color: #0ecb81; font-weight: bold;');
}

/**
 * Setup UI event handlers
 */
function setupUIHandlers() {
    console.log('Setting up UI handlers...');

    // Symbol selector
    const symbolSelect = document.getElementById('symbolSelect');
    if (symbolSelect) {
        symbolSelect.addEventListener('change', (e) => {
            const symbol = e.target.value;
            App.currentSymbol = symbol;

            // Clear previous symbol's price lines and panels
            if (window.PriceLineManager) window.PriceLineManager.clearAll();
            if (window.PositionPanelOnChart) window.PositionPanelOnChart.clearAll();

            window.ChartManager.loadSymbol(symbol);
        });
    }

    // Timeframe buttons
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const timeframe = e.target.dataset.tf;

            // Update active state
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            e.target.classList.add('active');

            // Change chart timeframe
            App.currentTimeframe = timeframe;
            window.ChartManager.changeTimeframe(timeframe);
        });
    });

    // Settings button
    const settingsBtn = document.getElementById('settingsBtn');
    if (settingsBtn) {
        settingsBtn.addEventListener('click', () => {
            window.openSettings();
        });
    }

    // Chart toolbar buttons
    const crosshairBtn = document.getElementById('crosshairBtn');
    const hlineBtn = document.getElementById('hlineBtn');
    const trendlineBtn = document.getElementById('trendlineBtn');
    const clearDrawingsBtn = document.getElementById('clearDrawingsBtn');

    // Crosshair button
    crosshairBtn?.addEventListener('click', () => {
        if (window.DrawingManager) {
            window.DrawingManager.setTool(null);
        }
        document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
        crosshairBtn.classList.add('active');
    });

    // Horizontal line button
    hlineBtn?.addEventListener('click', () => {
        if (window.DrawingManager) {
            window.DrawingManager.setTool('hline');
        }
        document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
        hlineBtn.classList.add('active');
    });

    // Trend line button
    trendlineBtn?.addEventListener('click', () => {
        if (window.DrawingManager) {
            window.DrawingManager.setTool('trendline');
        }
        document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
        trendlineBtn.classList.add('active');
    });

    // Clear drawings button
    clearDrawingsBtn?.addEventListener('click', () => {
        if (window.DrawingManager) {
            window.DrawingManager.clearAll();
        }
    });

    // Bracket order button — exclusive with on-chart order panel to avoid
    // competing pointer handlers on the same chart container.
    const bracketBtn = document.getElementById('bracketBtn');
    bracketBtn?.addEventListener('click', () => {
        if (window.BracketOrderDrawer) {
            if (window.BracketOrderDrawer.enabled) {
                window.BracketOrderDrawer.disable();
                window.OrderPanelOnChart?.enable();
                bracketBtn.classList.remove('active');
            } else {
                window.OrderPanelOnChart?.disable();
                window.BracketOrderDrawer.enable();
                bracketBtn.classList.add('active');
            }
        }
    });

    // Help button (keyboard shortcuts)
    const helpBtn = document.getElementById('helpBtn');
    helpBtn?.addEventListener('click', () => {
        if (window.KeyboardShortcuts) {
            window.KeyboardShortcuts.showShortcutsHelp();
        }
    });

    // Smart defaults button
    const smartDefaultsBtn = document.getElementById('smartDefaultsBtn');
    smartDefaultsBtn?.addEventListener('click', () => {
        if (window.SmartDefaults && window.TradingPanel) {
            const contractType = window.TradingPanel.contractType;
            window.SmartDefaults.applySmartDefaults(contractType);
        }
    });

    // Order panel on chart button
    const orderPanelBtn = document.getElementById('orderPanelBtn');
    orderPanelBtn?.addEventListener('click', () => {
        if (window.OrderPanelOnChart) {
            if (window.OrderPanelOnChart.enabled) {
                window.OrderPanelOnChart.disable();
                orderPanelBtn.classList.remove('active');
            } else {
                window.OrderPanelOnChart.enable();
                orderPanelBtn.classList.add('active');
            }
        }
    });

    // ESC key to deselect drawing tool, Delete key to remove selected drawing
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            if (window.DrawingManager) {
                window.DrawingManager.setTool(null);
            }
            document.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
            if (crosshairBtn) {
                crosshairBtn.classList.add('active');
            }
        } else if (e.key === 'Delete' || e.key === 'Backspace') {
            // Delete the currently selected drawing
            if (window.DrawingManager) {
                const deleted = window.DrawingManager.deleteSelected();
                if (deleted) {
                    showNotification('Drawing deleted', 'info');
                }
            }
        }
    });

    // Set crosshair as default active tool
    if (crosshairBtn) {
        crosshairBtn.classList.add('active');
    }

    // Indicators dropdown
    const indicatorsBtn = document.getElementById('indicatorsBtn');
    const indicatorsMenu = document.getElementById('indicatorsMenu');

    console.log('Setting up indicators dropdown...', { indicatorsBtn, indicatorsMenu });

    if (indicatorsBtn && indicatorsMenu) {
        let isTogglingNow = false;

        // Toggle dropdown
        indicatorsBtn.addEventListener('click', (e) => {
            console.log('=== INDICATOR BUTTON CLICKED ===');
            e.preventDefault();
            e.stopPropagation();

            isTogglingNow = true;
            const wasShowing = indicatorsMenu.classList.contains('show');
            indicatorsMenu.classList.toggle('show');
            const isShowing = indicatorsMenu.classList.contains('show');

            console.log('Dropdown toggle:', { wasShowing, isShowing, classList: Array.from(indicatorsMenu.classList) });

            // Reset flag after this event cycle completes
            setTimeout(() => {
                isTogglingNow = false;
            }, 0);
        });

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            // Don't run if we're currently toggling
            if (isTogglingNow) {
                return;
            }

            // Skip if clicking the button or menu
            if (indicatorsBtn.contains(e.target) || indicatorsMenu.contains(e.target)) {
                return;
            }

            // Close the menu if it's open
            if (indicatorsMenu.classList.contains('show')) {
                indicatorsMenu.classList.remove('show');
            }
        });

        // Handle indicator checkbox changes
        indicatorsMenu.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                e.stopPropagation();
                const indicatorId = checkbox.dataset.indicator;
                const isChecked = checkbox.checked;

                handleIndicatorToggle(indicatorId, isChecked);
            });
        });
    }

    console.log('UI handlers setup complete');
}

/**
 * Handle indicator toggle
 */
function handleIndicatorToggle(indicatorId, isActive) {
    if (!window.IndicatorsManager) return;

    if (isActive) {
        // Add indicator
        switch (indicatorId) {
            case 'volume':
                window.IndicatorsManager.addVolumeHistogram();
                break;
            case 'vwap':
                window.IndicatorsManager.addVWAP();
                break;
            case 'sma_200':
                window.IndicatorsManager.addSMA(200, '#2196F3', 2);  // Blue, dashed
                break;
            case 'ema_8':
                window.IndicatorsManager.addEMA(8, '#FFC107');  // Yellow
                break;
            case 'ema_21':
                window.IndicatorsManager.addEMA(21, '#0ecb81');  // Green
                break;
            case 'rsi':
                window.IndicatorsManager.addRSI(14);
                break;
        }
    } else {
        // Remove indicator
        window.IndicatorsManager.removeIndicator(indicatorId);
    }
}

/**
 * Load initial data
 */
async function loadInitialData() {
    console.log('Loading initial data...');

    // Get default symbol from settings
    App.currentSymbol = window.Settings.get('defaultSymbol') || 'SPY';
    App.currentTimeframe = window.Settings.get('defaultTimeframe') || '5Min';

    // Set symbol selector
    const symbolSelect = document.getElementById('symbolSelect');
    if (symbolSelect) {
        symbolSelect.value = App.currentSymbol;
    }

    // Set timeframe button
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tf === App.currentTimeframe);
    });

    // Load chart data
    await window.ChartManager.loadSymbol(App.currentSymbol, App.currentTimeframe);

    // Refresh indicators after symbol load
    window.EventBus.on('chart:symbol_loaded', () => {
        if (window.IndicatorsManager) {
            window.IndicatorsManager.refreshAll();
        }
    });

    console.log('Initial data loaded');
    // Force resize to ensure chart fits container
    window.dispatchEvent(new Event('resize'));
}

/**
 * Show notification
 * @param {string} message - Notification message
 * @param {string} type - Type: 'success', 'error', 'warning', 'info'
 */
function showNotification(message, type = 'info') {
    console.log(`[${type.toUpperCase()}] ${message}`);

    // Use toast notification system
    if (window.Toast) {
        window.Toast.show(message, type, 3000);
    }
}

/**
 * Handle errors globally
 */
window.addEventListener('error', (event) => {
    console.error('Global error:', event.error);
});

window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
});

/**
 * Cleanup on page unload
 */
window.addEventListener('beforeunload', () => {
    console.log('Cleaning up...');

    // Stop position polling
    if (window.PositionTracker) {
        window.PositionTracker.stopPolling();
    }

    // Disconnect WebSocket
    if (window.DataStream) {
        window.DataStream.disconnect();
    }

    // Destroy chart
    if (window.ChartManager) {
        window.ChartManager.destroy();
    }
});

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApp);
} else {
    // DOM already loaded
    initializeApp();
}

// Export for debugging
window.App = App;
