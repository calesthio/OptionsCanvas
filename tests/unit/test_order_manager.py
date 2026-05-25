"""
Unit tests for OrderManager
Tests order creation, state transitions, and queries
"""

import pytest
from datetime import datetime
import pytz


@pytest.mark.unit
class TestOrderCreation:
    """Test order creation"""

    def test_create_market_order(self, order_manager):
        """Test creating a market order"""
        order_id = order_manager.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        assert order_id is not None
        assert len(order_id) > 0

        # Verify order was created
        order = order_manager.get_order(order_id)
        assert order is not None
        assert order['symbol'] == 'SPY'
        assert order['contract_type'] == 'CALL'
        assert order['dte'] == 30
        assert order['position_size'] == 1000.0
        assert order['order_type'] == 'equity_market'
        assert order['status'] == 'pending'

    def test_create_limit_order(self, order_manager):
        """Test creating a limit order"""
        order_id = order_manager.create_order(
            symbol='AAPL',
            contract_type='PUT',
            dte=45,
            position_size=2000.0,
            order_type='equity_limit',
            equity_limit_price=175.0
        )

        order = order_manager.get_order(order_id)
        assert order['order_type'] == 'equity_limit'
        assert order['equity_limit_price'] == 175.0
        assert order['status'] == 'monitoring_equity'

    def test_create_order_with_stop_loss(self, order_manager):
        """Test creating order with stop loss"""
        order_id = order_manager.create_order(
            symbol='NVDA',
            contract_type='CALL',
            dte=60,
            position_size=1500.0,
            order_type='equity_market',
            stop_loss_price=440.0
        )

        order = order_manager.get_order(order_id)
        assert order['stop_loss_price'] == 440.0

    def test_create_order_with_take_profit(self, order_manager):
        """Test creating order with take profit"""
        order_id = order_manager.create_order(
            symbol='MSFT',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market',
            take_profit_price=380.0
        )

        order = order_manager.get_order(order_id)
        assert order['take_profit_price'] == 380.0


@pytest.mark.unit
class TestOrderStateTransitions:
    """Test order state transitions"""

    def test_transition_to_pending_fill(self, order_manager):
        """Test transition from monitoring_equity to pending_fill"""
        # Create limit order (starts in monitoring_equity)
        order_id = order_manager.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_limit',
            equity_limit_price=450.0
        )

        # Verify initial state
        order = order_manager.get_order(order_id)
        assert order['status'] == 'monitoring_equity'

        # Transition to pending_fill
        order_manager.transition_to_pending_fill(
            order_id=order_id,
            broker_order_id='BROKER123',
            option_symbol='SPY250131C00450000',
            strike=450.0,
            requested_qty=10
        )

        # Verify new state
        order = order_manager.get_order(order_id)
        assert order['status'] == 'pending_fill'
        assert order['broker_order_id'] == 'BROKER123'
        assert order['option_symbol'] == 'SPY250131C00450000'
        assert order['strike'] == 450.0
        assert order['requested_qty'] == 10

    def test_transition_to_filled(self, order_manager):
        """Test transition to filled state"""
        # Create order
        order_id = order_manager.create_order(
            symbol='AAPL',
            contract_type='PUT',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        # Mark as filled
        order_manager.transition_to_filled(
            order_id=order_id,
            filled_qty=5,
            filled_avg_price=10.50
        )

        # Verify filled state
        order = order_manager.get_order(order_id)
        assert order['status'] == 'filled'
        assert order['filled_qty'] == 5
        assert order['filled_avg_price'] == 10.50
        assert order['fill_time'] is not None

    def test_mark_order_rejected(self, order_manager):
        """Test marking order as rejected"""
        order_id = order_manager.create_order(
            symbol='MSFT',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        order_manager.mark_order_rejected(order_id, reason="Insufficient funds")

        order = order_manager.get_order(order_id)
        assert order['status'] == 'rejected'

    def test_mark_order_canceled(self, order_manager):
        """Test marking order as canceled"""
        order_id = order_manager.create_order(
            symbol='NVDA',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        order_manager.mark_order_canceled(order_id)

        order = order_manager.get_order(order_id)
        assert order['status'] == 'canceled'
        assert order['cancel_time'] is not None

    def test_mark_order_timeout(self, order_manager):
        """Test marking order as timeout"""
        order_id = order_manager.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        order_manager.mark_order_timeout(order_id)

        order = order_manager.get_order(order_id)
        assert order['status'] == 'timeout'


@pytest.mark.unit
class TestOrderQueries:
    """Test order query methods"""

    def test_get_order_not_found(self, order_manager):
        """Test querying non-existent order"""
        order = order_manager.get_order('INVALID_ID')
        assert order is None

    def test_get_pending_orders(self, order_manager):
        """Test getting all pending orders"""
        # Create mix of orders
        pending_id = order_manager.create_order(
            symbol='SPY', contract_type='CALL', dte=30,
            position_size=1000.0, order_type='equity_market'
        )

        monitoring_id = order_manager.create_order(
            symbol='AAPL', contract_type='PUT', dte=30,
            position_size=1000.0, order_type='equity_limit',
            equity_limit_price=180.0
        )

        filled_id = order_manager.create_order(
            symbol='MSFT', contract_type='CALL', dte=30,
            position_size=1000.0, order_type='equity_market'
        )
        order_manager.mark_order_filled(filled_id, 5, 10.0)

        # Get pending orders
        pending_orders = order_manager.get_pending_orders()

        # Should include pending and monitoring_equity, not filled
        statuses = [o['status'] for o in pending_orders]
        assert 'pending' in statuses
        assert 'monitoring_equity' in statuses
        assert 'filled' not in statuses

    def test_get_orders_by_status(self, order_manager):
        """Test getting orders by specific status"""
        # Create multiple filled orders
        for i in range(3):
            order_id = order_manager.create_order(
                symbol='SPY',
                contract_type='CALL',
                dte=30,
                position_size=1000.0,
                order_type='equity_market'
            )
            order_manager.mark_order_filled(order_id, 5, 10.0 + i)

        filled_orders = order_manager.get_orders_by_status('filled')
        assert len(filled_orders) >= 3


@pytest.mark.unit
class TestOrderCancellation:
    """Test order cancellation"""

    def test_cancel_pending_order(self, order_manager):
        """Test canceling a pending order"""
        order_id = order_manager.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        result = order_manager.cancel_order(order_id)
        assert result is True

        order = order_manager.get_order(order_id)
        assert order['status'] == 'canceled'

    def test_cancel_monitoring_equity_order(self, order_manager):
        """Test canceling an order in monitoring_equity state"""
        order_id = order_manager.create_order(
            symbol='AAPL',
            contract_type='PUT',
            dte=30,
            position_size=1000.0,
            order_type='equity_limit',
            equity_limit_price=180.0
        )

        result = order_manager.cancel_order(order_id)
        assert result is True

        order = order_manager.get_order(order_id)
        assert order['status'] == 'canceled'

    def test_cannot_cancel_filled_order(self, order_manager):
        """Test that filled orders cannot be canceled"""
        order_id = order_manager.create_order(
            symbol='MSFT',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )
        order_manager.mark_order_filled(order_id, 5, 10.0)

        result = order_manager.cancel_order(order_id)
        assert result is False

        # Status should still be filled
        order = order_manager.get_order(order_id)
        assert order['status'] == 'filled'

    def test_cancel_nonexistent_order(self, order_manager):
        """Test canceling non-existent order"""
        result = order_manager.cancel_order('INVALID_ID')
        assert result is False


@pytest.mark.unit
class TestOrderInvariants:
    """Test order invariants"""

    def test_order_id_is_unique(self, order_manager):
        """Test that order IDs are unique"""
        order_ids = set()

        for i in range(10):
            order_id = order_manager.create_order(
                symbol='SPY',
                contract_type='CALL',
                dte=30,
                position_size=1000.0,
                order_type='equity_market'
            )
            order_ids.add(order_id)

        # All IDs should be unique
        assert len(order_ids) == 10

    def test_timestamps_are_set(self, order_manager):
        """Test that timestamps are properly set"""
        order_id = order_manager.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        order = order_manager.get_order(order_id)
        assert order['submit_time'] is not None

        # Mark as filled
        order_manager.mark_order_filled(order_id, 5, 10.0)
        order = order_manager.get_order(order_id)
        assert order['fill_time'] is not None

    def test_status_always_valid(self, order_manager):
        """Test that order status is always valid"""
        valid_statuses = [
            'pending', 'monitoring_equity', 'pending_fill',
            'filled', 'rejected', 'canceled', 'timeout'
        ]

        order_id = order_manager.create_order(
            symbol='SPY',
            contract_type='CALL',
            dte=30,
            position_size=1000.0,
            order_type='equity_market'
        )

        order = order_manager.get_order(order_id)
        assert order['status'] in valid_statuses
