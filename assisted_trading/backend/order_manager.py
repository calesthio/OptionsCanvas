"""
Order Manager - Tracks order lifecycle and state transitions
Now with formal state machine validation
"""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
import pytz

from .database.db_manager import DatabaseManager
from .state_machine import (
    OrderStateMachine,
    OrderState,
    StateTransitionError,
    InvariantValidator
)

logger = logging.getLogger(__name__)


class OrderManager:
    """
    Manages orders using SQLite database with formal state machine validation
    Tracks order lifecycle: pending -> filled/rejected/canceled/timeout
    Every state transition is validated through the state machine
    """

    def __init__(self, timezone: pytz.timezone, db_manager: DatabaseManager,
                 enable_state_machine: bool = True,
                 enable_invariant_validation: bool = True):
        """
        Initialize order manager

        Args:
            timezone: Timezone for timestamps
            db_manager: Database manager instance
            enable_state_machine: Enable formal state machine validation (default: True)
            enable_invariant_validation: Enable invariant validation (default: True)
        """
        self.timezone = timezone
        self.db = db_manager
        self.enable_state_machine = enable_state_machine
        self.enable_invariant_validation = enable_invariant_validation

        # Track state machines for active orders
        self._state_machines: Dict[str, OrderStateMachine] = {}

        logger.info(
            f"OrderManager initialized (state_machine={enable_state_machine}, "
            f"invariants={enable_invariant_validation})"
        )

    # ========== Order Creation ==========

    def create_order(self, symbol: str, contract_type: str, dte: int,
                    position_size: float, order_type: str,
                    stop_loss_price: Optional[float] = None,
                    take_profit_price: Optional[float] = None,
                    equity_limit_price: Optional[float] = None,
                    option_order_type: str = 'limit') -> str:
        """
        Create new order record with invariant validation

        Args:
            symbol: Underlying symbol
            contract_type: CALL or PUT
            dte: Days to expiration
            position_size: Position size in dollars
            order_type: equity_market or equity_limit
            stop_loss_price: Stop loss price (optional)
            take_profit_price: Take profit price (optional)
            equity_limit_price: Equity limit price (for equity_limit orders)
            option_order_type: 'market' or 'limit' for the option leg (default 'limit')

        Returns:
            order_id (UUID)
        """
        order_id = str(uuid.uuid4())
        submit_time = datetime.now(self.timezone).isoformat()

        # Determine initial status
        if order_type == 'equity_limit':
            status = 'monitoring_equity'
            initial_state = OrderState.MONITORING_EQUITY
        else:
            status = 'pending'
            initial_state = OrderState.PENDING

        order_data = {
            'order_id': order_id,
            'symbol': symbol,
            'contract_type': contract_type,
            'dte': dte,
            'order_type': order_type,
            'equity_limit_price': equity_limit_price,
            'option_order_type': option_order_type,
            'position_size': position_size,
            'stop_loss_price': stop_loss_price,
            'take_profit_price': take_profit_price,
            'status': status,
            'submit_time': submit_time
        }

        # Validate invariants before creating
        if self.enable_invariant_validation:
            is_valid, error = InvariantValidator.validate_order_invariants(order_data)
            if not is_valid:
                logger.error(f"Order creation failed invariant check: {error}")
                raise ValueError(f"Invalid order data: {error}")

        # Create state machine for this order
        if self.enable_state_machine:
            self._state_machines[order_id] = OrderStateMachine(
                order_id, initial_state, self.timezone
            )

        self.db.create_order(order_data)

        logger.info(
            f"Order created: {order_id} - {contract_type} {symbol} "
            f"(type={order_type}, status={status})"
        )

        return order_id

    def create_close_order(self, option_symbol: str, contracts: int,
                           broker_order_id: str) -> str:
        """
        Record a position-close market sell that has just been submitted to the
        broker. Tracked as `order_type='close_market'`, `status='pending_close'`
        until either the synchronous polling loop or `process_pending_closes`
        confirms the fill. Required so a slow fill can never orphan the order.

        Returns the new internal order_id.
        """
        order_id = str(uuid.uuid4())
        submit_time = datetime.now(self.timezone).isoformat()

        # Pull schema-required metadata from the position being closed.
        position = self.db.get_position(option_symbol)
        if position:
            symbol = position['symbol']
            contract_type = position['contract_type']
            dte = position.get('dte') or 0
            # Notional dollar value of the close — keeps the position_size
            # invariant (> 0) honest without claiming fresh capital allocation.
            position_size = max(
                1.0,
                float(position.get('entry_price') or 0) * contracts * 100,
            )
        else:
            # Position record missing — fall back to neutral metadata so we
            # don't lose the order entirely.
            symbol = option_symbol[:3]
            contract_type = 'CALL'
            dte = 0
            position_size = 1.0

        order_data = {
            'order_id': order_id,
            'symbol': symbol,
            'contract_type': contract_type,
            'dte': dte,
            'order_type': 'close_market',
            'option_order_type': 'market',
            'position_size': position_size,
            'status': 'pending_close',
            'submit_time': submit_time,
        }
        self.db.create_order(order_data)

        # Backfill broker linkage + option_symbol on the new row.
        self.db.update_order(order_id, {
            'broker_order_id': broker_order_id,
            'option_symbol': option_symbol,
            'requested_qty': contracts,
        })

        logger.info(
            f"Close order tracked: {order_id} for {option_symbol} "
            f"({contracts} contracts, broker={broker_order_id})"
        )
        return order_id

    # ========== Order Updates ==========

    def _get_or_create_state_machine(self, order_id: str) -> Optional[OrderStateMachine]:
        """
        Get existing state machine or create one from current order state

        Args:
            order_id: Order ID

        Returns:
            OrderStateMachine instance or None if state machine disabled
        """
        if not self.enable_state_machine:
            return None

        # Return existing if available
        if order_id in self._state_machines:
            return self._state_machines[order_id]

        # Create from current order state
        order = self.get_order(order_id)
        if not order:
            return None

        current_state = OrderState(order['status'])
        sm = OrderStateMachine(order_id, current_state, self.timezone)
        self._state_machines[order_id] = sm
        return sm

    def update_order_status(self, order_id: str, status: str,
                           broker_order_id: Optional[str] = None,
                           option_symbol: Optional[str] = None,
                           strike: Optional[float] = None,
                           requested_qty: Optional[int] = None,
                           reason: str = ""):
        """
        Update order status and metadata with state machine validation

        Args:
            order_id: Order ID
            status: New status
            broker_order_id: Broker's order ID (optional)
            option_symbol: Option symbol (optional)
            strike: Strike price (optional)
            requested_qty: Requested quantity (optional)
            reason: Reason for transition (optional)
        """
        # Validate transition with state machine
        if self.enable_state_machine:
            sm = self._get_or_create_state_machine(order_id)
            if sm:
                try:
                    new_state = OrderState(status)
                    sm.transition(
                        new_state,
                        reason=reason or f"Status update to {status}",
                        broker_order_id=broker_order_id,
                        option_symbol=option_symbol,
                        strike=strike,
                        requested_qty=requested_qty
                    )
                except StateTransitionError as e:
                    logger.error(f"Invalid state transition: {e}")
                    raise

        updates = {'status': status}

        if broker_order_id:
            updates['broker_order_id'] = broker_order_id
        if option_symbol:
            updates['option_symbol'] = option_symbol
        if strike:
            updates['strike'] = strike
        if requested_qty:
            updates['requested_qty'] = requested_qty

        self.db.update_order(order_id, updates)

        logger.info(f"Order {order_id} updated: status={status}")

    def mark_order_filled(self, order_id: str, filled_qty: int,
                         filled_avg_price: float):
        """
        Mark order as filled with state machine validation

        Args:
            order_id: Order ID
            filled_qty: Filled quantity
            filled_avg_price: Average fill price
        """
        # Validate transition
        if self.enable_state_machine:
            sm = self._get_or_create_state_machine(order_id)
            if sm:
                try:
                    sm.transition(
                        OrderState.FILLED,
                        reason="Order filled by broker",
                        filled_qty=filled_qty,
                        filled_avg_price=filled_avg_price
                    )
                except StateTransitionError as e:
                    logger.error(f"Cannot mark order as filled: {e}")
                    raise

        fill_time = datetime.now(self.timezone).isoformat()

        updates = {
            'status': 'filled',
            'filled_qty': filled_qty,
            'filled_avg_price': filled_avg_price,
            'fill_time': fill_time
        }

        # Validate invariants
        if self.enable_invariant_validation:
            order = self.get_order(order_id)
            if order:
                test_order = {**order, **updates}
                is_valid, error = InvariantValidator.validate_order_invariants(test_order)
                if not is_valid:
                    logger.error(f"Filled order violates invariant: {error}")
                    raise ValueError(f"Invalid filled order: {error}")

        self.db.update_order(order_id, updates)

        logger.info(
            f"Order filled: {order_id} - {filled_qty} contracts @ ${filled_avg_price:.2f}"
        )

    def mark_order_rejected(self, order_id: str, reason: Optional[str] = None):
        """Mark order as rejected with state machine validation"""
        if self.enable_state_machine:
            sm = self._get_or_create_state_machine(order_id)
            if sm:
                try:
                    sm.transition(OrderState.REJECTED, reason=reason or "Order rejected")
                except StateTransitionError as e:
                    logger.error(f"Cannot mark order as rejected: {e}")
                    raise

        updates = {'status': 'rejected'}
        self.db.update_order(order_id, updates)
        logger.warning(f"Order rejected: {order_id} - {reason}")

    def mark_order_canceled(self, order_id: str):
        """Mark order as canceled with state machine validation"""
        if self.enable_state_machine:
            sm = self._get_or_create_state_machine(order_id)
            if sm:
                try:
                    sm.transition(OrderState.CANCELED, reason="Order canceled by user")
                except StateTransitionError as e:
                    logger.error(f"Cannot mark order as canceled: {e}")
                    raise

        cancel_time = datetime.now(self.timezone).isoformat()
        updates = {
            'status': 'canceled',
            'cancel_time': cancel_time
        }
        self.db.update_order(order_id, updates)
        logger.info(f"Order canceled: {order_id}")

    def mark_order_timeout(self, order_id: str):
        """Mark order as timeout with state machine validation"""
        if self.enable_state_machine:
            sm = self._get_or_create_state_machine(order_id)
            if sm:
                try:
                    sm.transition(OrderState.TIMEOUT, reason="Order timed out")
                except StateTransitionError as e:
                    logger.error(f"Cannot mark order as timeout: {e}")
                    raise

        updates = {'status': 'timeout'}
        self.db.update_order(order_id, updates)
        logger.warning(f"Order timeout: {order_id}")

    # ========== Order Queries ==========

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get order by ID"""
        return self.db.get_order(order_id)

    def get_pending_orders(self) -> List[Dict[str, Any]]:
        """Get all pending orders (pending, monitoring_equity, pending_fill)"""
        return self.db.get_pending_orders()

    def get_orders_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get orders by status"""
        query = "SELECT * FROM orders WHERE status = ? ORDER BY submit_time DESC"
        return self.db.execute_query(query, (status,))

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel pending order

        Args:
            order_id: Order ID

        Returns:
            True if canceled successfully
        """
        order = self.get_order(order_id)
        if not order:
            logger.error(f"Order not found: {order_id}")
            return False

        if order['status'] not in ['pending', 'monitoring_equity', 'pending_fill']:
            logger.error(f"Cannot cancel order {order_id} with status {order['status']}")
            return False

        self.mark_order_canceled(order_id)
        return True

    # ========== Order State Transitions ==========

    def transition_to_pending_fill(self, order_id: str, broker_order_id: str,
                                   option_symbol: str, strike: float,
                                   requested_qty: int):
        """
        Transition order from monitoring_equity to pending_fill with state machine validation

        Args:
            order_id: Order ID
            broker_order_id: Broker's order ID
            option_symbol: Option symbol
            strike: Strike price
            requested_qty: Requested quantity
        """
        self.update_order_status(
            order_id=order_id,
            status='pending_fill',
            broker_order_id=broker_order_id,
            option_symbol=option_symbol,
            strike=strike,
            requested_qty=requested_qty,
            reason="Equity limit reached, submitting order to broker"
        )

        logger.info(
            f"Order {order_id} transitioned to pending_fill: "
            f"{option_symbol}, {requested_qty} contracts"
        )

    def transition_to_filled(self, order_id: str, filled_qty: int,
                           filled_avg_price: float):
        """
        Transition order to filled state with state machine validation

        Args:
            order_id: Order ID
            filled_qty: Filled quantity
            filled_avg_price: Average fill price
        """
        self.mark_order_filled(order_id, filled_qty, filled_avg_price)

        logger.info(
            f"Order {order_id} filled: {filled_qty} contracts @ ${filled_avg_price:.2f}"
        )

    def get_transition_history(self, order_id: str) -> Optional[List[Dict[str, Any]]]:
        """
        Get state transition history for an order

        Args:
            order_id: Order ID

        Returns:
            List of transitions or None if state machine not enabled
        """
        if not self.enable_state_machine:
            return None

        sm = self._state_machines.get(order_id)
        if sm:
            return sm.get_transition_history()
        return None

    # ========== Cleanup ==========

    def cleanup_old_orders(self, days: int = 7):
        """
        Clean up old completed orders

        Args:
            days: Delete orders older than this many days
        """
        self.db.cleanup_old_data(days)
        logger.info(f"Cleaned up orders older than {days} days")
