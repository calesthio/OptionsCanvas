"""
Unit tests for State Machine
Tests state transitions, validation, and invariant checking
"""

import pytest
import pytz
from assisted_trading.backend.state_machine import (
    OrderStateMachine,
    PositionStateMachine,
    OrderState,
    PositionState,
    StateTransitionError,
    InvariantValidator
)


@pytest.mark.unit
class TestOrderStateMachine:
    """Test order state machine"""

    def test_initial_state(self):
        """Test state machine initialization"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        assert sm.current_state == OrderState.PENDING
        assert sm.order_id == 'ORDER123'
        assert len(sm.transition_history) == 1
        assert sm.transition_history[0]['to_state'] == 'pending'

    def test_valid_transition_pending_to_filled(self):
        """Test valid transition from pending to filled"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        result = sm.transition(OrderState.FILLED, reason="Order filled by broker")
        assert result is True
        assert sm.current_state == OrderState.FILLED
        assert len(sm.transition_history) == 2

    def test_valid_transition_monitoring_to_pending_fill(self):
        """Test valid transition from monitoring_equity to pending_fill"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.MONITORING_EQUITY, tz)

        result = sm.transition(OrderState.PENDING_FILL, reason="Equity limit reached")
        assert result is True
        assert sm.current_state == OrderState.PENDING_FILL

    def test_invalid_transition_raises_error(self):
        """Test that invalid transitions raise StateTransitionError"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.FILLED, tz)

        # Cannot transition from terminal state
        with pytest.raises(StateTransitionError) as exc_info:
            sm.transition(OrderState.PENDING, reason="Invalid")

        assert "Invalid transition" in str(exc_info.value)
        assert "filled -> pending" in str(exc_info.value)

    def test_cannot_leave_terminal_state(self):
        """Test that terminal states cannot be left"""
        tz = pytz.timezone('US/Eastern')

        terminal_states = [
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELED,
            OrderState.TIMEOUT,
        ]

        for terminal_state in terminal_states:
            sm = OrderStateMachine('ORDER123', terminal_state, tz)
            assert sm.is_terminal() is True
            assert len(sm.get_valid_next_states()) == 0

    def test_can_transition_to(self):
        """Test can_transition_to method"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        assert sm.can_transition_to(OrderState.FILLED) is True
        assert sm.can_transition_to(OrderState.REJECTED) is True
        assert sm.can_transition_to(OrderState.PENDING) is False

    def test_get_valid_next_states(self):
        """Test getting valid next states"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        valid_states = sm.get_valid_next_states()
        assert OrderState.FILLED in valid_states
        assert OrderState.REJECTED in valid_states
        assert OrderState.CANCELED in valid_states
        assert OrderState.PENDING not in valid_states

    def test_transition_history_tracking(self):
        """Test that transition history is properly tracked"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        sm.transition(OrderState.PENDING_FILL, reason="Submitted to broker")
        sm.transition(OrderState.FILLED, reason="Order filled", price=10.50, qty=5)

        history = sm.get_transition_history()
        assert len(history) == 3  # Initial + 2 transitions

        assert history[1]['from_state'] == 'pending'
        assert history[1]['to_state'] == 'pending_fill'
        assert history[1]['reason'] == "Submitted to broker"

        assert history[2]['from_state'] == 'pending_fill'
        assert history[2]['to_state'] == 'filled'
        assert history[2]['metadata']['price'] == 10.50
        assert history[2]['metadata']['qty'] == 5

    def test_transition_with_metadata(self):
        """Test transitions with additional metadata"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        sm.transition(
            OrderState.FILLED,
            reason="Filled by broker",
            broker_order_id="BROKER999",
            filled_price=10.25,
            filled_qty=10
        )

        history = sm.get_transition_history()
        last_transition = history[-1]

        assert last_transition['metadata']['broker_order_id'] == "BROKER999"
        assert last_transition['metadata']['filled_price'] == 10.25
        assert last_transition['metadata']['filled_qty'] == 10


@pytest.mark.unit
class TestPositionStateMachine:
    """Test position state machine"""

    def test_initial_state(self):
        """Test position state machine initialization"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.ACTIVE, tz)

        assert sm.current_state == PositionState.ACTIVE
        assert sm.position_id == 'POS123'

    def test_valid_transition_active_to_closing(self):
        """Test valid transition from active to closing"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.ACTIVE, tz)

        result = sm.transition(PositionState.CLOSING, reason="User requested close")
        assert result is True
        assert sm.current_state == PositionState.CLOSING

    def test_stop_loss_triggered_flow(self):
        """Test stop loss triggered flow"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.ACTIVE, tz)

        # Trigger stop loss
        sm.transition(PositionState.STOP_LOSS_TRIGGERED, reason="Price hit stop loss")
        assert sm.current_state == PositionState.STOP_LOSS_TRIGGERED

        # Move to closing
        sm.transition(PositionState.CLOSING, reason="Submitting close order")
        assert sm.current_state == PositionState.CLOSING

        # Close
        sm.transition(PositionState.CLOSED, reason="Close order filled")
        assert sm.current_state == PositionState.CLOSED
        assert sm.is_terminal() is True

    def test_take_profit_triggered_flow(self):
        """Test take profit triggered flow"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.ACTIVE, tz)

        # Trigger take profit
        sm.transition(PositionState.TAKE_PROFIT_TRIGGERED, reason="Price hit take profit")
        assert sm.current_state == PositionState.TAKE_PROFIT_TRIGGERED

        # Direct to closed
        sm.transition(PositionState.CLOSED, reason="Close order filled immediately")
        assert sm.current_state == PositionState.CLOSED

    def test_invalid_position_transition(self):
        """Test invalid position transition"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.CLOSED, tz)

        # Cannot transition from closed state
        with pytest.raises(StateTransitionError):
            sm.transition(PositionState.ACTIVE, reason="Invalid")


@pytest.mark.unit
class TestInvariantValidator:
    """Test invariant validation"""

    def test_valid_order_invariants(self):
        """Test that valid orders pass invariant checks"""
        order = {
            'order_id': 'ORDER123',
            'status': 'pending',
            'position_size': 1000.0,
            'order_type': 'equity_market'
        }

        is_valid, error = InvariantValidator.validate_order_invariants(order)
        assert is_valid is True
        assert error is None

    def test_filled_order_must_have_fill_data(self):
        """Test that filled orders must have fill data"""
        order = {
            'order_id': 'ORDER123',
            'status': 'filled',
            'position_size': 1000.0,
            # Missing filled_qty, filled_avg_price, fill_time
        }

        is_valid, error = InvariantValidator.validate_order_invariants(order)
        assert is_valid is False
        assert "filled_qty" in error

    def test_filled_order_with_complete_data(self):
        """Test that filled orders with complete data pass"""
        order = {
            'order_id': 'ORDER123',
            'status': 'filled',
            'position_size': 1000.0,
            'filled_qty': 10,
            'filled_avg_price': 10.50,
            'fill_time': '2025-01-21T10:30:00'
        }

        is_valid, error = InvariantValidator.validate_order_invariants(order)
        assert is_valid is True

    def test_order_missing_id(self):
        """Test that orders must have ID"""
        order = {
            'status': 'pending',
            'position_size': 1000.0
        }

        is_valid, error = InvariantValidator.validate_order_invariants(order)
        assert is_valid is False
        assert "order_id" in error

    def test_position_size_must_be_positive(self):
        """Test that position size must be positive"""
        order = {
            'order_id': 'ORDER123',
            'status': 'pending',
            'position_size': -1000.0  # Negative!
        }

        is_valid, error = InvariantValidator.validate_order_invariants(order)
        assert is_valid is False
        assert "positive" in error

    def test_equity_limit_order_must_have_limit_price(self):
        """Test that equity_limit orders must have limit price"""
        order = {
            'order_id': 'ORDER123',
            'status': 'monitoring_equity',
            'position_size': 1000.0,
            'order_type': 'equity_limit',
            # Missing equity_limit_price
        }

        is_valid, error = InvariantValidator.validate_order_invariants(order)
        assert is_valid is False
        assert "equity_limit_price" in error

    def test_valid_position_invariants(self):
        """Test valid position passes invariant checks"""
        position = {
            'option_symbol': 'SPY260115C00595000',
            'symbol': 'SPY',
            'status': 'open',
            'total_contracts': 10,
            'remaining_contracts': 10,
            'entry_price': 10.50,
            'entry_time': '2025-01-21T10:00:00'
        }

        is_valid, error = InvariantValidator.validate_position_invariants(position)
        assert is_valid is True

    def test_position_quantity_must_be_positive(self):
        """Position contract counts must be sane."""
        position = {
            'option_symbol': 'SPY260115C00595000',
            'status': 'open',
            'total_contracts': 0,  # Zero contracts!
            'remaining_contracts': 0,
            'entry_price': 10.50
        }

        is_valid, error = InvariantValidator.validate_position_invariants(position)
        assert is_valid is False
        assert "total_contracts" in error

    def test_closed_position_must_have_close_time(self):
        """Closed positions must have exit_time, zero remaining, and exit_price."""
        position = {
            'option_symbol': 'SPY260115C00595000',
            'status': 'closed',
            'total_contracts': 10,
            'remaining_contracts': 0,
            'entry_price': 10.50,
            'entry_time': '2025-01-21T10:00:00',
            'exit_price': 12.00,
            # Missing exit_time
        }

        is_valid, error = InvariantValidator.validate_position_invariants(position)
        assert is_valid is False
        assert "exit_time" in error


@pytest.mark.unit
class TestStateTransitionEdgeCases:
    """Test edge cases and complex scenarios"""

    def test_multiple_cancel_attempts(self):
        """Test that we can't transition after cancellation"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        # Cancel order
        sm.transition(OrderState.CANCELED, reason="User canceled")

        # Try to fill canceled order - should fail
        with pytest.raises(StateTransitionError):
            sm.transition(OrderState.FILLED, reason="Too late!")

    def test_concurrent_state_checks(self):
        """Test checking state before and after transition"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        # Check before
        assert sm.can_transition_to(OrderState.FILLED) is True
        assert sm.is_terminal() is False

        # Transition
        sm.transition(OrderState.FILLED, reason="Order filled")

        # Check after
        assert sm.can_transition_to(OrderState.CANCELED) is False
        assert sm.is_terminal() is True
