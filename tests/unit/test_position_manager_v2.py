"""
Unit tests for PositionManagerV2.
"""
import pytest


@pytest.mark.unit
class TestOpenAndQuery:
    def test_open_position_creates_row(self, position_manager):
        position_manager.open_position(
            option_symbol='SPY250131C00450000', symbol='SPY',
            contract_type='CALL', strike=450.0, dte=5,
            total_contracts=10, entry_price=5.0, underlying_entry_price=450.0
        )
        assert position_manager.has_position('SPY250131C00450000')
        p = position_manager.get_position('SPY250131C00450000')
        assert p['remaining_contracts'] == 10

    def test_has_any_position(self, position_manager):
        assert position_manager.has_any_position() is False
        position_manager.open_position(
            'X', 'SPY', 'CALL', 450.0, 5, 1, 1.0, 450.0
        )
        assert position_manager.has_any_position() is True

    def test_has_position_false_when_zero_remaining(self, position_manager):
        position_manager.open_position(
            'Z', 'SPY', 'CALL', 450.0, 5, 1, 1.0, 450.0
        )
        position_manager.close_position('Z', 1, 2.0)
        assert position_manager.has_position('Z') is False


@pytest.mark.unit
class TestAddToPosition:
    def test_add_to_position_weighted_average(self, position_manager):
        position_manager.open_position(
            'A', 'SPY', 'CALL', 450.0, 5, 10, 5.0, 450.0
        )
        position_manager.add_to_position('A', 10, 7.0, 451.0)
        p = position_manager.get_position('A')
        assert p['total_contracts'] == 20
        assert p['remaining_contracts'] == 20
        # weighted average: (10*5 + 10*7)/20 = 6.0
        assert abs(p['entry_price'] - 6.0) < 1e-6

    def test_add_to_nonexistent_position_raises(self, position_manager):
        with pytest.raises(ValueError):
            position_manager.add_to_position('NOPE', 1, 1.0, 1.0)


@pytest.mark.unit
class TestClosePosition:
    def test_partial_close_keeps_position(self, position_manager):
        position_manager.open_position(
            'P', 'SPY', 'CALL', 450.0, 5, 10, 5.0, 450.0
        )
        rec = position_manager.close_position('P', 4, 7.0)
        # P&L = (7-5) * 4 * 100 = 800
        assert abs(rec['realized_pnl'] - 800.0) < 1e-6
        p = position_manager.get_position('P')
        assert p is not None
        assert p['remaining_contracts'] == 6

    def test_full_close_deletes_position(self, position_manager):
        position_manager.open_position(
            'F', 'SPY', 'CALL', 450.0, 5, 5, 5.0, 450.0
        )
        position_manager.close_position('F', 5, 6.0)
        assert position_manager.get_position('F') is None

    def test_overclose_raises(self, position_manager):
        position_manager.open_position(
            'O', 'SPY', 'CALL', 450.0, 5, 2, 5.0, 450.0
        )
        with pytest.raises(ValueError):
            position_manager.close_position('O', 10, 6.0)

    def test_close_nonexistent_raises(self, position_manager):
        with pytest.raises(ValueError):
            position_manager.close_position('GHOST', 1, 1.0)

    def test_close_pnl_negative_loss(self, position_manager):
        position_manager.open_position(
            'L', 'SPY', 'CALL', 450.0, 5, 1, 10.0, 450.0
        )
        rec = position_manager.close_position('L', 1, 5.0)
        # (5-10) * 1 * 100 = -500
        assert abs(rec['realized_pnl'] - (-500.0)) < 1e-6


@pytest.mark.unit
class TestSlTpUpdates:
    def test_update_stop_loss(self, position_manager):
        position_manager.open_position(
            'S', 'SPY', 'CALL', 450.0, 5, 1, 5.0, 450.0
        )
        position_manager.update_stop_loss('S', 440.0)
        assert position_manager.get_position('S')['stop_loss_price'] == 440.0

    def test_update_take_profit(self, position_manager):
        position_manager.open_position(
            'T', 'SPY', 'CALL', 450.0, 5, 1, 5.0, 450.0
        )
        position_manager.update_take_profit('T', 460.0)
        assert position_manager.get_position('T')['take_profit_price'] == 460.0


@pytest.mark.unit
class TestLimits:
    def test_can_open_under_limits(self, position_manager):
        ok, _ = position_manager.can_open_new_position('SPY')
        assert ok is True

    def test_max_simultaneous_blocks(self, position_manager):
        # fixture allows max 5
        for i in range(5):
            position_manager.open_position(
                f'sym{i}', 'SPY', 'CALL', 450.0, 5, 1, 1.0, 450.0
            )
        ok, reason = position_manager.can_open_new_position('AAPL')
        assert ok is False
        assert 'simultaneous' in reason.lower()

    def test_max_per_symbol_blocks(self, position_manager):
        for i in range(2):
            position_manager.open_position(
                f'spy{i}', 'SPY', 'CALL', 450.0, 5, 1, 1.0, 450.0
            )
        ok, reason = position_manager.can_open_new_position('SPY')
        assert ok is False
        assert 'SPY' in reason


@pytest.mark.unit
class TestReconcileWithBroker:
    def test_removes_stale_positions(self, position_manager):
        position_manager.open_position(
            'STALE', 'SPY', 'CALL', 450.0, 5, 1, 1.0, 450.0
        )
        report = position_manager.reconcile_with_broker([])
        assert 'STALE' in report['removed']
        assert position_manager.get_position('STALE') is None

    def test_detects_external_positions(self, position_manager):
        broker_positions = [{'symbol': 'EXT001', 'qty': 1}]
        report = position_manager.reconcile_with_broker(broker_positions)
        assert 'EXT001' in report['added']

    def test_keeps_matching_positions(self, position_manager):
        position_manager.open_position(
            'KEEP', 'SPY', 'CALL', 450.0, 5, 1, 1.0, 450.0
        )
        report = position_manager.reconcile_with_broker([{'symbol': 'KEEP'}])
        assert 'KEEP' not in report['removed']


@pytest.mark.unit
class TestDailySummary:
    def test_empty_day(self, position_manager):
        s = position_manager.get_daily_summary('2026-01-01')
        assert s['total_trades'] == 0
        assert s['net_pnl'] == 0.0

    def test_with_wins_and_losses(self, position_manager, test_db):
        # Open then close at gain and loss to populate closes
        position_manager.open_position(
            'W', 'SPY', 'CALL', 450.0, 5, 2, 5.0, 450.0
        )
        position_manager.close_position('W', 1, 10.0)  # +500
        position_manager.close_position('W', 1, 1.0)   # -400
        from datetime import datetime
        import pytz
        today = datetime.now(pytz.timezone('US/Eastern')).strftime('%Y-%m-%d')
        s = position_manager.get_daily_summary(today)
        assert s['total_trades'] == 2
        assert s['winning_trades'] == 1
        assert s['losing_trades'] == 1
        assert abs(s['net_pnl'] - 100.0) < 1e-6
