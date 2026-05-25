"""
Database Manager for Assisted Trading
Handles SQLite connection, migrations, and CRUD operations
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQLite database connection and operations"""

    def __init__(self, db_path: str):
        """
        Initialize database manager

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = None
        self._initialize_database()

    def _initialize_database(self):
        """Initialize database and run migrations"""
        logger.info(f"Initializing database at {self.db_path}")

        # Create database and tables
        with self.get_connection() as conn:
            schema_path = Path(__file__).parent / 'schema.sql'
            with open(schema_path, 'r') as f:
                schema_sql = f.read()

            conn.executescript(schema_sql)
            conn.commit()

        # Migrate old supported_symbols schema if needed
        self._migrate_supported_symbols()
        # Backfill new columns on the orders table for existing DBs.
        self._migrate_orders()

        logger.info("Database initialized successfully")

    def _migrate_orders(self):
        """
        Add columns introduced after the initial schema. Idempotent — only
        adds a column when it's missing.

        Tracked columns:
          - option_order_type TEXT DEFAULT 'limit'  (added 2026-05-24)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(orders)")
            cols = {row[1] for row in cursor.fetchall()}

            if 'option_order_type' not in cols:
                logger.info("Adding orders.option_order_type column (default 'limit')")
                cursor.execute(
                    "ALTER TABLE orders ADD COLUMN option_order_type TEXT DEFAULT 'limit'"
                )
                conn.commit()

    def _migrate_supported_symbols(self):
        """
        Migrate supported_symbols table from old schema (with asset_type,
        expiration_frequency, etc.) to new simplified schema.
        Idempotent — skips if already migrated.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(supported_symbols)")
            columns = {row[1] for row in cursor.fetchall()}

            # If old columns exist, migrate
            if 'asset_type' not in columns:
                logger.info("supported_symbols already has new schema, skipping migration")
                return

            logger.info("Migrating supported_symbols table to simplified schema...")

            cursor.executescript("""
                -- Create new table with simplified schema
                CREATE TABLE IF NOT EXISTS supported_symbols_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL UNIQUE,
                    is_active BOOLEAN DEFAULT 1,
                    added_date TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                    notes TEXT
                );

                -- Copy data from old table
                INSERT OR IGNORE INTO supported_symbols_new (symbol, is_active, added_date, last_updated, notes)
                SELECT symbol, is_active, added_date, last_updated, notes
                FROM supported_symbols;

                -- Drop old table and rename new one
                DROP TABLE supported_symbols;
                ALTER TABLE supported_symbols_new RENAME TO supported_symbols;

                -- Recreate index
                CREATE INDEX IF NOT EXISTS idx_supported_symbols_active
                ON supported_symbols(symbol, is_active);
            """)
            conn.commit()
            logger.info("Migration complete: supported_symbols simplified")

    @contextmanager
    def get_connection(self):
        """
        Get database connection context manager

        Usage:
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(...)
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row  # Return rows as dict-like objects
        try:
            yield conn
        finally:
            conn.close()

    def execute_query(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """
        Execute SELECT query and return results

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of result rows as dictionaries
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]

    def execute_update(self, query: str, params: tuple = ()) -> int:
        """
        Execute INSERT/UPDATE/DELETE query

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Number of rows affected
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.rowcount

    def execute_insert(self, query: str, params: tuple = ()) -> int:
        """
        Execute INSERT query and return last row ID

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            Last inserted row ID
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid

    # ========== Order Operations ==========

    def create_order(self, order_data: Dict[str, Any]) -> str:
        """
        Create new order record

        Args:
            order_data: Order details dictionary

        Returns:
            order_id
        """
        query = """
            INSERT INTO orders (
                order_id, symbol, contract_type, dte, order_type,
                equity_limit_price, option_order_type,
                position_size, stop_loss_price, take_profit_price,
                status, submit_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            order_data['order_id'],
            order_data['symbol'],
            order_data['contract_type'],
            order_data['dte'],
            order_data['order_type'],
            order_data.get('equity_limit_price'),
            order_data.get('option_order_type', 'limit'),
            order_data['position_size'],
            order_data.get('stop_loss_price'),
            order_data.get('take_profit_price'),
            order_data['status'],
            order_data['submit_time']
        )

        self.execute_insert(query, params)
        return order_data['order_id']

    def update_order(self, order_id: str, updates: Dict[str, Any]) -> int:
        """Update order with new data"""
        # Build dynamic UPDATE query
        set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
        query = f"UPDATE orders SET {set_clause} WHERE order_id = ?"
        params = tuple(updates.values()) + (order_id,)

        return self.execute_update(query, params)

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order by ID"""
        query = "SELECT * FROM orders WHERE order_id = ?"
        results = self.execute_query(query, (order_id,))
        return results[0] if results else None

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get all pending orders"""
        query = """
            SELECT * FROM orders
            WHERE status IN ('pending', 'monitoring_equity', 'pending_fill')
            ORDER BY submit_time ASC
        """
        return self.execute_query(query)

    def get_pending_close_orders(self) -> List[Dict[str, Any]]:
        """Get all close orders awaiting broker confirmation."""
        query = """
            SELECT * FROM orders
            WHERE status = 'pending_close'
            ORDER BY submit_time ASC
        """
        return self.execute_query(query)

    # ========== Position Operations ==========

    def create_position(self, position_data: Dict[str, Any]) -> int:
        """Create new position record"""
        query = """
            INSERT INTO positions (
                option_symbol, symbol, contract_type, strike, dte,
                total_contracts, remaining_contracts, entry_price, entry_time,
                underlying_entry_price, stop_loss_price, take_profit_price,
                is_tracked, source_order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            position_data['option_symbol'],
            position_data['symbol'],
            position_data['contract_type'],
            position_data['strike'],
            position_data.get('dte'),
            position_data['total_contracts'],
            position_data['remaining_contracts'],
            position_data['entry_price'],
            position_data['entry_time'],
            position_data.get('underlying_entry_price'),
            position_data.get('stop_loss_price'),
            position_data.get('take_profit_price'),
            position_data.get('is_tracked', True),
            position_data.get('source_order_id')
        )

        return self.execute_insert(query, params)

    def update_position(self, option_symbol: str, updates: Dict[str, Any]) -> int:
        """Update position"""
        set_clause = ', '.join([f"{key} = ?" for key in updates.keys()])
        query = f"UPDATE positions SET {set_clause} WHERE option_symbol = ?"
        params = tuple(updates.values()) + (option_symbol,)

        return self.execute_update(query, params)

    def get_position(self, option_symbol: str) -> Optional[Dict[str, Any]]:
        """Get position by option symbol"""
        query = "SELECT * FROM positions WHERE option_symbol = ?"
        results = self.execute_query(query, (option_symbol,))
        return results[0] if results else None

    def get_all_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions"""
        query = "SELECT * FROM positions WHERE remaining_contracts > 0"
        return self.execute_query(query)

    def delete_position(self, option_symbol: str) -> int:
        """Delete position record"""
        query = "DELETE FROM positions WHERE option_symbol = ?"
        return self.execute_update(query, (option_symbol,))

    # ========== Position Close Operations ==========

    def record_position_close(self, close_data: Dict[str, Any]) -> int:
        """Record a position close (full or partial)"""
        query = """
            INSERT INTO position_closes (
                option_symbol, contracts_closed, exit_price, exit_time, realized_pnl
            ) VALUES (?, ?, ?, ?, ?)
        """
        params = (
            close_data['option_symbol'],
            close_data['contracts_closed'],
            close_data['exit_price'],
            close_data['exit_time'],
            close_data['realized_pnl']
        )

        return self.execute_insert(query, params)

    def get_position_closes(self, option_symbol: str) -> List[Dict[str, Any]]:
        """Get all closes for a position"""
        query = """
            SELECT * FROM position_closes
            WHERE option_symbol = ?
            ORDER BY exit_time ASC
        """
        return self.execute_query(query, (option_symbol,))

    # ========== Journal Operations ==========

    def update_journal_entry(self, date: str, journal_data: Dict[str, Any]) -> int:
        """Update or create journal entry for a date"""
        # Check if entry exists
        existing = self.execute_query(
            "SELECT id FROM journal_entries WHERE date = ?",
            (date,)
        )

        if existing:
            # Update
            set_clause = ', '.join([f"{key} = ?" for key in journal_data.keys()])
            query = f"UPDATE journal_entries SET {set_clause} WHERE date = ?"
            params = tuple(journal_data.values()) + (date,)
            return self.execute_update(query, params)
        else:
            # Insert
            keys = list(journal_data.keys())
            placeholders = ', '.join(['?' for _ in keys])
            query = f"INSERT INTO journal_entries (date, {', '.join(keys)}) VALUES (?, {placeholders})"
            params = (date,) + tuple(journal_data.values())
            return self.execute_insert(query, params)

    def get_journal_entries(self, start_date: Optional[str] = None,
                           end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get journal entries within date range"""
        if start_date and end_date:
            query = """
                SELECT * FROM journal_entries
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC
            """
            return self.execute_query(query, (start_date, end_date))
        elif start_date:
            query = """
                SELECT * FROM journal_entries
                WHERE date >= ?
                ORDER BY date DESC
            """
            return self.execute_query(query, (start_date,))
        else:
            query = "SELECT * FROM journal_entries ORDER BY date DESC"
            return self.execute_query(query)

    # ========== Cleanup Operations ==========

    def cleanup_old_data(self, days: int = 90):
        """Clean up old completed orders and closed positions"""
        cutoff_date = datetime.now().isoformat()

        # Delete old completed orders
        query = """
            DELETE FROM orders
            WHERE status IN ('filled', 'rejected', 'canceled', 'timeout')
            AND datetime(submit_time) < datetime(?, '-' || ? || ' days')
        """
        deleted_orders = self.execute_update(query, (cutoff_date, days))

        logger.info(f"Cleaned up {deleted_orders} old orders")

    def vacuum(self):
        """Optimize database"""
        with self.get_connection() as conn:
            conn.execute("VACUUM")
        logger.info("Database vacuumed")
