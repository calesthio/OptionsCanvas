#!/usr/bin/env python3
"""
Symbol Onboarding Script
Verifies options exist on Alpaca, then inserts into DB. Idempotent.

Usage:
    # Default — onboard the curated Tier-1 universe (30 highest option-flow names)
    python scripts/onboard_symbol.py

    # Onboard the full 110-name universe (Tier 1 + 2 + 3)
    python scripts/onboard_symbol.py --all

    # Onboard your own custom tickers
    python scripts/onboard_symbol.py AAPL MSFT NVDA

    # List what's currently active in your DB
    python scripts/onboard_symbol.py --list
"""

import sys
import json
import sqlite3
import logging
import argparse
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
CONFIG_PATH = PROJECT_ROOT / 'config' / 'config.json'
DB_PATH = PROJECT_ROOT / 'assisted_trading' / 'state' / 'trading.db'

# ============================================================================
# Curated universes — ranked by sampled options flow (Alpaca data, 2026-05-22)
# ============================================================================

# Tier 1 — 30 names, ~85% of US single-name option volume
TIER_1 = [
    'SPY', 'QQQ', 'NVDA', 'TSLA', 'IWM', 'AAPL', 'AMD', 'MSFT', 'MU', 'INTC',
    'AMZN', 'META', 'GOOGL', 'SOXL', 'TQQQ', 'F', 'PLTR', 'AAL', 'HOOD', 'XLE',
    'XLF', 'SOXS', 'SQQQ', 'MSTR', 'GOOG', 'AVGO', 'COIN', 'CRWD', 'NFLX', 'UBER',
]

# Tier 2 — adds 40 names (ranks 31-70)
TIER_2 = [
    'JPM', 'BAC', 'GLD', 'TLT', 'SMH', 'HPQ', 'QCOM', 'DIA', 'WMT', 'ARM',
    'PFE', 'T', 'VZ', 'NKE', 'GE', 'DIS', 'SMCI', 'RKLB', 'WFC', 'TSLL',
    'BABA', 'NU', 'XLK', 'CVNA', 'SNOW', 'PDD', 'ORCL', 'SLV', 'CRM', 'TSM',
    'ROKU', 'GDX', 'MRK', 'C', 'CCL', 'UVXY', 'VXX', 'ANET', 'EEM', 'WDC',
]

# Tier 3 — adds 40 names (ranks 71-110)
TIER_3 = [
    'CVX', 'XOM', 'MS', 'GS', 'LLY', 'UNH', 'JNJ', 'ABBV', 'GILD', 'HYG',
    'ABNB', 'RBLX', 'DAL', 'UAL', 'DDOG', 'GM', 'SHOP', 'BA', 'CAT', 'DE',
    'BMY', 'MRNA', 'ZS', 'OKTA', 'NET', 'ADBE', 'TGT', 'KRE', 'XOP', 'XBI',
    'MELI', 'PYPL', 'JD', 'KWEB', 'FXI', 'CVS', 'TMUS', 'PG', 'KO', 'HD',
]

UNIVERSE_ALL = TIER_1 + TIER_2 + TIER_3  # 110 names


def load_alpaca_client():
    """Load Alpaca credentials and create trading client"""
    if not CONFIG_PATH.exists():
        logger.error(f"Config not found at {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    alpaca_config = config['alpaca']
    is_paper = 'paper' in alpaca_config.get('base_url', '')
    trading_client = TradingClient(
        api_key=alpaca_config['api_key'],
        secret_key=alpaca_config['secret_key'],
        paper=is_paper
    )
    return trading_client


def verify_has_options(trading_client, symbol):
    """Confirm symbol has active option contracts on Alpaca"""
    from datetime import date, timedelta
    today = date.today()
    end_date = today + timedelta(days=30)

    try:
        request = GetOptionContractsRequest(
            underlying_symbols=[symbol],
            expiration_date_gte=today.strftime('%Y-%m-%d'),
            expiration_date_lte=end_date.strftime('%Y-%m-%d'),
            status=AssetStatus.ACTIVE,
        )
        contracts = trading_client.get_option_contracts(request)
        option_contracts = contracts.option_contracts if contracts else []

        if not option_contracts:
            return False, 0

        return True, len(option_contracts)

    except Exception as e:
        logger.warning(f"Could not verify options for {symbol}: {e}")
        return False, 0


# ============================================================================
# Database operations
# ============================================================================

def ensure_table_exists(conn):
    """Create supported_symbols table if it doesn't exist (new simplified schema)"""
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


def get_db_connection():
    """Get database connection"""
    if not DB_PATH.exists():
        logger.info(f"Creating new database at {DB_PATH}")
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_table_exists(conn)
    return conn


def upsert_symbol(conn, symbol, notes=None):
    """Insert or update a symbol in the database"""
    cursor = conn.cursor()
    cursor.execute("SELECT id, is_active FROM supported_symbols WHERE symbol = ?", (symbol,))
    existing = cursor.fetchone()

    if existing is None:
        cursor.execute("""
            INSERT INTO supported_symbols (symbol, notes) VALUES (?, ?)
        """, (symbol, notes))
        conn.commit()
        return 'inserted'
    else:
        was_inactive = existing['is_active'] == 0
        cursor.execute("""
            UPDATE supported_symbols SET
                notes = ?, is_active = 1,
                last_updated = CURRENT_TIMESTAMP
            WHERE symbol = ?
        """, (notes, symbol))
        conn.commit()
        return 'reactivated' if was_inactive else 'updated'


def list_symbols():
    """List all symbols in database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT symbol, is_active, notes, added_date
        FROM supported_symbols ORDER BY is_active DESC, symbol ASC
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("No symbols in database.")
        return

    print()
    print("=" * 70)
    print("SYMBOLS IN DATABASE")
    print("=" * 70)
    print(f"{'Symbol':<8} {'Status':<10} {'Notes':<30} {'Added':<20}")
    print("-" * 70)
    for row in rows:
        status = "ACTIVE" if row['is_active'] else "INACTIVE"
        notes = (row['notes'] or '')[:28]
        added = (row['added_date'] or '')[:19]
        print(f"{row['symbol']:<8} {status:<10} {notes:<30} {added:<20}")
    print("=" * 70)
    print()


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Onboard symbols for options trading. '
            'Default (no args) onboards the curated Tier-1 universe of 30 names.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'Examples:\n'
            '  python scripts/onboard_symbol.py                # default: 30 Tier-1 names\n'
            '  python scripts/onboard_symbol.py --all          # full 110-name universe\n'
            '  python scripts/onboard_symbol.py AAPL MSFT NVDA # custom tickers\n'
            '  python scripts/onboard_symbol.py --list         # show what is active\n'
        )
    )
    parser.add_argument('symbols', nargs='*', help='Custom ticker(s) to onboard (overrides --all/default)')
    parser.add_argument('--all', action='store_true',
                        help=f'Onboard the full {len(UNIVERSE_ALL)}-name universe (Tier 1 + 2 + 3)')
    parser.add_argument('--tier2', action='store_true',
                        help=f'Onboard Tier 1 + Tier 2 ({len(TIER_1) + len(TIER_2)} names)')
    parser.add_argument('--list', action='store_true', help='List all symbols in database')
    args = parser.parse_args()

    if args.list:
        list_symbols()
        return 0

    # Resolve which symbols to onboard
    if args.symbols:
        symbols_to_onboard = [s.upper() for s in args.symbols]
        source = f'custom ({len(symbols_to_onboard)} tickers)'
    elif args.all:
        symbols_to_onboard = UNIVERSE_ALL
        source = f'Tier 1 + 2 + 3 ({len(UNIVERSE_ALL)} names)'
    elif args.tier2:
        symbols_to_onboard = TIER_1 + TIER_2
        source = f'Tier 1 + 2 ({len(TIER_1) + len(TIER_2)} names)'
    else:
        symbols_to_onboard = TIER_1
        source = f'Tier 1 default ({len(TIER_1)} names — pass --all for {len(UNIVERSE_ALL)})'

    logger.info(f"Onboarding: {source}")
    logger.info(f"Symbols: {', '.join(symbols_to_onboard)}")
    print()

    # Load Alpaca client
    trading_client = load_alpaca_client()
    conn = get_db_connection()

    stats = {'inserted': 0, 'updated': 0, 'reactivated': 0, 'errors': 0, 'no_options': 0}

    for symbol in symbols_to_onboard:
        symbol = symbol.upper()
        try:
            has_options, count = verify_has_options(trading_client, symbol)

            if not has_options:
                logger.warning(f"  {symbol}: No active option contracts found — skipping")
                stats['no_options'] += 1
                continue

            logger.info(f"  {symbol}: Verified ({count} contracts found)")

            result = upsert_symbol(conn, symbol, notes='Auto-onboarded')
            stats[result] += 1
            logger.info(f"  -> {result.upper()}")

        except Exception as e:
            logger.error(f"Failed to onboard {symbol}: {e}")
            stats['errors'] += 1

    conn.close()

    # Summary
    print()
    print("=" * 50)
    print("ONBOARDING SUMMARY")
    print("=" * 50)
    if stats['inserted']:
        print(f"  New:         {stats['inserted']}")
    if stats['updated']:
        print(f"  Updated:     {stats['updated']}")
    if stats['reactivated']:
        print(f"  Reactivated: {stats['reactivated']}")
    if stats['no_options']:
        print(f"  No options:  {stats['no_options']}")
    if stats['errors']:
        print(f"  Errors:      {stats['errors']}")
    print("=" * 50)

    # Show current state
    list_symbols()

    return 1 if stats['errors'] else 0


if __name__ == '__main__':
    sys.exit(main())
