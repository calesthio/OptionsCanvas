#!/usr/bin/env python3
"""
Symbol Offboarding Script
Safely deactivates symbols in the supported_symbols table (soft delete)

Usage:
    python scripts/offboard_symbols.py
    python scripts/offboard_symbols.py --interactive
    python scripts/offboard_symbols.py --list

Configure the SYMBOLS_TO_OFFBOARD list below with symbols to deactivate.
This is a SOFT DELETE - symbols remain in database but marked as inactive.
To permanently delete, use the --hard-delete flag (use with caution!).
"""

import sys
import sqlite3
import logging
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION - Edit this section to offboard symbols
# ============================================================================

SYMBOLS_TO_OFFBOARD = [
    # Add symbols to deactivate here
    'DIA',
    'IWM',
    'MSFT',
]

# Database path (relative to project root)
DB_PATH = Path(__file__).parent.parent / 'assisted_trading' / 'state' / 'trading.db'

# ============================================================================
# Script Logic
# ============================================================================

def get_db_connection():
    """Get database connection"""
    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        logger.error("Please run the platform at least once to create the database.")
        logger.error("Or run: python scripts/onboard_symbols.py")
        sys.exit(1)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # Check if table exists
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='supported_symbols'
    """)

    if cursor.fetchone() is None:
        logger.error("Table 'supported_symbols' not found in database")
        logger.error("Please run: python scripts/onboard_symbols.py")
        conn.close()
        sys.exit(1)

    return conn


def symbol_exists(conn, symbol):
    """Check if symbol exists in database"""
    cursor = conn.cursor()
    cursor.execute("SELECT id, is_active FROM supported_symbols WHERE symbol = ?", (symbol,))
    result = cursor.fetchone()
    return dict(result) if result else None


def deactivate_symbol(conn, symbol):
    """Deactivate symbol (soft delete)"""
    query = """
        UPDATE supported_symbols
        SET is_active = 0, last_updated = CURRENT_TIMESTAMP
        WHERE symbol = ?
    """
    cursor = conn.cursor()
    cursor.execute(query, (symbol,))
    conn.commit()
    return cursor.rowcount


def hard_delete_symbol(conn, symbol):
    """Permanently delete symbol from database (use with caution!)"""
    query = "DELETE FROM supported_symbols WHERE symbol = ?"
    cursor = conn.cursor()
    cursor.execute(query, (symbol,))
    conn.commit()
    return cursor.rowcount


def offboard_symbols(symbols_list, hard_delete=False):
    """Offboard symbols from the database"""
    conn = get_db_connection()

    stats = {
        'deactivated': 0,
        'deleted': 0,
        'not_found': 0,
        'already_inactive': 0,
        'errors': 0
    }

    action = "HARD DELETE" if hard_delete else "SOFT DELETE (deactivate)"
    logger.info(f"Starting symbol offboarding - {len(symbols_list)} symbols to process")
    logger.info(f"Mode: {action}")
    logger.info(f"Database: {DB_PATH}")

    if hard_delete:
        logger.warning("WARNING: Hard delete mode enabled - symbols will be permanently removed!")

    for symbol in symbols_list:
        try:
            existing = symbol_exists(conn, symbol)

            if existing is None:
                logger.warning(f"  Symbol not found: {symbol}")
                stats['not_found'] += 1
                continue

            if existing['is_active'] == 0 and not hard_delete:
                logger.info(f"  Symbol already inactive: {symbol}")
                stats['already_inactive'] += 1
                continue

            if hard_delete:
                rows = hard_delete_symbol(conn, symbol)
                if rows > 0:
                    logger.info(f"  Permanently deleted symbol: {symbol}")
                    stats['deleted'] += 1
            else:
                rows = deactivate_symbol(conn, symbol)
                if rows > 0:
                    logger.info(f"  Deactivated symbol: {symbol}")
                    stats['deactivated'] += 1

        except Exception as e:
            logger.error(f"  Failed to offboard {symbol}: {e}")
            stats['errors'] += 1

    conn.close()

    # Print summary
    logger.info("=" * 60)
    logger.info("OFFBOARDING SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Symbols deactivated:      {stats['deactivated']}")
    logger.info(f"Symbols deleted:          {stats['deleted']}")
    logger.info(f"Already inactive:         {stats['already_inactive']}")
    logger.info(f"Not found:                {stats['not_found']}")
    logger.info(f"Errors encountered:       {stats['errors']}")
    logger.info("=" * 60)

    if stats['errors'] > 0:
        logger.warning(f"{stats['errors']} symbols failed to offboard. Check logs above.")
        return False

    logger.info("Offboarding completed successfully!")
    return True


def list_symbols(active_only=False):
    """List symbols in database"""
    conn = get_db_connection()
    cursor = conn.cursor()

    if active_only:
        cursor.execute("""
            SELECT symbol, is_active, notes, added_date
            FROM supported_symbols
            WHERE is_active = 1
            ORDER BY symbol ASC
        """)
        title = "ACTIVE SYMBOLS IN DATABASE"
    else:
        cursor.execute("""
            SELECT symbol, is_active, notes, added_date
            FROM supported_symbols
            ORDER BY is_active DESC, symbol ASC
        """)
        title = "ALL SYMBOLS IN DATABASE"

    symbols = cursor.fetchall()
    conn.close()

    if not symbols:
        logger.info("No symbols found in database.")
        return

    logger.info("\n" + "=" * 70)
    logger.info(title)
    logger.info("=" * 70)
    logger.info(f"{'Symbol':<8} {'Status':<10} {'Notes':<30} {'Added':<20}")
    logger.info("-" * 70)

    for row in symbols:
        status = "ACTIVE" if row['is_active'] else "INACTIVE"
        notes = (row['notes'] or '')[:28]
        added = (row['added_date'] or '')[:19]
        logger.info(f"{row['symbol']:<8} {status:<10} {notes:<30} {added:<20}")

    logger.info("=" * 70 + "\n")


def interactive_mode():
    """Interactive mode to select symbols to offboard"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol FROM supported_symbols
        WHERE is_active = 1
        ORDER BY symbol ASC
    """)
    active_symbols = [row['symbol'] for row in cursor.fetchall()]
    conn.close()

    if not active_symbols:
        logger.info("No active symbols found in database.")
        return []

    logger.info("Active symbols:")
    for i, symbol in enumerate(active_symbols, 1):
        logger.info(f"  {i}. {symbol}")

    logger.info("\nEnter symbol numbers to offboard (comma-separated, e.g., 1,3,5):")
    logger.info("Or type 'all' to offboard all symbols")
    logger.info("Or press Enter to cancel")

    try:
        selection = input("> ").strip()
    except KeyboardInterrupt:
        logger.info("\nCancelled.")
        return []

    if not selection:
        return []

    if selection.lower() == 'all':
        return active_symbols

    # Parse selection
    try:
        indices = [int(x.strip()) - 1 for x in selection.split(',')]
        selected = [active_symbols[i] for i in indices if 0 <= i < len(active_symbols)]
        return selected
    except (ValueError, IndexError):
        logger.error("Invalid selection. Please enter valid numbers.")
        return []


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Offboard symbols from trading platform')
    parser.add_argument('--hard-delete', action='store_true',
                        help='Permanently delete symbols instead of deactivating (DANGEROUS!)')
    parser.add_argument('--interactive', '-i', action='store_true',
                        help='Interactive mode - select symbols from list')
    parser.add_argument('--list', '-l', action='store_true',
                        help='List all symbols and exit')
    parser.add_argument('--list-active', action='store_true',
                        help='List only active symbols and exit')
    args = parser.parse_args()

    logger.info("Symbol Offboarding Script")
    logger.info("=" * 60)

    # List mode
    if args.list:
        list_symbols(active_only=False)
        return 0

    if args.list_active:
        list_symbols(active_only=True)
        return 0

    # Show current symbols
    try:
        list_symbols(active_only=False)
    except Exception as e:
        logger.warning(f"Could not list symbols: {e}")

    # Determine which symbols to offboard
    if args.interactive:
        symbols = interactive_mode()
        if not symbols:
            logger.info("No symbols selected. Exiting.")
            return 0
    else:
        symbols = SYMBOLS_TO_OFFBOARD
        if not symbols:
            logger.warning("No symbols configured in SYMBOLS_TO_OFFBOARD list.")
            logger.info("Edit the script or use --interactive mode.")
            return 0

    # Confirm hard delete
    if args.hard_delete:
        logger.warning("=" * 60)
        logger.warning("HARD DELETE MODE - This will PERMANENTLY remove symbols!")
        logger.warning("This action CANNOT be undone!")
        logger.warning("=" * 60)
        logger.warning(f"Symbols to delete: {', '.join(symbols)}")
        confirm = input("Type 'DELETE' to confirm: ").strip()
        if confirm != 'DELETE':
            logger.info("Cancelled.")
            return 0

    # Offboard symbols
    success = offboard_symbols(symbols, hard_delete=args.hard_delete)

    # Show updated list
    if success:
        logger.info("\nUpdated symbol list:")
        list_symbols(active_only=False)

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
