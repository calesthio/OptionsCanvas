-- Assisted Trading Database Schema
-- SQLite database for tracking orders, positions, and trading state

-- Orders table: tracks all order submissions and their lifecycle
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT UNIQUE NOT NULL,  -- UUID or broker order ID
    broker_order_id TEXT,  -- Broker's order ID (once placed)

    -- Order details
    symbol TEXT NOT NULL,  -- Underlying symbol (SPY, QQQ)
    option_symbol TEXT,  -- Option contract symbol (filled after order placed)
    contract_type TEXT NOT NULL,  -- CALL or PUT
    dte INTEGER NOT NULL,  -- Days to expiration
    strike REAL,  -- Strike price (filled after order placed)

    -- Order parameters
    order_type TEXT NOT NULL,  -- equity_market, equity_limit
    equity_limit_price REAL,  -- For equity_limit orders
    option_order_type TEXT DEFAULT 'limit',  -- 'market' or 'limit' for the option leg
    position_size REAL NOT NULL,  -- Position size in dollars
    requested_qty INTEGER,  -- Number of contracts requested

    -- Stop loss / Take profit
    stop_loss_price REAL,
    take_profit_price REAL,

    -- Order lifecycle
    status TEXT NOT NULL,  -- pending, monitoring_equity, pending_fill, filled, rejected, canceled, timeout
    submit_time TEXT NOT NULL,  -- ISO timestamp
    fill_time TEXT,  -- ISO timestamp when filled
    cancel_time TEXT,  -- ISO timestamp when canceled

    -- Fill details
    filled_qty INTEGER DEFAULT 0,
    filled_avg_price REAL,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Positions table: tracks CURRENT open positions (source of truth: broker)
-- This is a cache/augmentation of broker positions with our metadata
CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Position identification
    option_symbol TEXT UNIQUE NOT NULL,  -- The option contract symbol
    symbol TEXT NOT NULL,  -- Underlying symbol

    -- Contract details
    contract_type TEXT NOT NULL,  -- CALL or PUT
    strike REAL NOT NULL,
    dte INTEGER,  -- Days to expiration at entry

    -- Position sizing
    total_contracts INTEGER NOT NULL,  -- Original size
    remaining_contracts INTEGER NOT NULL,  -- Current size (after partial closes)

    -- Entry details
    entry_price REAL NOT NULL,  -- Average entry price per share
    entry_time TEXT NOT NULL,  -- ISO timestamp
    underlying_entry_price REAL,  -- Underlying price at entry

    -- Risk management
    stop_loss_price REAL,
    take_profit_price REAL,

    -- P&L tracking
    realized_pnl REAL DEFAULT 0.0,

    -- Tracking
    is_tracked BOOLEAN DEFAULT 1,  -- 1 if opened via platform, 0 if external
    source_order_id TEXT,  -- Reference to orders table

    -- Metadata
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (source_order_id) REFERENCES orders(order_id)
);

-- Position closes table: tracks all position exits (full or partial)
CREATE TABLE IF NOT EXISTS position_closes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    option_symbol TEXT NOT NULL,
    contracts_closed INTEGER NOT NULL,
    exit_price REAL NOT NULL,
    exit_time TEXT NOT NULL,
    realized_pnl REAL NOT NULL,

    -- Metadata
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (option_symbol) REFERENCES positions(option_symbol)
);

-- Trading journal: aggregated daily performance
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT UNIQUE NOT NULL,  -- YYYY-MM-DD

    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    losing_trades INTEGER DEFAULT 0,

    gross_profit REAL DEFAULT 0.0,
    gross_loss REAL DEFAULT 0.0,
    net_pnl REAL DEFAULT 0.0,

    largest_win REAL DEFAULT 0.0,
    largest_loss REAL DEFAULT 0.0,

    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Supported symbols table: tracks which symbols are enabled for trading.
-- Option chain details (expirations, strikes, increments) come from the broker API at runtime.
CREATE TABLE IF NOT EXISTS supported_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL UNIQUE,
    is_active BOOLEAN DEFAULT 1,
    added_date TEXT DEFAULT CURRENT_TIMESTAMP,
    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_submit_time ON orders(submit_time);
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_option_symbol ON positions(option_symbol);
CREATE INDEX IF NOT EXISTS idx_position_closes_option_symbol ON position_closes(option_symbol);
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(date);
CREATE INDEX IF NOT EXISTS idx_supported_symbols_active ON supported_symbols(symbol, is_active);

-- Triggers to auto-update updated_at timestamps
CREATE TRIGGER IF NOT EXISTS update_orders_timestamp
AFTER UPDATE ON orders
BEGIN
    UPDATE orders SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_positions_timestamp
AFTER UPDATE ON positions
BEGIN
    UPDATE positions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_journal_timestamp
AFTER UPDATE ON journal_entries
BEGIN
    UPDATE journal_entries SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_supported_symbols_timestamp
AFTER UPDATE ON supported_symbols
BEGIN
    UPDATE supported_symbols SET last_updated = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
