"""
Formal State Machine for Order Management
Provides explicit state transitions with validation and logging
"""

import logging
from enum import Enum
from typing import Dict, Set, Optional, Callable, Any
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)


class OrderState(Enum):
    """Order states"""
    PENDING = "pending"
    MONITORING_EQUITY = "monitoring_equity"
    PENDING_FILL = "pending_fill"
    # PENDING_CLOSE: a close market-sell submitted to the broker but not yet
    # confirmed filled. Held until process_pending_closes finalises it.
    PENDING_CLOSE = "pending_close"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    TIMEOUT = "timeout"


class PositionState(Enum):
    """Position states"""
    ACTIVE = "active"
    CLOSING = "closing"
    CLOSED = "closed"
    STOP_LOSS_TRIGGERED = "stop_loss_triggered"
    TAKE_PROFIT_TRIGGERED = "take_profit_triggered"


class StateTransitionError(Exception):
    """Raised when invalid state transition is attempted"""
    pass


class OrderStateMachine:
    """
    Formal state machine for order lifecycle
    Validates transitions and enforces invariants
    """

    # Define valid transitions: current_state -> set of allowed next states
    VALID_TRANSITIONS: Dict[OrderState, Set[OrderState]] = {
        OrderState.PENDING: {
            OrderState.PENDING_FILL,
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELED,
            OrderState.TIMEOUT,
        },
        OrderState.MONITORING_EQUITY: {
            OrderState.PENDING_FILL,
            OrderState.CANCELED,
            OrderState.TIMEOUT,
        },
        OrderState.PENDING_FILL: {
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELED,
            OrderState.TIMEOUT,
        },
        OrderState.PENDING_CLOSE: {
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELED,
            OrderState.TIMEOUT,
        },
        # Terminal states (no transitions allowed)
        OrderState.FILLED: set(),
        OrderState.REJECTED: set(),
        OrderState.CANCELED: set(),
        OrderState.TIMEOUT: set(),
    }

    def __init__(self, order_id: str, initial_state: OrderState, timezone: pytz.timezone):
        """
        Initialize state machine

        Args:
            order_id: Order identifier
            initial_state: Starting state
            timezone: Timezone for timestamps
        """
        self.order_id = order_id
        self.current_state = initial_state
        self.timezone = timezone
        self.transition_history: list = []
        self._record_transition(None, initial_state, "Initial state")

    def transition(self, to_state: OrderState, reason: str = "", **metadata) -> bool:
        """
        Attempt state transition with validation

        Args:
            to_state: Target state
            reason: Reason for transition
            **metadata: Additional metadata to log

        Returns:
            True if transition successful

        Raises:
            StateTransitionError: If transition is invalid
        """
        # Validate transition
        if to_state not in self.VALID_TRANSITIONS[self.current_state]:
            raise StateTransitionError(
                f"Invalid transition for order {self.order_id}: "
                f"{self.current_state.value} -> {to_state.value}"
            )

        # Record transition
        from_state = self.current_state
        self.current_state = to_state
        self._record_transition(from_state, to_state, reason, **metadata)

        logger.info(
            f"Order {self.order_id}: {from_state.value} -> {to_state.value} "
            f"(reason: {reason})"
        )

        return True

    def _record_transition(self, from_state: Optional[OrderState],
                          to_state: OrderState, reason: str, **metadata):
        """Record transition in history"""
        self.transition_history.append({
            'timestamp': datetime.now(self.timezone).isoformat(),
            'from_state': from_state.value if from_state else None,
            'to_state': to_state.value,
            'reason': reason,
            'metadata': metadata
        })

    def can_transition_to(self, to_state: OrderState) -> bool:
        """Check if transition to target state is valid"""
        return to_state in self.VALID_TRANSITIONS[self.current_state]

    def is_terminal(self) -> bool:
        """Check if current state is terminal (no more transitions)"""
        return len(self.VALID_TRANSITIONS[self.current_state]) == 0

    def get_valid_next_states(self) -> Set[OrderState]:
        """Get set of valid next states from current state"""
        return self.VALID_TRANSITIONS[self.current_state].copy()

    def get_transition_history(self) -> list:
        """Get full transition history"""
        return self.transition_history.copy()


class PositionStateMachine:
    """
    Formal state machine for position lifecycle
    Validates transitions and enforces invariants
    """

    VALID_TRANSITIONS: Dict[PositionState, Set[PositionState]] = {
        PositionState.ACTIVE: {
            PositionState.CLOSING,
            PositionState.STOP_LOSS_TRIGGERED,
            PositionState.TAKE_PROFIT_TRIGGERED,
        },
        PositionState.CLOSING: {
            PositionState.CLOSED,
        },
        PositionState.STOP_LOSS_TRIGGERED: {
            PositionState.CLOSING,
            PositionState.CLOSED,
        },
        PositionState.TAKE_PROFIT_TRIGGERED: {
            PositionState.CLOSING,
            PositionState.CLOSED,
        },
        # Terminal state
        PositionState.CLOSED: set(),
    }

    def __init__(self, position_id: str, initial_state: PositionState, timezone: pytz.timezone):
        """Initialize position state machine"""
        self.position_id = position_id
        self.current_state = initial_state
        self.timezone = timezone
        self.transition_history: list = []
        self._record_transition(None, initial_state, "Initial state")

    def transition(self, to_state: PositionState, reason: str = "", **metadata) -> bool:
        """Attempt state transition with validation"""
        if to_state not in self.VALID_TRANSITIONS[self.current_state]:
            raise StateTransitionError(
                f"Invalid transition for position {self.position_id}: "
                f"{self.current_state.value} -> {to_state.value}"
            )

        from_state = self.current_state
        self.current_state = to_state
        self._record_transition(from_state, to_state, reason, **metadata)

        logger.info(
            f"Position {self.position_id}: {from_state.value} -> {to_state.value} "
            f"(reason: {reason})"
        )

        return True

    def _record_transition(self, from_state: Optional[PositionState],
                          to_state: PositionState, reason: str, **metadata):
        """Record transition in history"""
        self.transition_history.append({
            'timestamp': datetime.now(self.timezone).isoformat(),
            'from_state': from_state.value if from_state else None,
            'to_state': to_state.value,
            'reason': reason,
            'metadata': metadata
        })

    def can_transition_to(self, to_state: PositionState) -> bool:
        """Check if transition is valid"""
        return to_state in self.VALID_TRANSITIONS[self.current_state]

    def is_terminal(self) -> bool:
        """Check if current state is terminal"""
        return len(self.VALID_TRANSITIONS[self.current_state]) == 0

    def get_valid_next_states(self) -> Set[PositionState]:
        """Get valid next states"""
        return self.VALID_TRANSITIONS[self.current_state].copy()

    def get_transition_history(self) -> list:
        """Get full transition history"""
        return self.transition_history.copy()


class InvariantValidator:
    """
    Validates system invariants
    Ensures business rules are never violated
    """

    @staticmethod
    def validate_order_invariants(order: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate order invariants

        Returns:
            (is_valid, error_message)
        """
        # Invariant 1: Order must have valid ID
        if not order.get('order_id'):
            return False, "Order missing order_id"

        # Invariant 2: Filled orders must have fill data
        if order.get('status') == 'filled':
            if order.get('filled_qty') is None or order.get('filled_qty') <= 0:
                return False, "Filled order missing filled_qty"
            if order.get('filled_avg_price') is None or order.get('filled_avg_price') <= 0:
                return False, "Filled order missing filled_avg_price"
            if not order.get('fill_time'):
                return False, "Filled order missing fill_time"

        # Invariant 3: Position size must be positive
        if order.get('position_size') is not None:
            if order['position_size'] <= 0:
                return False, "Position size must be positive"

        # Invariant 4: Stop loss must be below entry (for calls)
        # Take profit must be above entry (for calls)
        # (Inverse for puts - would need contract_type check)

        # Invariant 5: equity_limit orders must have equity_limit_price
        if order.get('order_type') == 'equity_limit':
            if order.get('equity_limit_price') is None:
                return False, "equity_limit order missing equity_limit_price"

        return True, None

    @staticmethod
    def validate_position_invariants(position: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate position invariants against the real `positions` schema:
            option_symbol, symbol, contract_type, strike, dte,
            total_contracts, remaining_contracts,
            entry_price, underlying_entry_price,
            stop_loss_price, take_profit_price,
            status, entry_time, exit_time, exit_price, realized_pnl, source_order_id

        Returns (is_valid, error_message).
        """
        # Invariant 1: position is uniquely identified by option_symbol.
        if not position.get('option_symbol'):
            return False, "Position missing option_symbol"

        # Invariant 2: contract counts must be sane and consistent.
        total = position.get('total_contracts')
        remaining = position.get('remaining_contracts')
        if total is None or total <= 0:
            return False, "Position total_contracts must be > 0"
        if remaining is None or remaining < 0:
            return False, "Position remaining_contracts must be >= 0"
        if remaining > total:
            return False, "remaining_contracts cannot exceed total_contracts"

        # Invariant 3: entry price must be positive.
        entry_price = position.get('entry_price')
        if entry_price is None or entry_price <= 0:
            return False, "Position entry_price must be > 0"

        # Invariant 4: open positions must have entry_time.
        status = position.get('status')
        if status in ('open', 'active') and not position.get('entry_time'):
            return False, "Open position missing entry_time"

        # Invariant 5: closed positions must have exit_time, zero remaining,
        # and a non-null exit_price.
        if status == 'closed':
            if not position.get('exit_time'):
                return False, "Closed position missing exit_time"
            if remaining != 0:
                return False, "Closed position must have remaining_contracts == 0"
            if position.get('exit_price') is None:
                return False, "Closed position missing exit_price"

        # Invariant 6: SL/TP price levels, if set, must be positive.
        for level in ('stop_loss_price', 'take_profit_price', 'underlying_entry_price'):
            v = position.get(level)
            if v is not None and v <= 0:
                return False, f"Position {level} must be > 0 if set"

        return True, None

    @staticmethod
    def check_and_log_violation(entity_type: str, entity: Dict[str, Any],
                                validator: Callable) -> bool:
        """
        Check invariants and log violations

        Returns:
            True if valid, False if violation found
        """
        is_valid, error_msg = validator(entity)

        if not is_valid:
            logger.error(
                f"INVARIANT VIOLATION - {entity_type}: {error_msg} "
                f"(entity_id: {entity.get('order_id') or entity.get('position_id')})"
            )
            # In production, this could:
            # - Send alert to monitoring system
            # - Write to violation log file
            # - Trigger circuit breaker

        return is_valid
