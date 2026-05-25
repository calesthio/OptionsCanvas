#!/usr/bin/env python3
"""
Symbol Onboarding Script (Batch)
Idempotently adds or updates symbols in the supported_symbols table.

Usage:
    python scripts/onboard_symbols.py MU WDC AVGO
    python scripts/onboard_symbols.py                # uses SYMBOLS_TO_ONBOARD list below

Pass symbols as CLI arguments, or configure the SYMBOLS_TO_ONBOARD list below.
Run multiple times safely - existing symbols will be updated, not duplicated.
"""

import sys
import sqlite3
import logging
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION - Edit this section to onboard symbols
# ============================================================================

SYMBOLS_TO_ONBOARD = [
    # Just list the ticker symbols — all option chain details (expirations,
    # strikes, increments) are fetched from the broker API at runtime.
    'SPY',
    'QQQ',
    'NVDA',
    'TSLA',
    'AAPL',
    'META',
    'INTC',
    'AMZN',
    'AMD',
    'MU',
]

# Database path (relative to project root)
DB_PATH = Path(__file__).parent.parent / 'assisted_trading' / 'state' / 'trading.db'

# ============================================================================
# Script Logic
# ============================================================================

def get_db_connection():
    """Get database connection and ensure table exists"""
    if not DB_PATH.exists():
        logger.warning(f"Database not found at {DB_PATH}")
        logger.info("Creating new database...")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    ensure_table_exists(conn)
    return conn


def ensure_table_exists(conn):
    """Create supported_symbols table if it doesn't exist"""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='supported_symbols'
    """)

    if cursor.fetchone() is None:
        logger.info("Creating supported_symbols table...")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supported_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                is_active BOOLEAN DEFAULT 1,
                added_date TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_supported_symbols_active
            ON supported_symbols(symbol, is_active)
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS update_supported_symbols_timestamp
            AFTER UPDATE ON supported_symbols
            BEGIN
                UPDATE supported_symbols SET last_updated = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        """)

        conn.commit()
        logger.info("Created supported_symbols table")


def symbol_exists(conn, symbol):
    """Check if symbol already exists in database"""
    cursor = conn.cursor()
    cursor.execute("SELECT id, is_active FROM supported_symbols WHERE symbol = ?", (symbol,))
    result = cursor.fetchone()
    return dict(result) if result else None


def insert_symbol(conn, symbol):
    """Insert new symbol"""
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO supported_symbols (symbol) VALUES (?)",
        (symbol,)
    )
    conn.commit()
    return cursor.lastrowid


def reactivate_symbol(conn, symbol):
    """Reactivate inactive symbol"""
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE supported_symbols SET is_active = 1, last_updated = CURRENT_TIMESTAMP WHERE symbol = ?",
        (symbol,)
    )
    conn.commit()
    return cursor.rowcount


def onboard_symbols(symbols_list):
    """Onboard or update symbols in the database"""
    conn = get_db_connection()

    stats = {
        'inserted': 0,
        'reactivated': 0,
        'already_active': 0,
        'errors': 0
    }

    logger.info(f"Starting symbol onboarding - {len(symbols_list)} symbols to process")
    logger.info(f"Database: {DB_PATH}")

    for symbol in symbols_list:
        symbol = symbol.upper()
        try:
            existing = symbol_exists(conn, symbol)

            if existing is None:
                insert_symbol(conn, symbol)
                logger.info(f"  Inserted new symbol: {symbol}")
                stats['inserted'] += 1
            elif existing['is_active'] == 0:
                reactivate_symbol(conn, symbol)
                logger.info(f"  Reactivated symbol: {symbol}")
                stats['reactivated'] += 1
            else:
                logger.info(f"  Already active: {symbol}")
                stats['already_active'] += 1

        except Exception as e:
            logger.error(f"  Failed to onboard {symbol}: {e}")
            stats['errors'] += 1

    conn.close()

    # Print summary
    logger.info("=" * 60)
    logger.info("ONBOARDING SUMMARY")
    logger.info("=" * 60)
    logger.info(f"New symbols inserted:       {stats['inserted']}")
    logger.info(f"Symbols reactivated:        {stats['reactivated']}")
    logger.info(f"Already active (no change): {stats['already_active']}")
    logger.info(f"Errors encountered:         {stats['errors']}")
    logger.info("=" * 60)

    if stats['errors'] > 0:
        logger.warning(f"{stats['errors']} symbols failed to onboard. Check logs above.")
        return False

    logger.info("All symbols onboarded successfully!")
    return True


def list_current_symbols():
    """List all currently active symbols in database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol, is_active, notes, added_date
        FROM supported_symbols
        ORDER BY is_active DESC, symbol ASC
    """)
    symbols = cursor.fetchall()
    conn.close()

    if not symbols:
        logger.info("No symbols found in database.")
        return

    logger.info("\n" + "=" * 70)
    logger.info("CURRENT SYMBOLS IN DATABASE")
    logger.info("=" * 70)
    logger.info(f"{'Symbol':<8} {'Status':<10} {'Notes':<30} {'Added':<20}")
    logger.info("-" * 70)

    for row in symbols:
        status = "ACTIVE" if row['is_active'] else "INACTIVE"
        notes = (row['notes'] or '')[:28]
        added = (row['added_date'] or '')[:19]
        logger.info(f"{row['symbol']:<8} {status:<10} {notes:<30} {added:<20}")

    logger.info("=" * 70 + "\n")


def main():
    """Main entry point"""
    logger.info("Symbol Onboarding Script")
    logger.info("=" * 60)

    # Use CLI args if provided, otherwise fall back to hardcoded list
    cli_symbols = [s.upper() for s in sys.argv[1:] if not s.startswith('-')]
    symbols = cli_symbols if cli_symbols else SYMBOLS_TO_ONBOARD

    if cli_symbols:
        logger.info(f"Onboarding from CLI args: {', '.join(symbols)}")
    else:
        logger.info(f"Onboarding from SYMBOLS_TO_ONBOARD list ({len(symbols)} symbols)")

    # First, show current symbols
    try:
        list_current_symbols()
    except Exception as e:
        logger.warning(f"Could not list current symbols: {e}")

    # Onboard symbols
    success = onboard_symbols(symbols)

    # Show updated list
    if success:
        logger.info("\nUpdated symbol list:")
        list_current_symbols()

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
