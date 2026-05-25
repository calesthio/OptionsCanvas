"""
Property-Based Tests for State Machines
Tests state transition logic with thousands of random scenarios
"""

import pytest
from hypothesis import given, strategies as st, assume, settings
import pytz

from assisted_trading.backend.state_machine import (
    OrderStateMachine,
    PositionStateMachine,
    OrderState,
    PositionState,
    StateTransitionError
)


# ========== Strategies ==========

order_states = st.sampled_from(list(OrderState))
position_states = st.sampled_from(list(PositionState))

# Valid transitions for orders
valid_order_transitions = {
    OrderState.PENDING: [OrderState.PENDING_FILL, OrderState.FILLED,
                        OrderState.REJECTED, OrderState.CANCELED, OrderState.TIMEOUT],
    OrderState.MONITORING_EQUITY: [OrderState.PENDING_FILL, OrderState.CANCELED, OrderState.TIMEOUT],
    OrderState.PENDING_FILL: [OrderState.FILLED, OrderState.REJECTED,
                              OrderState.CANCELED, OrderState.TIMEOUT],
}


# ========== Property Tests ==========

@pytest.mark.property
class TestOrderStateMachineProperties:
    """Property-based tests for OrderStateMachine"""

    @given(initial_state=order_states)
    @settings(max_examples=50, deadline=500)
    def test_state_machine_initialization(self, initial_state):
        """Property: State machine initializes with given state"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', initial_state, tz)

        assert sm.current_state == initial_state
        assert len(sm.transition_history) == 1
        assert sm.transition_history[0]['to_state'] == initial_state.value

    @given(
        from_state=st.sampled_from([OrderState.PENDING, OrderState.MONITORING_EQUITY, OrderState.PENDING_FILL]),
        to_state=order_states
    )
    @settings(max_examples=100, deadline=500)
    def test_transition_validation(self, from_state, to_state):
        """Property: Transitions are validated correctly"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', from_state, tz)

        # Check if transition should be valid
        expected_valid = to_state in valid_order_transitions.get(from_state, [])

        if expected_valid:
            # Should succeed
            result = sm.transition(to_state, reason="Test transition")
            assert result is True
            assert sm.current_state == to_state
        else:
            # Should fail
            with pytest.raises(StateTransitionError):
                sm.transition(to_state, reason="Invalid transition")

    @given(
        state=st.sampled_from([OrderState.PENDING, OrderState.MONITORING_EQUITY, OrderState.PENDING_FILL])
    )
    @settings(max_examples=50, deadline=500)
    def test_non_terminal_states_have_transitions(self, state):
        """Property: Non-terminal states have at least one valid transition"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', state, tz)

        valid_transitions = sm.get_valid_next_states()

        # Property: Non-terminal states can transition
        assert len(valid_transitions) > 0
        assert sm.is_terminal() is False

    @given(
        terminal_state=st.sampled_from([OrderState.FILLED, OrderState.REJECTED,
                                       OrderState.CANCELED, OrderState.TIMEOUT])
    )
    @settings(max_examples=50, deadline=500)
    def test_terminal_states_have_no_transitions(self, terminal_state):
        """Property: Terminal states have no valid transitions"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', terminal_state, tz)

        valid_transitions = sm.get_valid_next_states()

        # Property: Terminal states cannot transition
        assert len(valid_transitions) == 0
        assert sm.is_terminal() is True

    @given(
        transitions=st.lists(
            st.sampled_from([OrderState.PENDING_FILL, OrderState.FILLED]),
            min_size=1,
            max_size=10
        )
    )
    @settings(max_examples=50, deadline=1000)
    def test_transition_history_accumulates(self, transitions):
        """Property: Transition history accumulates correctly"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        initial_history_len = len(sm.transition_history)

        # Try to apply transitions (some may fail)
        successful_transitions = 0
        for to_state in transitions:
            if sm.can_transition_to(to_state):
                sm.transition(to_state, reason=f"Transition to {to_state.value}")
                successful_transitions += 1

                # If terminal, stop
                if sm.is_terminal():
                    break

        # Property: History length increases with successful transitions
        expected_len = initial_history_len + successful_transitions
        assert len(sm.transition_history) == expected_len

    @given(metadata_keys=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=5))
    @settings(max_examples=50, deadline=500)
    def test_transition_metadata_stored(self, metadata_keys):
        """Property: Transition metadata is stored correctly"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        # Create metadata dictionary
        metadata = {key: f"value_{key}" for key in metadata_keys}

        # Transition with metadata
        sm.transition(OrderState.FILLED, reason="Test", **metadata)

        # Property: Metadata should be in history
        history = sm.get_transition_history()
        last_transition = history[-1]

        for key, value in metadata.items():
            assert key in last_transition['metadata']
            assert last_transition['metadata'][key] == value


@pytest.mark.property
class TestPositionStateMachineProperties:
    """Property-based tests for PositionStateMachine"""

    @given(initial_state=position_states)
    @settings(max_examples=50, deadline=500)
    def test_position_state_machine_initialization(self, initial_state):
        """Property: Position state machine initializes correctly"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', initial_state, tz)

        assert sm.current_state == initial_state
        assert len(sm.transition_history) == 1

    @given(
        trigger_type=st.sampled_from([PositionState.STOP_LOSS_TRIGGERED,
                                     PositionState.TAKE_PROFIT_TRIGGERED])
    )
    @settings(max_examples=50, deadline=500)
    def test_triggered_states_can_close(self, trigger_type):
        """Property: Triggered states can always transition to closing/closed"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.ACTIVE, tz)

        # Trigger
        sm.transition(trigger_type, reason="Price trigger hit")

        # Property: Should be able to close
        assert sm.can_transition_to(PositionState.CLOSING) is True
        assert sm.can_transition_to(PositionState.CLOSED) is True

    @given(
        path=st.lists(
            st.sampled_from([PositionState.CLOSING, PositionState.STOP_LOSS_TRIGGERED,
                           PositionState.TAKE_PROFIT_TRIGGERED]),
            min_size=1,
            max_size=5
        )
    )
    @settings(max_examples=50, deadline=1000)
    def test_position_eventually_closes(self, path):
        """Property: All position paths eventually lead to CLOSED"""
        tz = pytz.timezone('US/Eastern')
        sm = PositionStateMachine('POS123', PositionState.ACTIVE, tz)

        # Follow path
        for next_state in path:
            if sm.can_transition_to(next_state):
                sm.transition(next_state, reason=f"Moving to {next_state.value}")

                # If terminal, done
                if sm.is_terminal():
                    break

        # If we're in CLOSING, we can always get to CLOSED
        if sm.current_state == PositionState.CLOSING:
            assert sm.can_transition_to(PositionState.CLOSED) is True


@pytest.mark.property
class TestStateTransitionSymmetryProperties:
    """Property tests for state transition symmetry"""

    @given(state=order_states)
    @settings(max_examples=50, deadline=500)
    def test_can_transition_matches_valid_transitions(self, state):
        """Property: can_transition_to matches get_valid_next_states"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', state, tz)

        valid_states = sm.get_valid_next_states()

        # Property: can_transition_to should return True for all valid states
        for valid_state in valid_states:
            assert sm.can_transition_to(valid_state) is True

        # Property: All other states should return False
        for test_state in OrderState:
            if test_state not in valid_states:
                assert sm.can_transition_to(test_state) is False

    @given(
        from_state=st.sampled_from([OrderState.PENDING, OrderState.MONITORING_EQUITY]),
        to_state=order_states
    )
    @settings(max_examples=100, deadline=500)
    def test_transition_idempotency_check(self, from_state, to_state):
        """Property: Checking if a transition is valid doesn't change state"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', from_state, tz)

        initial_state = sm.current_state
        initial_history_len = len(sm.transition_history)

        # Check if transition is valid (should not change state)
        _ = sm.can_transition_to(to_state)

        # Property: State should not have changed
        assert sm.current_state == initial_state
        assert len(sm.transition_history) == initial_history_len


@pytest.mark.property
class TestStateMachineRobustnessProperties:
    """Property tests for state machine robustness"""

    @given(
        reason_length=st.integers(min_value=0, max_value=1000),
        num_transitions=st.integers(min_value=1, max_value=20)
    )
    @settings(max_examples=50, deadline=2000)
    def test_handles_long_reasons(self, reason_length, num_transitions):
        """Property: State machine handles arbitrarily long transition reasons"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        reason = "X" * reason_length

        # Try multiple transitions with long reasons
        transitions_made = 0
        current_options = [OrderState.PENDING_FILL, OrderState.FILLED, OrderState.CANCELED]

        for i in range(min(num_transitions, len(current_options))):
            next_state = current_options[i]
            if sm.can_transition_to(next_state):
                sm.transition(next_state, reason=reason)
                transitions_made += 1

                if sm.is_terminal():
                    break

        # Property: All transitions should be recorded
        assert len(sm.transition_history) >= transitions_made + 1  # +1 for initial

    @given(
        order_id_length=st.integers(min_value=1, max_value=100)
    )
    @settings(max_examples=50, deadline=500)
    def test_handles_various_order_id_lengths(self, order_id_length):
        """Property: State machine handles various order ID lengths"""
        tz = pytz.timezone('US/Eastern')
        order_id = "X" * order_id_length

        sm = OrderStateMachine(order_id, OrderState.PENDING, tz)

        # Property: Should initialize correctly
        assert sm.order_id == order_id
        assert sm.current_state == OrderState.PENDING


@pytest.mark.property
class TestTransitionSequenceProperties:
    """Property tests for valid transition sequences"""

    @given(
        sequence_length=st.integers(min_value=1, max_value=10)
    )
    @settings(max_examples=50, deadline=1000)
    def test_pending_to_filled_sequence(self, sequence_length):
        """Property: Valid sequences from PENDING to FILLED work"""
        tz = pytz.timezone('US/Eastern')
        sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)

        # Valid path: PENDING -> PENDING_FILL -> FILLED
        sm.transition(OrderState.PENDING_FILL, reason="Submitted")
        assert sm.current_state == OrderState.PENDING_FILL

        sm.transition(OrderState.FILLED, reason="Filled")
        assert sm.current_state == OrderState.FILLED

        # Property: Should be terminal now
        assert sm.is_terminal() is True

    @given(
        cancel_at_step=st.integers(min_value=0, max_value=2)
    )
    @settings(max_examples=50, deadline=500)
    def test_can_cancel_before_fill(self, cancel_at_step):
        """Property: Orders can be canceled at any non-terminal state"""
        tz = pytz.timezone('US/Eastern')

        if cancel_at_step == 0:
            # Cancel from PENDING
            sm = OrderStateMachine('ORDER123', OrderState.PENDING, tz)
            assert sm.can_transition_to(OrderState.CANCELED) is True
        elif cancel_at_step == 1:
            # Cancel from MONITORING_EQUITY
            sm = OrderStateMachine('ORDER123', OrderState.MONITORING_EQUITY, tz)
            assert sm.can_transition_to(OrderState.CANCELED) is True
        else:
            # Cancel from PENDING_FILL
            sm = OrderStateMachine('ORDER123', OrderState.PENDING_FILL, tz)
            assert sm.can_transition_to(OrderState.CANCELED) is True
