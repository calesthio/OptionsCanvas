"""
Tests for the four flagged-issue fixes from
docs/backend-flagged-fixes-plan-2026-05-24.md:

 1. close_position polling + pending_close reconciliation
 2. add_to_position weighted average uses remaining (not lifetime) contracts
 3. option_order_type persisted on equity_limit orders
 4. InvariantValidator.validate_position_invariants (rewritten to match real schema)
"""

import pytest
from unittest.mock import MagicMock
import pytz

from assisted_trading.backend.state_machine import InvariantValidator
from assisted_trading.backend.database.db_manager import DatabaseManager
from assisted_trading.backend.order_manager import OrderManager
from assisted_trading.backend.position_manager_v2 import PositionManagerV2
from assisted_trading.backend.trading_engine import TradingEngine


TZ = pytz.timezone('US/Eastern')


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _fresh_db(tmp_path):
    return DatabaseManager(str(tmp_path / 'test.db'))


def _seed_position(pm, *, option_symbol='SPY260115C00595000', remaining=10,
                   total=10, entry_price=2.00):
    pm.open_position(
        option_symbol=option_symbol,
        symbol='SPY',
        contract_type='CALL',
        strike=595.0,
        dte=2,
        total_contracts=total,
        entry_price=entry_price,
        underlying_entry_price=590.0,
    )
    if remaining != total:
        # Simulate a partial close.
        pm.close_position(option_symbol, total - remaining, exit_price=3.00)


def _engine(tmp_path, broker=None):
    db = _fresh_db(tmp_path)
    om = OrderManager(timezone=TZ, db_manager=db)
    pm = PositionManagerV2(
        config={'risk_management': {'max_open_positions': 10, 'max_position_size': 100_000}},
        timezone=TZ,
        db_manager=db,
    )
    broker = broker or MagicMock()
    engine = TradingEngine.__new__(TradingEngine)
    # Match production wiring: TradingEngine does NOT own a db handle;
    # it reaches the DB through order_manager.db.
    engine.order_manager = om
    engine.position_manager = pm
    engine.broker = broker
    engine.market_hours = MagicMock()
    engine.market_hours.validate_trading_allowed.return_value = (True, '')
    engine.timezone = TZ
    return engine, db, om, pm, broker


# --------------------------------------------------------------------------- #
# Fix 2: weighted average over remaining contracts
# --------------------------------------------------------------------------- #
class TestAddToPositionUsesRemainingBasis:
    def test_add_after_partial_close_uses_remaining_for_basis(self, tmp_path):
        _, _, _, pm, _ = _engine(tmp_path)
        _seed_position(pm, remaining=2, total=10, entry_price=2.00)

        updated = pm.add_to_position(
            option_symbol='SPY260115C00595000',
            additional_contracts=5,
            new_entry_price=1.00,
            new_underlying_price=580.0,
        )

        # (2 * $2.00 + 5 * $1.00) / 7 = 9/7 ≈ $1.2857
        assert updated['remaining_contracts'] == 7
        assert updated['total_contracts'] == 15  # lifetime accumulator unchanged
        assert round(updated['entry_price'], 4) == round(9 / 7, 4)
        # The lifetime-basis bug would have produced 25/15 ≈ $1.6667.
        assert updated['entry_price'] < 1.50

    def test_add_with_no_prior_close_unchanged_behavior(self, tmp_path):
        _, _, _, pm, _ = _engine(tmp_path)
        _seed_position(pm, remaining=10, total=10, entry_price=2.00)

        updated = pm.add_to_position(
            option_symbol='SPY260115C00595000',
            additional_contracts=5,
            new_entry_price=1.00,
            new_underlying_price=580.0,
        )

        # (10 * 2 + 5 * 1) / 15 = 25/15 ≈ 1.6667 — same as before the fix
        # because remaining == total when nothing was sold.
        assert updated['remaining_contracts'] == 15
        assert round(updated['entry_price'], 4) == round(25 / 15, 4)


# --------------------------------------------------------------------------- #
# Fix 4: rewritten invariant validator
# --------------------------------------------------------------------------- #
class TestPositionInvariants:
    def _good_open(self):
        return {
            'option_symbol': 'SPY260115C00595000',
            'symbol': 'SPY',
            'status': 'open',
            'total_contracts': 10,
            'remaining_contracts': 10,
            'entry_price': 2.00,
            'entry_time': '2026-05-24T10:00:00',
        }

    def test_valid_open_position(self):
        ok, err = InvariantValidator.validate_position_invariants(self._good_open())
        assert ok is True and err is None

    def test_missing_option_symbol_fails(self):
        pos = self._good_open(); pos.pop('option_symbol')
        ok, err = InvariantValidator.validate_position_invariants(pos)
        assert ok is False and 'option_symbol' in err

    def test_remaining_exceeds_total_fails(self):
        pos = self._good_open(); pos['remaining_contracts'] = 99
        ok, err = InvariantValidator.validate_position_invariants(pos)
        assert ok is False and 'exceed' in err

    def test_zero_total_contracts_fails(self):
        pos = self._good_open(); pos['total_contracts'] = 0
        ok, err = InvariantValidator.validate_position_invariants(pos)
        assert ok is False and 'total_contracts' in err

    def test_negative_entry_price_fails(self):
        pos = self._good_open(); pos['entry_price'] = -1.0
        ok, err = InvariantValidator.validate_position_invariants(pos)
        assert ok is False and 'entry_price' in err

    def test_closed_must_have_exit_fields(self):
        pos = {**self._good_open(), 'status': 'closed', 'remaining_contracts': 0,
               'exit_price': 3.00}
        ok, err = InvariantValidator.validate_position_invariants(pos)
        assert ok is False and 'exit_time' in err

    def test_negative_sl_price_fails_if_set(self):
        pos = self._good_open(); pos['stop_loss_price'] = -1.0
        ok, err = InvariantValidator.validate_position_invariants(pos)
        assert ok is False and 'stop_loss_price' in err


# --------------------------------------------------------------------------- #
# Fix 3: option_order_type persistence + migration
# --------------------------------------------------------------------------- #
class TestOptionOrderTypePersistence:
    def test_create_order_persists_option_order_type_market(self, tmp_path):
        db = _fresh_db(tmp_path)
        om = OrderManager(timezone=TZ, db_manager=db)
        order_id = om.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=2,
            position_size=1000.0,
            order_type='equity_limit',
            equity_limit_price=595.50,
            option_order_type='market',
        )
        row = db.get_order(order_id)
        assert row['option_order_type'] == 'market'

    def test_default_is_limit(self, tmp_path):
        db = _fresh_db(tmp_path)
        om = OrderManager(timezone=TZ, db_manager=db)
        order_id = om.create_order(
            symbol='SPY', contract_type='CALL', dte=2,
            position_size=1000.0, order_type='equity_market',
        )
        row = db.get_order(order_id)
        assert row['option_order_type'] == 'limit'

    def test_migration_adds_column_to_old_db(self, tmp_path):
        # Simulate an old DB by manually creating the orders table without
        # the option_order_type column, then reopening through DatabaseManager.
        import sqlite3
        db_path = tmp_path / 'old.db'
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT UNIQUE NOT NULL,
                broker_order_id TEXT,
                symbol TEXT NOT NULL,
                option_symbol TEXT,
                contract_type TEXT NOT NULL,
                dte INTEGER NOT NULL,
                strike REAL,
                order_type TEXT NOT NULL,
                equity_limit_price REAL,
                position_size REAL NOT NULL,
                requested_qty INTEGER,
                stop_loss_price REAL,
                take_profit_price REAL,
                status TEXT NOT NULL,
                submit_time TEXT NOT NULL,
                fill_time TEXT,
                cancel_time TEXT,
                filled_qty INTEGER DEFAULT 0,
                filled_avg_price REAL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        conn.close()

        db = DatabaseManager(str(db_path))
        # Reading PRAGMA confirms the migration ran.
        rows = db.execute_query("PRAGMA table_info(orders)")
        cols = {r['name'] for r in rows}
        assert 'option_order_type' in cols


# --------------------------------------------------------------------------- #
# Fix 1: close_position bounded poll + pending_close reconciliation
# --------------------------------------------------------------------------- #
class TestClosePositionPolling:
    def test_close_polls_until_filled(self, tmp_path):
        engine, db, om, pm, broker = _engine(tmp_path)
        _seed_position(pm)

        broker.place_market_order.return_value = {'order_id': 'BR1'}
        # First two polls report pending, third reports filled.
        broker.get_order_status.side_effect = [
            {'status': 'pending'},
            {'status': 'pending'},
            {'status': 'filled', 'filled_avg_price': 3.50},
        ]

        result = engine.close_position('SPY260115C00595000', 10)
        assert result['success'] is True
        assert result['status'] == 'closed'
        # Position should be gone (fully closed → deleted).
        assert pm.get_position('SPY260115C00595000') is None
        # Close order finalised as filled.
        close_order = db.get_order(result['order_id'])
        assert close_order['status'] == 'filled'
        assert close_order['order_type'] == 'close_market'

    def test_close_returns_pending_close_when_broker_slow(self, tmp_path):
        engine, db, om, pm, broker = _engine(tmp_path)
        _seed_position(pm)

        broker.place_market_order.return_value = {'order_id': 'BR2'}
        # Always pending — never fills within the loop.
        broker.get_order_status.return_value = {'status': 'pending'}

        result = engine.close_position('SPY260115C00595000', 10)
        assert result['success'] is True
        assert result['status'] == 'pending_close'
        # Position still open until reconciliation finalises.
        assert pm.get_position('SPY260115C00595000') is not None
        close_order = db.get_order(result['order_id'])
        assert close_order['status'] == 'pending_close'
        assert close_order['broker_order_id'] == 'BR2'

    def test_process_pending_closes_finalises_late_fills(self, tmp_path):
        engine, db, om, pm, broker = _engine(tmp_path)
        _seed_position(pm)

        broker.place_market_order.return_value = {'order_id': 'BR3'}
        broker.get_order_status.return_value = {'status': 'pending'}

        defer = engine.close_position('SPY260115C00595000', 10)
        assert defer['status'] == 'pending_close'

        # Broker now reports fill on next sweep.
        broker.get_order_status.return_value = {'status': 'filled', 'filled_avg_price': 3.25}
        out = engine.process_pending_closes()
        assert out['closes_completed'] == 1
        assert pm.get_position('SPY260115C00595000') is None
        finalised = db.get_order(defer['order_id'])
        assert finalised['status'] == 'filled'

    def test_process_pending_closes_marks_canceled_when_broker_cancels(self, tmp_path):
        engine, db, om, pm, broker = _engine(tmp_path)
        _seed_position(pm)

        broker.place_market_order.return_value = {'order_id': 'BR4'}
        broker.get_order_status.return_value = {'status': 'pending'}
        defer = engine.close_position('SPY260115C00595000', 10)

        broker.get_order_status.return_value = {'status': 'canceled'}
        out = engine.process_pending_closes()
        assert out['closes_completed'] == 0
        finalised = db.get_order(defer['order_id'])
        assert finalised['status'] == 'canceled'
