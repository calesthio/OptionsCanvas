"""
Unit tests for DatabaseManager
Covers schema creation, CRUD, migration, and cleanup.
"""
import os
import sqlite3
import pytest
from datetime import datetime, timedelta

from assisted_trading.backend.database.db_manager import DatabaseManager


@pytest.mark.unit
class TestSchemaAndInit:
    def test_database_file_created(self, tmp_path):
        db_path = tmp_path / "x.db"
        DatabaseManager(str(db_path))
        assert db_path.exists()

    def test_tables_exist(self, test_db):
        with test_db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}
        for required in ('orders', 'positions', 'position_closes', 'journal_entries', 'supported_symbols'):
            assert required in tables

    def test_creates_missing_parent_dir(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "x.db"
        DatabaseManager(str(nested))
        assert nested.exists()


@pytest.mark.unit
class TestSupportedSymbolsMigration:
    def test_migration_is_idempotent(self, test_db):
        # Run migration again - must not crash
        test_db._migrate_supported_symbols()
        test_db._migrate_supported_symbols()

    def test_migration_from_old_schema(self, tmp_path):
        # Build a DB with old schema, then init DatabaseManager which migrates
        db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE supported_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                asset_type TEXT,
                expiration_frequency TEXT,
                strike_increment REAL,
                supports_zero_dte INTEGER,
                is_active BOOLEAN DEFAULT 1,
                added_date TEXT DEFAULT CURRENT_TIMESTAMP,
                last_updated TEXT DEFAULT CURRENT_TIMESTAMP,
                notes TEXT
            );
            INSERT INTO supported_symbols (symbol, asset_type, is_active, notes)
            VALUES ('SPY', 'ETF', 1, 'legacy');
        """)
        conn.commit()
        conn.close()

        db = DatabaseManager(str(db_path))

        # After migration: new schema, data preserved
        rows = db.execute_query("SELECT * FROM supported_symbols WHERE symbol='SPY'")
        assert len(rows) == 1
        assert rows[0]['notes'] == 'legacy'
        # asset_type column should be gone
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(supported_symbols)")
            cols = {row[1] for row in cursor.fetchall()}
        assert 'asset_type' not in cols


@pytest.mark.unit
class TestOrderCrud:
    def _order(self, oid='O1', status='pending'):
        return {
            'order_id': oid, 'symbol': 'SPY', 'contract_type': 'CALL',
            'dte': 1, 'order_type': 'equity_market',
            'equity_limit_price': None, 'position_size': 1000.0,
            'stop_loss_price': None, 'take_profit_price': None,
            'status': status, 'submit_time': datetime.now().isoformat()
        }

    def test_create_and_get_order(self, test_db):
        test_db.create_order(self._order('O1'))
        row = test_db.get_order('O1')
        assert row is not None
        assert row['symbol'] == 'SPY'

    def test_get_order_not_found(self, test_db):
        assert test_db.get_order('MISSING') is None

    def test_unique_order_id_constraint(self, test_db):
        test_db.create_order(self._order('DUPE'))
        with pytest.raises(sqlite3.IntegrityError):
            test_db.create_order(self._order('DUPE'))

    def test_get_pending_orders_filters(self, test_db):
        test_db.create_order(self._order('A', status='pending'))
        test_db.create_order(self._order('B', status='monitoring_equity'))
        test_db.create_order(self._order('C', status='filled'))
        pending = test_db.get_pending_orders()
        statuses = {o['status'] for o in pending}
        assert 'filled' not in statuses
        assert 'pending' in statuses
        assert 'monitoring_equity' in statuses

    def test_update_order(self, test_db):
        test_db.create_order(self._order('U'))
        test_db.update_order('U', {'status': 'filled', 'filled_qty': 5})
        row = test_db.get_order('U')
        assert row['status'] == 'filled'
        assert row['filled_qty'] == 5


@pytest.mark.unit
class TestPositionCrud:
    def _pos(self, opt='SPY250131C00450000', remain=10):
        return {
            'option_symbol': opt, 'symbol': 'SPY', 'contract_type': 'CALL',
            'strike': 450.0, 'dte': 5, 'total_contracts': 10,
            'remaining_contracts': remain, 'entry_price': 5.0,
            'entry_time': datetime.now().isoformat(),
            'underlying_entry_price': 450.0,
            'stop_loss_price': None, 'take_profit_price': None,
            'is_tracked': True, 'source_order_id': None
        }

    def test_create_get_position(self, test_db):
        test_db.create_position(self._pos())
        p = test_db.get_position('SPY250131C00450000')
        assert p is not None
        assert p['strike'] == 450.0

    def test_get_all_positions_excludes_closed(self, test_db):
        test_db.create_position(self._pos('A', remain=10))
        test_db.create_position(self._pos('B', remain=0))
        all_p = test_db.get_all_positions()
        symbols = {p['option_symbol'] for p in all_p}
        assert 'A' in symbols
        assert 'B' not in symbols

    def test_delete_position(self, test_db):
        test_db.create_position(self._pos('D'))
        test_db.delete_position('D')
        assert test_db.get_position('D') is None


@pytest.mark.unit
class TestPositionCloses:
    def test_record_and_get_closes(self, test_db):
        test_db.create_position({
            'option_symbol': 'SPY1', 'symbol': 'SPY', 'contract_type': 'CALL',
            'strike': 450.0, 'dte': 5, 'total_contracts': 10,
            'remaining_contracts': 10, 'entry_price': 5.0,
            'entry_time': datetime.now().isoformat()
        })
        test_db.record_position_close({
            'option_symbol': 'SPY1', 'contracts_closed': 5,
            'exit_price': 7.0, 'exit_time': datetime.now().isoformat(),
            'realized_pnl': 1000.0
        })
        closes = test_db.get_position_closes('SPY1')
        assert len(closes) == 1
        assert closes[0]['realized_pnl'] == 1000.0


@pytest.mark.unit
class TestJournal:
    def test_insert_then_update_journal(self, test_db):
        test_db.update_journal_entry('2026-01-01', {'net_pnl': 100.0, 'total_trades': 1})
        rows = test_db.get_journal_entries('2026-01-01')
        assert len(rows) == 1
        assert rows[0]['net_pnl'] == 100.0
        # Now update
        test_db.update_journal_entry('2026-01-01', {'net_pnl': 250.0, 'total_trades': 2})
        rows = test_db.get_journal_entries('2026-01-01')
        assert len(rows) == 1
        assert rows[0]['net_pnl'] == 250.0
        assert rows[0]['total_trades'] == 2

    def test_get_journal_entries_range(self, test_db):
        test_db.update_journal_entry('2026-01-01', {'net_pnl': 1.0})
        test_db.update_journal_entry('2026-01-05', {'net_pnl': 2.0})
        test_db.update_journal_entry('2026-02-01', {'net_pnl': 3.0})
        rows = test_db.get_journal_entries('2026-01-01', '2026-01-31')
        assert len(rows) == 2
