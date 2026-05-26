/**
 * DataStream - WebSocket connection for real-time chart data
 */

class DataStream {
    constructor(url = window.location.origin) {
        this.url = url;
        this.socket = null;
        this.subscriptions = new Set();
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000;  // Start with 1 second
        this.connected = false;
    }

    /**
     * Connect to WebSocket server
     * @returns {Promise<void>}
     */
    connect() {
        return new Promise((resolve, reject) => {
            console.log('Connecting to WebSocket...', this.url);

            this.socket = io(this.url, {
                transports: ['websocket', 'polling'],
                reconnection: true,
                reconnectionAttempts: this.maxReconnectAttempts,
                reconnectionDelay: this.reconnectDelay,
                reconnectionDelayMax: 5000
            });

            // Connection established
            this.socket.on('connect', () => {
                console.log('WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;

                // Emit connection event
                window.EventBus.emit('websocket:connected');

                // Re-subscribe to all previous subscriptions
                this.resubscribe();

                resolve();
            });

            // Connection error
            this.socket.on('connect_error', (error) => {
                console.error('WebSocket connection error:', error);
                this.connected = false;
                window.EventBus.emit('websocket:error', error);
            });

            // Disconnection
            this.socket.on('disconnect', (reason) => {
                console.log('WebSocket disconnected:', reason);
                this.connected = false;
                window.EventBus.emit('websocket:disconnected', reason);
            });

            // Reconnection attempt
            this.socket.on('reconnect_attempt', (attemptNumber) => {
                console.log(`WebSocket reconnection attempt ${attemptNumber}...`);
                this.reconnectAttempts = attemptNumber;
                window.EventBus.emit('websocket:reconnecting', attemptNumber);
            });

            // Reconnection successful
            this.socket.on('reconnect', (attemptNumber) => {
                console.log(`WebSocket reconnected after ${attemptNumber} attempts`);
                this.connected = true;
                this.reconnectAttempts = 0;
                window.EventBus.emit('websocket:reconnected');
            });

            // Reconnection failed
            this.socket.on('reconnect_failed', () => {
                console.error('WebSocket reconnection failed');
                this.connected = false;
                window.EventBus.emit('websocket:reconnect_failed');
                reject(new Error('Failed to reconnect to WebSocket'));
            });

            // Server events
            this.socket.on('connection_established', (data) => {
                console.log('Connection established:', data);
            });

            this.socket.on('error', (data) => {
                console.error('WebSocket error:', data);
                window.EventBus.emit('websocket:server_error', data);
            });

            this.socket.on('subscribed', (data) => {
                console.log('Subscribed:', data);
                window.EventBus.emit('chart:subscribed', data);
            });

            this.socket.on('unsubscribed', (data) => {
                console.log('Unsubscribed:', data);
                window.EventBus.emit('chart:unsubscribed', data);
            });

            // Bar updates
            this.socket.on('bar_update', (data) => {
                // Emit event for chart to handle
                window.EventBus.emit('chart:bar_update', data);
            });

            // Position updates
            this.socket.on('position_closed', (data) => {
                console.log('Position closed:', data);
                window.EventBus.emit('position:closed', data);
            });
        });
    }

    /**
     * Disconnect from WebSocket server
     */
    disconnect() {
        if (this.socket) {
            this.subscriptions.clear();
            this.socket.disconnect();
            this.socket = null;
            this.connected = false;
            console.log('WebSocket disconnected');
        }
    }

    /**
     * Subscribe to chart updates for a symbol
     * @param {string} symbol - Symbol to subscribe to
     * @param {string} timeframe - Timeframe (default '1Min')
     */
    subscribeChart(symbol, timeframe = '1Min') {
        if (!this.socket || !this.connected) {
            console.warn('Cannot subscribe: WebSocket not connected');
            return;
        }

        const key = `${symbol}_${timeframe}`;

        if (this.subscriptions.has(key)) {
            console.log(`Already subscribed to ${key}`);
            return;
        }

        console.log(`Subscribing to ${symbol} ${timeframe}...`);

        this.socket.emit('subscribe_chart', {
            symbol: symbol,
            timeframe: timeframe
        });

        this.subscriptions.add(key);
    }

    /**
     * Unsubscribe from chart updates
     * @param {string} symbol - Symbol to unsubscribe from
     * @param {string} timeframe - Timeframe (default '1Min')
     */
    unsubscribeChart(symbol, timeframe = '1Min') {
        const key = `${symbol}_${timeframe}`;
        if (!this.subscriptions.has(key)) {
            return;
        }

        // ALWAYS remove from the local set, even if the WebSocket is
        // currently disconnected. If we skip this when disconnected, the
        // entry sticks around in `this.subscriptions` and gets re-emitted
        // by resubscribe() on the next reconnect — so the user switches
        // symbols during a connection blip, the backend never hears the
        // unsubscribe, and on reconnect it gets re-subscribed forever.
        this.subscriptions.delete(key);

        if (!this.socket || !this.connected) {
            // Backend won't be told now; it'll catch up on the client's
            // next disconnect (handle_disconnect cleans streaming_symbols).
            return;
        }

        console.log(`Unsubscribing from ${symbol} ${timeframe}...`);
        this.socket.emit('unsubscribe_chart', {
            symbol: symbol,
            timeframe: timeframe
        });
    }

    /**
     * Re-subscribe to all previous subscriptions (after reconnect)
     */
    resubscribe() {
        console.log('Re-subscribing to all streams...');

        this.subscriptions.forEach(key => {
            const [symbol, timeframe] = key.split('_');
            this.socket.emit('subscribe_chart', {
                symbol: symbol,
                timeframe: timeframe
            });
        });
    }

    /**
     * Check if connected
     * @returns {boolean} Connection status
     */
    isConnected() {
        return this.connected;
    }
}

// Create singleton instance
window.DataStream = new DataStream();
