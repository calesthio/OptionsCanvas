#!/usr/bin/env python3
"""
Verification Script
Checks if the symbol management system is set up correctly
"""

import sys
import sqlite3
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent.parent / 'assisted_trading' / 'state' / 'trading.db'


def check_database_exists():
    """Check if database file exists"""
    if not DB_PATH.exists():
        print("FAIL: Database not found at:", DB_PATH)
        print("\nSolution: Run the platform once to create the database:")
        print("   python assisted_trading/run_platform.py")
        return False

    print("PASS: Database found at:", DB_PATH)
    return True


def check_table_exists():
    """Check if supported_symbols table exists"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='supported_symbols'
        """)
        result = cursor.fetchone()
        conn.close()

        if result:
            print("PASS: Table 'supported_symbols' exists")
            return True
        else:
            print("FAIL: Table 'supported_symbols' not found")
            print("\nSolution: The table will be created automatically when you restart the platform.")
            return False

    except Exception as e:
        print(f"FAIL: Error checking table: {e}")
        return False


def check_table_structure():
    """Check if table has correct columns (simplified schema)"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(supported_symbols)")
        columns = cursor.fetchall()
        conn.close()

        if not columns:
            print("FAIL: Table has no columns")
            return False

        expected_columns = {'symbol', 'is_active', 'added_date', 'last_updated', 'notes'}
        actual_columns = {col[1] for col in columns}

        missing = expected_columns - actual_columns
        if missing:
            print(f"FAIL: Missing columns: {missing}")
            return False

        # Check for old columns that should have been migrated away
        old_columns = {'asset_type', 'expiration_frequency', 'strike_increment',
                       'max_contracts_per_side', 'current_week_all', 'weekly_only', 'monthly_only'}
        leftover = old_columns & actual_columns
        if leftover:
            print(f"WARNING: Old columns still present (needs migration): {leftover}")
            print("Solution: Restart the platform to auto-migrate the database.")
            return False

        print(f"PASS: Table structure correct ({len(columns)} columns)")
        return True

    except Exception as e:
        print(f"FAIL: Error checking table structure: {e}")
        return False


def count_symbols():
    """Count symbols in database"""
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM supported_symbols WHERE is_active = 1")
        active_count = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM supported_symbols WHERE is_active = 0")
        inactive_count = cursor.fetchone()[0]

        conn.close()

        total = active_count + inactive_count

        if total == 0:
            print("WARNING: No symbols in database yet")
            print("\nNext step: Run the onboarding script:")
            print("   python scripts/onboard_symbol.py SPY QQQ AAPL NVDA TSLA")
        else:
            print(f"PASS: Symbols in database: {active_count} active, {inactive_count} inactive")

        return True

    except Exception as e:
        print(f"FAIL: Error counting symbols: {e}")
        return False


def test_symbol_config_service():
    """Test if SymbolConfigService can be imported and used"""
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent / 'assisted_trading'))
        from backend.symbol_config_service import SymbolConfigService
        from backend.database.db_manager import DatabaseManager

        # Try to initialize
        db_manager = DatabaseManager(str(DB_PATH))
        service = SymbolConfigService(db_manager)

        # Try to get active symbols
        symbols = service.get_all_active_symbols()

        print(f"PASS: SymbolConfigService working ({len(symbols)} active symbols)")
        return True

    except ImportError as e:
        print(f"FAIL: Cannot import SymbolConfigService: {e}")
        return False
    except Exception as e:
        print(f"FAIL: Error testing SymbolConfigService: {e}")
        return False


def main():
    """Run all verification checks"""
    print("=" * 70)
    print("  Symbol Management System - Setup Verification")
    print("=" * 70)
    print()

    checks = [
        ("Database File", check_database_exists),
        ("Table Exists", check_table_exists),
        ("Table Structure", check_table_structure),
        ("Symbol Count", count_symbols),
        ("Service Integration", test_symbol_config_service),
    ]

    results = []
    for check_name, check_func in checks:
        print(f"\nChecking: {check_name}")
        print("-" * 70)
        result = check_func()
        results.append(result)
        print()

    # Summary
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    passed = sum(results)
    total = len(results)

    for i, (check_name, _) in enumerate(checks):
        status = "PASS" if results[i] else "FAIL"
        print(f"{status} - {check_name}")

    print()
    print(f"Result: {passed}/{total} checks passed")
    print("=" * 70)

    if passed == total:
        print("\nAll checks passed! Symbol management system is ready.")
        print("\nNext steps:")
        print("   1. Run: python scripts/onboard_symbol.py SPY QQQ AAPL NVDA")
        print("   2. Restart your trading platform")
        print("   3. Symbols will appear in the UI")
    else:
        print("\nSome checks failed. Follow the solutions above to fix them.")

    return 0 if passed == total else 1


if __name__ == '__main__':
    sys.exit(main())
