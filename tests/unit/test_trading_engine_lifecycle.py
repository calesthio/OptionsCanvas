"""
Trading engine lifecycle tests: order placement, fill handling, SL/TP triggering,
partial fills, broker errors, cancellation, market-hours gating.

Uses MockBroker plus a fake market_hours to isolate behavior.
"""
from unittest.mock import MagicMock, patch
import pytest
import pytz

from assisted_trading.backend.trading_engine import TradingEngine
from assisted_trading.backend.position_manager_v2 import PositionManagerV2
from assisted_trading.backend.order_manager import OrderManager
from tests.mocks.mock_broker import MockBroker


@pytest.fixture
def tz():
    return pytz.timezone('America/Los_Angeles')


@pytest.fixture
def engine_config():
    return {
        'order_settings': {
            'entry_timeout_seconds': 60,
            'accept_partial_fills': True,
            'auto_sell_on_stop_loss': True,
            'auto_sell_on_take_profit': True,
        },
        'risk_management': {
            'max_simultaneous_positions': 5,
            'max_positions_per_symbol': 2,
        }
    }


@pytest.fixture
def market_hours_open():
    mh = MagicMock()
    mh.validate_trading_allowed.return_value = (True, "OK")
    mh.is_market_open.return_value = True
    return mh


@pytest.fixture
def market_hours_closed():
    mh = MagicMock()
    mh.validate_trading_allowed.return_value = (False, "Markets are closed")
    mh.is_market_open.return_value = False
    return mh


@pytest.fixture
def broker():
    return MockBroker()


@pytest.fixture
def engine(broker, engine_config, test_db, tz, market_hours_open):
    pm = PositionManagerV2(engine_config, tz, test_db)
    om = OrderManager(tz, test_db)
    return TradingEngine(broker, engine_config, pm, om, market_hours_open, tz)


@pytest.fixture
def engine_closed_market(broker, engine_config, test_db, tz, market_hours_closed):
    pm = PositionManagerV2(engine_config, tz, test_db)
    om = OrderManager(tz, test_db)
    return TradingEngine(broker, engine_config, pm, om, market_hours_closed, tz)


# ---------------------- open_position ----------------------

@pytest.mark.unit
class TestOpenPositionEquityMarket:
    def test_blocks_when_market_closed(self, engine_closed_market):
        result = engine_closed_market.open_position(
            'SPY', 'CALL', 1, 1000.0, strike=450.0
        )
        assert result['success'] is False
        assert 'closed' in result['error'].lower()

    def test_equity_market_places_order(self, engine):
        result = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        assert result['success'] is True
        assert result['status'] == 'pending_fill'
        order = engine.order_manager.get_order(result['order_id'])
        assert order['option_symbol'] is not None
        assert order['broker_order_id'] is not None
        assert order['requested_qty'] > 0

    def test_insufficient_buying_power_returns_error(self, engine, broker):
        broker.set_account_balance(buying_power=1.0)
        result = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        assert result['success'] is False
        assert 'buying power' in result['error'].lower()

    def test_broker_returns_no_contracts(self, engine, broker):
        broker.get_option_contracts = MagicMock(return_value=[])
        result = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        assert result['success'] is False
        assert 'option' in result['error'].lower()

    def test_zero_premium_returns_error(self, engine, broker):
        broker.get_option_quote = MagicMock(return_value={
            'bid': 0.0, 'ask': 0.0, 'mid': 0.0, 'spread': 0.0,
            'iv': 0.0, 'delta': 0.0, 'gamma': 0.0, 'theta': 0.0, 'vega': 0.0,
        })
        result = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        assert result['success'] is False

    def test_position_limit_blocks_open(self, engine):
        # Saturate max_simultaneous_positions=5
        for i in range(5):
            engine.position_manager.open_position(
                f'OPT{i}', 'SPY', 'CALL', 450.0, 1, 1, 5.0, 450.0
            )
        result = engine.open_position('AAPL', 'CALL', 1, 1000.0, strike=180.0)
        assert result['success'] is False


@pytest.mark.unit
class TestOpenPositionEquityLimit:
    def test_equity_limit_queues_order(self, engine):
        result = engine.open_position(
            'SPY', 'CALL', 1, 1000.0,
            order_type='equity_limit', equity_limit_price=440.0
        )
        assert result['success'] is True
        assert result['status'] == 'monitoring_equity'
        order = engine.order_manager.get_order(result['order_id'])
        assert order['status'] == 'monitoring_equity'
        assert order['equity_limit_price'] == 440.0

    def test_equity_limit_requires_price(self, engine):
        result = engine.open_position(
            'SPY', 'CALL', 1, 1000.0,
            order_type='equity_limit', equity_limit_price=None
        )
        assert result['success'] is False


# ---------------------- process_pending_orders ----------------------

@pytest.mark.unit
class TestProcessPendingOrders:
    def test_fills_pending_order_creates_position(self, engine, broker):
        r = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        order = engine.order_manager.get_order(r['order_id'])
        broker.simulate_order_fill(order['broker_order_id'], 5.0)
        summary = engine.process_pending_orders()
        assert summary['fills_completed'] >= 1
        assert engine.position_manager.has_position(order['option_symbol'])
        updated = engine.order_manager.get_order(r['order_id'])
        assert updated['status'] == 'filled'

    def test_broker_rejection_marks_rejected(self, engine, broker):
        r = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        order = engine.order_manager.get_order(r['order_id'])
        broker.orders[order['broker_order_id']]['status'] = 'rejected'
        engine.process_pending_orders()
        assert engine.order_manager.get_order(r['order_id'])['status'] == 'rejected'

    def test_broker_cancellation_marks_canceled_not_rejected(self, engine, broker):
        """Bug regression: a broker-reported 'canceled' status was previously
        being mapped to mark_order_rejected, polluting the rejected status."""
        r = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        order = engine.order_manager.get_order(r['order_id'])
        broker.orders[order['broker_order_id']]['status'] = 'canceled'
        engine.process_pending_orders()
        final = engine.order_manager.get_order(r['order_id'])
        assert final['status'] == 'canceled'

    def test_fill_into_existing_position_uses_add_to_position(self, engine, broker):
        # First fill creates the position
        r1 = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        o1 = engine.order_manager.get_order(r1['order_id'])
        broker.simulate_order_fill(o1['broker_order_id'], 5.0)
        engine.process_pending_orders()

        # Second order fills at different price into same option_symbol
        r2 = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        o2 = engine.order_manager.get_order(r2['order_id'])
        # MockBroker.get_option_contracts returns same option_symbol regardless
        broker.simulate_order_fill(o2['broker_order_id'], 7.0)
        engine.process_pending_orders()

        pos = engine.position_manager.get_position(o2['option_symbol'])
        # weighted average of two fills (both same qty since same position_size+premium)
        assert pos['total_contracts'] > o1['requested_qty']

    def test_broker_status_call_error_recorded(self, engine, broker):
        r = engine.open_position('SPY', 'CALL', 1, 1000.0, strike=450.0)
        order = engine.order_manager.get_order(r['order_id'])
        original = broker.get_order_status

        def fail(oid):
            if oid == order['broker_order_id']:
                raise RuntimeError("broker down")
            return original(oid)
        broker.get_order_status = fail
        summary = engine.process_pending_orders()
        assert len(summary['errors']) >= 1


# ---------------------- close_position ----------------------

@pytest.mark.unit
class TestClosePosition:
    def _open_existing(self, engine, broker, option='SPY250131C00450000', qty=2, entry=5.0):
        engine.position_manager.open_position(
            option, 'SPY', 'CALL', 450.0, 1, qty, entry, 450.0,
            stop_loss_price=440.0, take_profit_price=460.0
        )
        broker.add_position(option, qty, entry)
        return option

    def test_close_unknown_position(self, engine):
        result = engine.close_position('NOPE', 1)
        assert result['success'] is False

    def test_overclose_blocked(self, engine, broker):
        opt = self._open_existing(engine, broker, qty=2)
        result = engine.close_position(opt, 10)
        assert result['success'] is False

    def test_close_full_fills_and_removes(self, engine, broker):
        opt = self._open_existing(engine, broker, qty=2, entry=5.0)
        # Patch broker order fill to instantly fill
        original_place = broker.place_market_order

        def place_and_fill(symbol, qty, side):
            o = original_place(symbol, qty, side)
            broker.simulate_order_fill(o['order_id'], 7.0)
            return o
        broker.place_market_order = place_and_fill

        with patch('assisted_trading.backend.trading_engine.time.sleep'):
            result = engine.close_position(opt, 2)
        assert result['success'] is True
        assert engine.position_manager.get_position(opt) is None


# ---------------------- Stop Loss / Take Profit ----------------------

@pytest.mark.unit
class TestStopLoss:
    def test_no_positions_returns_empty(self, engine):
        assert engine.check_stop_loss() == []

    def test_sl_not_hit_call(self, engine, broker):
        engine.position_manager.open_position(
            'SPY1', 'SPY', 'CALL', 450.0, 1, 1, 5.0, 450.0,
            stop_loss_price=440.0
        )
        broker.add_position('SPY1', 1, 5.0)
        # current SPY price is 450 in mock, > 440, no trigger
        results = engine.check_stop_loss()
        assert results == []

    def test_sl_hit_call_auto_sells(self, engine, broker):
        engine.position_manager.open_position(
            'SPY1', 'SPY', 'CALL', 450.0, 1, 1, 5.0, 450.0,
            stop_loss_price=460.0  # SL above current — triggers
        )
        broker.add_position('SPY1', 1, 5.0)
        # Patch broker placement to instantly fill the close
        original_place = broker.place_market_order

        def place_and_fill(symbol, qty, side):
            o = original_place(symbol, qty, side)
            broker.simulate_order_fill(o['order_id'], 4.0)
            return o
        broker.place_market_order = place_and_fill

        with patch('assisted_trading.backend.trading_engine.time.sleep'):
            results = engine.check_stop_loss()
        assert len(results) == 1
        assert results[0].get('reason') == 'stop_loss'
        assert engine.position_manager.get_position('SPY1') is None

    def test_sl_hit_put_triggers_when_price_rises(self, engine, broker):
        engine.position_manager.open_position(
            'SPY1', 'SPY', 'PUT', 450.0, 1, 1, 5.0, 450.0,
            stop_loss_price=440.0  # PUT SL triggers if price >= SL
        )
        broker.add_position('SPY1', 1, 5.0)
        original_place = broker.place_market_order

        def place_and_fill(symbol, qty, side):
            o = original_place(symbol, qty, side)
            broker.simulate_order_fill(o['order_id'], 4.0)
            return o
        broker.place_market_order = place_and_fill

        with patch('assisted_trading.backend.trading_engine.time.sleep'):
            results = engine.check_stop_loss()
        assert len(results) == 1

    def test_sl_cleanup_when_broker_position_missing(self, engine, broker):
        # Position in our DB but not in broker — should be cleaned up, not sold
        engine.position_manager.open_position(
            'SPY1', 'SPY', 'CALL', 450.0, 1, 1, 5.0, 450.0,
            stop_loss_price=460.0
        )
        # Note: no broker.add_position
        results = engine.check_stop_loss()
        assert results == []
        assert engine.position_manager.get_position('SPY1') is None


@pytest.mark.unit
class TestTakeProfit:
    def test_no_tp_set_does_not_trigger(self, engine, broker):
        engine.position_manager.open_position(
            'SPY1', 'SPY', 'CALL', 450.0, 1, 1, 5.0, 450.0
        )
        broker.add_position('SPY1', 1, 5.0)
        results = engine.check_take_profit()
        assert results == []

    def test_tp_hit_call_triggers(self, engine, broker):
        engine.position_manager.open_position(
            'SPY1', 'SPY', 'CALL', 450.0, 1, 1, 5.0, 450.0,
            take_profit_price=440.0  # TP below current — CALL triggers since 450 >= 440
        )
        broker.add_position('SPY1', 1, 5.0)
        original_place = broker.place_market_order

        def place_and_fill(symbol, qty, side):
            o = original_place(symbol, qty, side)
            broker.simulate_order_fill(o['order_id'], 10.0)
            return o
        broker.place_market_order = place_and_fill

        with patch('assisted_trading.backend.trading_engine.time.sleep'):
            results = engine.check_take_profit()
        assert len(results) == 1
        assert engine.position_manager.get_position('SPY1') is None


# ---------------------- cancel_pending_order ----------------------

@pytest.mark.unit
class TestCancelPendingOrder:
    def test_cancel_unknown_returns_friendly_message(self, engine):
        result = engine.cancel_pending_order('MISSING')
        assert result['success'] is False
        assert 'not found' in result['message'].lower()

    def test_cancel_filled_blocked_with_hint(self, engine):
        oid = engine.order_manager.create_order(
            'SPY', 'CALL', 1, 1000.0, 'equity_market'
        )
        engine.order_manager.mark_order_filled(oid, 1, 5.0)
        result = engine.cancel_pending_order(oid)
        assert result['success'] is False
        assert 'filled' in result['message'].lower()

    def test_cancel_already_canceled(self, engine):
        oid = engine.order_manager.create_order(
            'SPY', 'CALL', 1, 1000.0, 'equity_market'
        )
        engine.order_manager.mark_order_canceled(oid)
        result = engine.cancel_pending_order(oid)
        assert result['success'] is False

    def test_cancel_pending_succeeds(self, engine):
        oid = engine.order_manager.create_order(
            'SPY', 'CALL', 1, 1000.0, 'equity_market'
        )
        result = engine.cancel_pending_order(oid)
        assert result['success'] is True
        assert engine.order_manager.get_order(oid)['status'] == 'canceled'

    def test_cancel_pending_with_broker_order_calls_broker(self, engine, broker):
        oid = engine.order_manager.create_order(
            'SPY', 'CALL', 1, 1000.0, 'equity_market'
        )
        engine.order_manager.update_order_status(
            oid, 'pending_fill', broker_order_id='BRK1',
            option_symbol='SPY250131C00450000', strike=450.0, requested_qty=1
        )
        broker.orders['BRK1'] = {'order_id': 'BRK1', 'status': 'accepted', 'qty': 1}
        result = engine.cancel_pending_order(oid)
        assert result['success'] is True
        assert broker.orders['BRK1']['status'] == 'canceled'

    def test_cancel_continues_when_broker_cancel_raises(self, engine, broker):
        oid = engine.order_manager.create_order(
            'SPY', 'CALL', 1, 1000.0, 'equity_market'
        )
        engine.order_manager.update_order_status(
            oid, 'pending_fill', broker_order_id='BRK2',
            option_symbol='SPY250131C00450000', strike=450.0, requested_qty=1
        )
        broker.cancel_order = MagicMock(side_effect=RuntimeError('network'))
        result = engine.cancel_pending_order(oid)
        # Should still mark order canceled in our DB
        assert result['success'] is True
        assert engine.order_manager.get_order(oid)['status'] == 'canceled'


# ---------------------- Misc helpers ----------------------

@pytest.mark.unit
class TestEngineHelpers:
    def test_calculate_contracts_zero_premium(self, engine):
        assert engine.calculate_contracts_from_position_size(1000.0, 0.0) == 0

    def test_calculate_contracts_basic(self, engine):
        # 1000 / (5*100) = 2
        assert engine.calculate_contracts_from_position_size(1000.0, 5.0) == 2

    def test_calculate_contracts_min_one(self, engine):
        # 100 / (5*100) = 0 -> min 1
        assert engine.calculate_contracts_from_position_size(100.0, 5.0) == 1

    def test_place_market_option_order(self, engine, broker):
        order = engine.place_option_order('OPT1', 1, 5.0, 5.5, 'market')
        assert order['type'] == 'market'

    def test_place_limit_option_order_floors_midpoint(self, engine):
        order = engine.place_option_order('OPT1', 1, 5.03, 5.07, 'limit')
        # midpoint 5.05 -> floor 5.05
        assert order['limit_price'] == pytest.approx(5.05, abs=1e-6)

    def test_get_option_for_strike_broker_error(self, engine, broker):
        broker.get_option_contracts = MagicMock(side_effect=RuntimeError('x'))
        sym, q = engine.get_option_for_strike('SPY', 'CALL', 1, 450.0)
        assert sym is None and q is None
