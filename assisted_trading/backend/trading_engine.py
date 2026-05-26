"""
Trading Engine for Assisted Trading
Handles option buying, position management, and stop loss monitoring
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Tuple
import pytz
import math

logger = logging.getLogger(__name__)


class TradingEngine:
    """Core trading engine for assisted trading"""

    def __init__(self, broker, config, position_manager, order_manager, market_hours, timezone):
        """
        Initialize trading engine

        Args:
            broker: Broker module instance
            config: Assisted trading configuration
            position_manager: Position manager instance (V2 - database-backed)
            order_manager: Order manager instance (database-backed)
            market_hours: Market hours validator
            timezone: Timezone object
        """
        self.broker = broker
        self.config = config
        self.position_manager = position_manager
        self.order_manager = order_manager
        self.market_hours = market_hours
        self.timezone = timezone

        self.order_timeout = config['order_settings']['entry_timeout_seconds']
        self.accept_partial_fills = config['order_settings']['accept_partial_fills']

        # ----------------------------------------------------------------
        # Broker-positions cache.
        # Reasons:
        #   1. /api/position is polled every few seconds by the frontend; each
        #      call without cache fans out a fresh broker API request.
        #   2. Transient errors (DNS blip, broker rate-limit, brief outage)
        #      MUST NOT cause the engine to falsely conclude positions
        #      disappeared and delete its local tracking — which would also
        #      drop any server-side stops attached to those positions.
        # ----------------------------------------------------------------
        self._positions_cache = {'data': [], 'fetched_at': 0.0, 'fresh': False}
        self._positions_cache_ttl = 5.0          # short enough to feel live
        self._positions_failure_streak = 0       # consecutive broker call failures

        logger.info("Trading engine initialized with database-backed managers")

    def _fetch_broker_positions(self):
        """Get broker positions through a short TTL cache with graceful fallback.

        Returns:
            (positions: list, just_fetched: bool)
            just_fetched=True  → we just hit the broker and got an authoritative
                                 response in this call.
            just_fetched=False → we're serving cached or stale data. The cache
                                 may be up to TTL seconds old, OR the last
                                 broker call failed. Either way, callers MUST
                                 NOT do destructive reconciliation against this
                                 data — a position might exist on the broker
                                 but not in this cached snapshot.

        NB: the previous version of this method returned `fresh=True` on cache
        hits, which caused get_position_details() to delete tracked positions
        whenever the cache happened to be older than the position's creation.
        That manifested as "position opened via platform shows as External
        broker position" — the position got written to our DB, then the very
        next /api/position poll deleted it because the stale cache didn't see
        it on the broker yet. Renaming the flag is the fix.
        """
        now = time.time()
        cache = self._positions_cache

        if cache['fresh'] and (now - cache['fetched_at']) < self._positions_cache_ttl:
            return cache['data'], False  # cache hit — NOT just-fetched

        try:
            positions = self.broker.get_all_positions()
            cache['data'] = positions
            cache['fetched_at'] = now
            cache['fresh'] = True
            if self._positions_failure_streak > 0:
                logger.info(
                    "Broker positions: recovered after %d failed attempts",
                    self._positions_failure_streak,
                )
                self._positions_failure_streak = 0
            return positions, True
        except Exception as e:
            self._positions_failure_streak += 1
            if self._positions_failure_streak == 1:
                logger.warning(
                    "Failed to get broker positions (serving cached/stale data): %s", e
                )
            elif self._positions_failure_streak % 30 == 0:
                logger.warning(
                    "Broker positions still failing after %d attempts",
                    self._positions_failure_streak,
                )
            return cache['data'], False

    def get_option_for_strike(self, symbol: str, contract_type: str, dte: int, strike: float):
        """
        Get option details for a specific strike price

        Args:
            symbol: Underlying symbol
            contract_type: CALL or PUT
            dte: Days to expiration
            strike: Strike price

        Returns:
            tuple: (option_symbol, quote) or (None, None) if not found
        """
        try:
            logger.info(f"Looking up option: {symbol} {contract_type} strike ${strike:.2f}, {dte} DTE")

            # Get option contracts for this strike and DTE
            contracts = self.broker.get_option_contracts(
                underlying_symbol=symbol,
                dte=dte,
                strike_price=strike,
                option_type=contract_type.lower()
            )

            if not contracts:
                logger.error(f"No {contract_type} contracts found for {symbol} "
                           f"strike ${strike:.2f}, {dte} DTE")
                return None, None

            option_symbol = contracts[0]['symbol']
            logger.info(f"Option symbol: {option_symbol}")

            # Get option quote
            quote = self.broker.get_option_quote(option_symbol)

            return option_symbol, quote

        except Exception as e:
            logger.error(f"Error getting option for strike: {e}", exc_info=True)
            return None, None

    def get_atm_strike_and_option(self, symbol: str, contract_type: str, dte: int):
        """
        Get ATM strike and option contract details

        Args:
            symbol: Underlying symbol (SPY/QQQ)
            contract_type: CALL or PUT
            dte: Days to expiration

        Returns:
            tuple: (strike_price, option_symbol, quote_data) or (None, None, None) if not found
        """
        try:
            # Get current underlying price
            current_price = self.broker.get_current_price(symbol)
            logger.info(f"Current {symbol} price: ${current_price:.2f}")

            # Get ATM strike
            atm_strike = self.broker.get_atm_strike(symbol, current_price)
            logger.info(f"ATM strike: ${atm_strike:.2f}")

            # Get option contracts for this strike and DTE
            contracts = self.broker.get_option_contracts(
                underlying_symbol=symbol,
                dte=dte,
                strike_price=atm_strike,
                option_type=contract_type.lower()
            )

            if not contracts:
                logger.error(f"No {contract_type} contracts found for {symbol} "
                           f"strike ${atm_strike}, {dte} DTE")
                return None, None, None

            option_symbol = contracts[0]['symbol']
            logger.info(f"Option symbol: {option_symbol}")

            # Get option quote
            quote = self.broker.get_option_quote(option_symbol)

            return atm_strike, option_symbol, quote

        except Exception as e:
            logger.error(f"Error getting ATM strike/option: {e}", exc_info=True)
            return None, None, None

    def calculate_contracts_from_position_size(self, position_size: float,
                                              option_premium: float) -> int:
        """
        Calculate number of contracts based on position size and option premium

        Args:
            position_size: Position size in dollars
            option_premium: Option premium per share

        Returns:
            int: Number of contracts (minimum 1)
        """
        contract_value = option_premium * 100
        if contract_value <= 0:
            return 0

        contracts = int(position_size / contract_value)
        return max(1, contracts)

    def place_option_order(self, option_symbol: str, contracts: int,
                          bid: float, ask: float, order_type: str = 'limit') -> Dict[str, Any]:
        """
        Place option order - either market or limit at midpoint

        Args:
            option_symbol: Option symbol
            contracts: Number of contracts
            bid: Bid price
            ask: Ask price
            order_type: 'market' or 'limit' (default)

        Returns:
            dict: Order details
        """
        if order_type == 'market':
            # Market order - fills immediately at best available price
            logger.info(f"Placing MARKET order: {contracts} contracts of {option_symbol} "
                       f"(bid: ${bid:.2f}, ask: ${ask:.2f})")

            order = self.broker.place_market_order(
                symbol=option_symbol,
                qty=contracts,
                side='buy'
            )
        else:  # 'limit' (default)
            # Limit order at midpoint price
            midpoint = (bid + ask) / 2
            limit_price = math.floor(midpoint * 100) / 100

            logger.info(f"Placing LIMIT order at midpoint: {contracts} contracts of {option_symbol} "
                       f"@ ${limit_price:.2f} (bid: ${bid:.2f}, ask: ${ask:.2f})")

            order = self.broker.place_limit_order(
                symbol=option_symbol,
                qty=contracts,
                side='buy',
                limit_price=limit_price
            )

        return order

    def monitor_order_fill(self, order_id: str, timeout_seconds: int) -> Tuple[str, int, Optional[float]]:
        """
        Monitor order until filled, partially filled, or timeout

        Args:
            order_id: Order ID to monitor
            timeout_seconds: Timeout in seconds

        Returns:
            tuple: (status, filled_qty, filled_avg_price)
                   status: 'filled', 'partial', 'timeout', 'rejected', 'canceled'
        """
        start_time = time.time()

        while time.time() - start_time < timeout_seconds:
            try:
                order_status = self.broker.get_order_status(order_id)

                status = order_status['status']
                filled_qty = order_status.get('filled_qty', 0)
                filled_price = order_status.get('filled_avg_price')

                logger.debug(f"Order {order_id}: status={status}, filled={filled_qty}")

                if status == 'filled':
                    logger.info(f"Order filled: {filled_qty} contracts @ ${filled_price:.2f}")
                    return 'filled', filled_qty, filled_price

                elif status in ['rejected', 'canceled', 'expired']:
                    logger.warning(f"Order {status}: {order_id}")
                    return status, filled_qty, filled_price

                elif filled_qty > 0:
                    # Partial fill
                    logger.info(f"Partial fill: {filled_qty} contracts @ ${filled_price:.2f}")

            except Exception as e:
                logger.error(f"Error checking order status: {e}")

            time.sleep(2)  # Check every 2 seconds

        # Timeout reached
        logger.warning(f"Order timeout reached after {timeout_seconds}s")

        # Get final status
        try:
            final_status = self.broker.get_order_status(order_id)
            filled_qty = final_status.get('filled_qty', 0)
            filled_price = final_status.get('filled_avg_price')

            if filled_qty > 0:
                return 'partial', filled_qty, filled_price
            else:
                return 'timeout', 0, None

        except Exception as e:
            logger.error(f"Error getting final order status: {e}")
            return 'timeout', 0, None

    def open_position(self, symbol: str, contract_type: str, dte: int,
                     position_size: float, strike: Optional[float] = None,
                     stop_loss_price: Optional[float] = None,
                     take_profit_price: Optional[float] = None,
                     order_type: str = 'equity_market',
                     equity_limit_price: Optional[float] = None,
                     option_order_type: str = 'limit') -> Dict[str, Any]:
        """
        Queue a new option position order (equity_limit) or place immediately (equity_market)

        Args:
            symbol: Underlying symbol (SPY/QQQ)
            contract_type: CALL or PUT
            dte: Days to expiration
            position_size: Position size in dollars
            stop_loss_price: Optional stop loss price for underlying equity
            take_profit_price: Optional take profit price for underlying equity
            order_type: 'equity_market' or 'equity_limit'
            equity_limit_price: Limit price for equity (required if order_type is 'equity_limit')
            option_order_type: 'market' or 'limit' (default) for option order execution

        Returns:
            dict: Result with status and details
        """
        try:
            # Validate market hours
            allowed, reason = self.market_hours.validate_trading_allowed()
            if not allowed:
                return {
                    'success': False,
                    'error': f"Trading not allowed: {reason}"
                }

            # Check if can open new position
            can_open, reason = self.position_manager.can_open_new_position(symbol)
            if not can_open:
                return {
                    'success': False,
                    'error': reason
                }

            current_time = datetime.now(self.timezone).strftime('%Y-%m-%d %H:%M:%S')

            # For equity_limit orders, queue them for monitoring
            if order_type == 'equity_limit':
                if equity_limit_price is None:
                    return {
                        'success': False,
                        'error': 'Equity limit price is required for equity_limit orders'
                    }

                # Create order in database. Persist option_order_type so that
                # when the equity trigger fires later, process_pending_orders
                # honours the user's original "market" vs "limit" choice.
                order_id = self.order_manager.create_order(
                    symbol=symbol,
                    contract_type=contract_type,
                    dte=dte,
                    position_size=position_size,
                    order_type=order_type,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    equity_limit_price=equity_limit_price,
                    option_order_type=option_order_type
                )

                logger.info(f"Equity limit order created: {order_id} - {contract_type} {symbol} @ ${equity_limit_price:.2f}")

                return {
                    'success': True,
                    'status': 'monitoring_equity',
                    'message': f'Order queued. Monitoring for {symbol} to reach ${equity_limit_price:.2f}',
                    'order_id': order_id
                }

            # For equity_market orders, place immediately and queue for fill monitoring
            # Get current underlying price
            current_underlying_price = self.broker.get_current_price(symbol)

            # Get ATM strike and option details
            # Use provided strike from frontend if available, otherwise calculate
            if strike is None:
                strike, option_symbol, quote = self.get_atm_strike_and_option(
                    symbol, contract_type, dte
                )
            else:
                # Use the strike provided from frontend
                logger.info(f"Using provided strike: ${strike:.2f}")
                option_symbol, quote = self.get_option_for_strike(
                    symbol, contract_type, dte, strike
                )

            if not option_symbol:
                return {
                    'success': False,
                    'error': 'Could not find suitable option contract'
                }

            # Calculate contracts
            option_premium = quote['mid']
            contracts = self.calculate_contracts_from_position_size(
                position_size, option_premium
            )

            if contracts == 0:
                return {
                    'success': False,
                    'error': 'Calculated contracts is 0'
                }

            # Check buying power
            estimated_cost = contracts * option_premium * 100
            account_info = self.broker.get_account_info()
            if estimated_cost > account_info['buying_power']:
                return {
                    'success': False,
                    'error': f"Insufficient buying power: ${account_info['buying_power']:,.2f} < ${estimated_cost:,.2f}"
                }

            logger.info(f"Placing market order: {contracts} x {option_symbol} @ ~${option_premium:.2f}")

            # Create order in database first
            order_id = self.order_manager.create_order(
                symbol=symbol,
                contract_type=contract_type,
                dte=dte,
                position_size=position_size,
                order_type='equity_market',
                stop_loss_price=stop_loss_price,
                take_profit_price=take_profit_price
            )

            # Place order with broker using specified order type (market or limit)
            broker_order = self.place_option_order(
                option_symbol, contracts, quote['bid'], quote['ask'], option_order_type
            )

            # Update order with broker details
            self.order_manager.update_order_status(
                order_id=order_id,
                status='pending_fill',
                broker_order_id=broker_order['order_id'],
                option_symbol=option_symbol,
                strike=strike,
                requested_qty=contracts
            )

            logger.info(f"Order submitted: {broker_order['order_id']}. Monitoring for fill...")

            return {
                'success': True,
                'status': 'pending_fill',
                'message': f'Order placed. Monitoring for fill...',
                'order_id': order_id,
                'broker_order_id': broker_order['order_id']
            }

        except Exception as e:
            logger.error(f"Error opening position: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def close_position(self, option_symbol: str, contracts: int) -> Dict[str, Any]:
        """
        Close position (full or partial)

        Args:
            option_symbol: Option symbol to close
            contracts: Number of contracts to close

        Returns:
            dict: Result with status and details
        """
        try:
            if not self.position_manager.has_position(option_symbol):
                return {
                    'success': False,
                    'error': f'No open position for {option_symbol}'
                }

            position = self.position_manager.get_position(option_symbol)

            if contracts > position['remaining_contracts']:
                return {
                    'success': False,
                    'error': f'Cannot close {contracts} contracts, only {position["remaining_contracts"]} remaining'
                }

            # Place market sell order
            logger.info(f"Closing {contracts} contracts of {option_symbol}")

            order = self.broker.place_market_order(
                symbol=option_symbol,
                qty=contracts,
                side='sell'
            )
            broker_order_id = order['order_id']

            # Persist the close in our DB so it can be reconciled later if the
            # broker doesn't fill within the synchronous window. This is the
            # fix for the "sleep(3) + orphan" reliability hole.
            close_order_id = self.order_manager.create_close_order(
                option_symbol=option_symbol,
                contracts=contracts,
                broker_order_id=broker_order_id,
            )

            # Bounded poll: ~3s wall clock, 6×500ms, early exit on fill.
            order_status = None
            poll_iters = 6
            for attempt in range(poll_iters):
                time.sleep(0.5)
                try:
                    order_status = self.broker.get_order_status(broker_order_id)
                except Exception as poll_err:
                    logger.warning(
                        f"Poll {attempt + 1}/{poll_iters} for close order {broker_order_id} raised: {poll_err}"
                    )
                    continue
                if order_status and order_status.get('status') == 'filled':
                    break

            if order_status and order_status.get('status') == 'filled':
                exit_price = order_status['filled_avg_price']

                # Close position in database
                close_record = self.position_manager.close_position(
                    option_symbol, contracts, exit_price
                )

                # Finalise the close order row.
                self.order_manager.mark_order_filled(
                    close_order_id, contracts, exit_price
                )

                return {
                    'success': True,
                    'status': 'closed',
                    'close_record': close_record,
                    'option_symbol': option_symbol,
                    'order_id': close_order_id,
                }

            # Not filled within the window. Leave the close order as
            # pending_close so process_pending_orders picks it up later.
            current_status = (order_status or {}).get('status', 'unknown')
            logger.info(
                f"Close for {option_symbol} not filled within {poll_iters * 0.5}s "
                f"(broker status: {current_status}); deferred as pending_close."
            )
            return {
                'success': True,
                'status': 'pending_close',
                'message': (
                    f"Close working at broker (status: {current_status}). "
                    "Will reconcile in the background."
                ),
                'option_symbol': option_symbol,
                'order_id': close_order_id,
                'broker_order_id': broker_order_id,
            }

        except Exception as e:
            logger.error(f"Error closing position: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def update_stop_loss(self, option_symbol: str, new_stop_loss_price: float) -> Dict[str, Any]:
        """
        Update stop loss price

        Args:
            option_symbol: Option symbol
            new_stop_loss_price: New stop loss price

        Returns:
            dict: Result with status and details
        """
        try:
            if not self.position_manager.has_position(option_symbol):
                return {
                    'success': False,
                    'error': f'No open position for {option_symbol}'
                }

            self.position_manager.update_stop_loss(option_symbol, new_stop_loss_price)

            return {
                'success': True,
                'option_symbol': option_symbol,
                'new_stop_loss': new_stop_loss_price
            }

        except Exception as e:
            logger.error(f"Error updating stop loss: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def update_take_profit(self, option_symbol: str, new_take_profit_price: float) -> Dict[str, Any]:
        """
        Update take profit price

        Args:
            option_symbol: Option symbol
            new_take_profit_price: New take profit price

        Returns:
            dict: Result with status and details
        """
        try:
            if not self.position_manager.has_position(option_symbol):
                return {
                    'success': False,
                    'error': f'No open position for {option_symbol}'
                }

            self.position_manager.update_take_profit(option_symbol, new_take_profit_price)

            return {
                'success': True,
                'option_symbol': option_symbol,
                'new_take_profit': new_take_profit_price
            }

        except Exception as e:
            logger.error(f"Error updating take profit: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e)
            }

    def process_pending_orders(self) -> Dict[str, Any]:
        """
        Process all pending orders - check equity limits and order fill status
        Called every time the UI polls for position updates

        Returns:
            dict: Summary of processing results
        """
        results = {
            'orders_checked': 0,
            'equity_limits_triggered': 0,
            'fills_completed': 0,
            'errors': []
        }

        # Get all pending orders from database
        pending_orders = self.order_manager.get_pending_orders()

        for order in pending_orders:
            results['orders_checked'] += 1

            try:
                # Handle equity_limit orders
                if order['order_type'] == 'equity_limit' and order['status'] == 'monitoring_equity':
                    current_price = self.broker.get_current_price(order['symbol'])

                    # Check if limit condition is met
                    limit_met = False
                    if order['contract_type'] == 'CALL' and current_price <= order['equity_limit_price']:
                        limit_met = True
                    elif order['contract_type'] == 'PUT' and current_price >= order['equity_limit_price']:
                        limit_met = True

                    if limit_met:
                        logger.info(f"Equity limit met for order {order['order_id']}: "
                                  f"{order['symbol']} @ ${current_price:.2f}")

                        # Place the option order now
                        strike, option_symbol, quote = self.get_atm_strike_and_option(
                            order['symbol'], order['contract_type'], order['dte']
                        )

                        if option_symbol:
                            option_premium = quote['mid']
                            contracts = self.calculate_contracts_from_position_size(
                                order['position_size'], option_premium
                            )

                            if contracts > 0:
                                # Place option order with broker using order type from order (market or limit)
                                option_order_type = order.get('option_order_type', 'limit')
                                broker_order = self.place_option_order(
                                    option_symbol, contracts, quote['bid'], quote['ask'], option_order_type
                                )

                                # Transition order to pending_fill
                                self.order_manager.transition_to_pending_fill(
                                    order_id=order['order_id'],
                                    broker_order_id=broker_order['order_id'],
                                    option_symbol=option_symbol,
                                    strike=strike,
                                    requested_qty=contracts
                                )

                                results['equity_limits_triggered'] += 1
                                logger.info(f"Option order placed: {broker_order['order_id']}")

                # Handle orders waiting for fill
                if order['status'] == 'pending_fill' and order.get('broker_order_id'):
                    order_status = self.broker.get_order_status(order['broker_order_id'])
                    status = order_status['status']
                    filled_qty = order_status.get('filled_qty', 0)
                    filled_price = order_status.get('filled_avg_price')

                    if status == 'filled' and filled_qty > 0:
                        # Get current underlying price
                        current_underlying_price = self.broker.get_current_price(order['symbol'])

                        # Check if position already exists - if so, add to it instead of creating new
                        if self.position_manager.has_position(order['option_symbol']):
                            logger.info(f"Position already exists for {order['option_symbol']}, adding {filled_qty} contracts")

                            # Add to existing position (calculates weighted average)
                            self.position_manager.add_to_position(
                                option_symbol=order['option_symbol'],
                                additional_contracts=filled_qty,
                                new_entry_price=filled_price,
                                new_underlying_price=current_underlying_price
                            )

                            # Mark order as filled
                            self.order_manager.mark_order_filled(order['order_id'], filled_qty, filled_price)

                            results['fills_completed'] += 1
                            logger.info(f"Added to position: {filled_qty} contracts @ ${filled_price:.2f}")
                        else:
                            # Order filled - create NEW position in database
                            self.position_manager.open_position(
                                option_symbol=order['option_symbol'],
                                symbol=order['symbol'],
                                contract_type=order['contract_type'],
                                strike=order['strike'],
                                dte=order['dte'],
                                total_contracts=filled_qty,
                                entry_price=filled_price,
                                underlying_entry_price=current_underlying_price,
                                stop_loss_price=order.get('stop_loss_price'),
                                take_profit_price=order.get('take_profit_price'),
                                source_order_id=order['order_id']
                            )

                            # Mark order as filled
                            self.order_manager.mark_order_filled(order['order_id'], filled_qty, filled_price)

                            results['fills_completed'] += 1
                            logger.info(f"Position opened: {filled_qty} contracts @ ${filled_price:.2f}")

                    elif status in ['rejected', 'canceled', 'expired']:
                        # Order was rejected/canceled - use appropriate transition
                        if status == 'canceled':
                            self.order_manager.mark_order_canceled(order['order_id'])
                        else:
                            self.order_manager.mark_order_rejected(order['order_id'], status)
                        logger.warning(f"Order {order['order_id']} {status}")

            except Exception as e:
                logger.error(f"Error processing pending order {order['order_id']}: {e}", exc_info=True)
                results['errors'].append(f"Order {order['order_id']}: {str(e)}")

        # Reconcile deferred close orders that the synchronous close_position
        # loop couldn't finalise inside its 3s window.
        close_results = self.process_pending_closes()
        results['closes_completed'] = close_results.get('closes_completed', 0)
        results['closes_pending'] = close_results.get('still_pending', 0)
        if close_results.get('errors'):
            results['errors'].extend(close_results['errors'])

        return results

    def process_pending_closes(self) -> Dict[str, Any]:
        """
        Pick up any close orders that were left in `pending_close` (the
        broker hadn't filled within the synchronous polling window) and
        finalise them when the broker confirms the fill.
        """
        results = {'closes_completed': 0, 'still_pending': 0, 'errors': []}

        try:
            # OrderManager owns the DB handle; TradingEngine doesn't hold one
            # directly in production.
            pending_closes = self.order_manager.db.get_pending_close_orders()
        except Exception as e:
            logger.error(f"Failed to fetch pending close orders: {e}", exc_info=True)
            return results

        for close_row in pending_closes:
            order_id = close_row['order_id']
            broker_order_id = close_row.get('broker_order_id')
            option_symbol = close_row.get('option_symbol')
            contracts = close_row.get('requested_qty') or 0

            if not broker_order_id or not option_symbol:
                # Malformed row — surface as error, leave alone for human triage.
                results['errors'].append(
                    f"Close order {order_id} missing broker_order_id or option_symbol"
                )
                continue

            try:
                status = self.broker.get_order_status(broker_order_id)
            except Exception as e:
                logger.warning(f"Broker status poll failed for close {broker_order_id}: {e}")
                results['errors'].append(f"Close {order_id}: status poll failed: {e}")
                results['still_pending'] += 1
                continue

            broker_status = status.get('status') if status else None
            if broker_status == 'filled':
                exit_price = status['filled_avg_price']
                try:
                    self.position_manager.close_position(option_symbol, contracts, exit_price)
                except ValueError as e:
                    # Position already gone (e.g. resolved elsewhere). Still
                    # mark the order as filled so it stops being reconciled.
                    logger.warning(f"close_position raised for {option_symbol}: {e}")

                self.order_manager.mark_order_filled(order_id, contracts, exit_price)
                results['closes_completed'] += 1
                logger.info(f"Pending close finalised: {option_symbol} @ ${exit_price:.2f}")
            elif broker_status in ('canceled', 'rejected', 'expired'):
                # Broker terminated the close — record it accordingly.
                if broker_status == 'canceled':
                    self.order_manager.mark_order_canceled(order_id)
                else:
                    self.order_manager.mark_order_rejected(order_id, broker_status)
                logger.warning(f"Pending close {order_id} terminated by broker: {broker_status}")
            else:
                # Still working at the broker — leave for the next sweep.
                results['still_pending'] += 1

        return results

    def cancel_pending_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel a pending order

        Args:
            order_id: Order ID to cancel

        Returns:
            dict: Result with status and user-friendly message
        """
        from .state_machine import StateTransitionError

        try:
            order = self.order_manager.get_order(order_id)

            if not order:
                return {
                    'success': False,
                    'message': 'Order not found in system'
                }

            # Check current state - provide friendly error if can't cancel
            current_status = order.get('status')

            if current_status == 'filled':
                return {
                    'success': False,
                    'message': 'This order has already been filled! Check your open positions.',
                    'hint': 'You can close the position instead of canceling the order.'
                }

            if current_status == 'canceled':
                return {
                    'success': False,
                    'message': 'This order was already canceled.'
                }

            if current_status == 'rejected':
                return {
                    'success': False,
                    'message': 'This order was rejected by the broker and cannot be canceled.'
                }

            if current_status == 'timeout':
                return {
                    'success': False,
                    'message': 'This order has timed out and cannot be canceled.'
                }

            # If there's a broker order, cancel it
            if order.get('broker_order_id'):
                try:
                    self.broker.cancel_order(order['broker_order_id'])
                    logger.info(f"Canceled broker order: {order['broker_order_id']}")
                except Exception as e:
                    logger.warning(f"Could not cancel broker order {order['broker_order_id']}: {e}")

            # Mark order as canceled in database
            self.order_manager.mark_order_canceled(order_id)

            logger.info(f"Pending order canceled: {order_id}")

            return {
                'success': True,
                'message': 'Order canceled successfully'
            }

        except StateTransitionError as e:
            # Convert technical error to user-friendly message
            logger.warning(f"State transition error canceling order: {e}")
            return {
                'success': False,
                'message': 'Cannot cancel this order - it may have just been filled or changed status.',
                'hint': 'Please refresh and check if the order is now in your positions.'
            }

        except Exception as e:
            logger.error(f"Error canceling order: {e}", exc_info=True)
            return {
                'success': False,
                'message': 'Something went wrong while canceling your order. Please try again.'
            }

    def check_stop_loss(self) -> list:
        """
        Check if stop loss is hit for all positions and auto-sell if configured

        Returns:
            list: List of close results for positions where stop loss was hit
        """
        if not self.position_manager.has_any_position():
            return []

        results = []

        # Get all positions from database
        positions = self.position_manager.get_all_positions()

        for position in positions:
            option_symbol = position['option_symbol']
            try:
                # Skip stop loss check if no stop loss is set
                if position['stop_loss_price'] is None:
                    continue

                # Get current underlying price
                current_price = self.broker.get_current_price(position['symbol'])

                # Check if stop loss hit (logic depends on contract type)
                stop_loss_hit = False

                if position['contract_type'] == 'CALL':
                    # For CALL options, stop loss triggers when price drops below stop loss
                    if current_price <= position['stop_loss_price']:
                        stop_loss_hit = True
                        logger.warning(f"Stop loss hit (CALL): {position['symbol']} @ ${current_price:.2f} "
                                     f"<= ${position['stop_loss_price']:.2f}")
                elif position['contract_type'] == 'PUT':
                    # For PUT options, stop loss triggers when price rises above stop loss
                    if current_price >= position['stop_loss_price']:
                        stop_loss_hit = True
                        logger.warning(f"Stop loss hit (PUT): {position['symbol']} @ ${current_price:.2f} "
                                     f">= ${position['stop_loss_price']:.2f}")

                if stop_loss_hit:
                    if self.config['order_settings']['auto_sell_on_stop_loss']:
                        # Verify position still exists in broker before closing
                        broker_pos = self.broker.get_position(option_symbol)
                        if broker_pos:
                            logger.info(f"Auto-selling position {option_symbol} due to stop loss")
                            result = self.close_position(option_symbol, position['remaining_contracts'])
                            result['reason'] = 'stop_loss'
                            results.append(result)
                        else:
                            logger.warning(f"Skipping SL close for {option_symbol} - not found in broker")
                            self.position_manager.delete_position(option_symbol)

            except Exception as e:
                logger.error(f"Error checking stop loss for {option_symbol}: {e}", exc_info=True)

        return results

    def check_take_profit(self) -> list:
        """
        Check if take profit is hit for all positions and auto-sell if configured

        Returns:
            list: List of close results for positions where take profit was hit
        """
        if not self.position_manager.has_any_position():
            return []

        results = []

        # Get all positions from database
        positions = self.position_manager.get_all_positions()

        for position in positions:
            option_symbol = position['option_symbol']
            try:
                # Skip take profit check if no take profit is set
                if position['take_profit_price'] is None:
                    continue

                # Get current underlying price
                current_price = self.broker.get_current_price(position['symbol'])

                # Check if take profit hit (logic depends on contract type)
                take_profit_hit = False

                if position['contract_type'] == 'CALL':
                    # For CALL options, take profit triggers when price rises above take profit
                    if current_price >= position['take_profit_price']:
                        take_profit_hit = True
                        logger.warning(f"Take profit hit (CALL): {position['symbol']} @ ${current_price:.2f} "
                                     f">= ${position['take_profit_price']:.2f}")
                elif position['contract_type'] == 'PUT':
                    # For PUT options, take profit triggers when price drops below take profit
                    if current_price <= position['take_profit_price']:
                        take_profit_hit = True
                        logger.warning(f"Take profit hit (PUT): {position['symbol']} @ ${current_price:.2f} "
                                     f"<= ${position['take_profit_price']:.2f}")

                if take_profit_hit:
                    if self.config['order_settings'].get('auto_sell_on_take_profit', True):
                        # Verify position still exists in broker before closing
                        broker_pos = self.broker.get_position(option_symbol)
                        if broker_pos:
                            logger.info(f"Auto-selling position {option_symbol} due to take profit")
                            result = self.close_position(option_symbol, position['remaining_contracts'])
                            result['reason'] = 'take_profit'
                            results.append(result)
                        else:
                            logger.warning(f"Skipping TP close for {option_symbol} - not found in broker")
                            self.position_manager.delete_position(option_symbol)

            except Exception as e:
                logger.error(f"Error checking take profit for {option_symbol}: {e}", exc_info=True)

        return results

    def get_position_details(self) -> list:
        """
        Get all positions with live pricing
        Merges tracked positions with broker positions to ensure we show ALL open positions
        BROKER IS THE SOURCE OF TRUTH - positions not in broker are cleaned up

        Returns:
            list: List of position details with current P&L
        """
        positions_with_details = []

        # Get broker positions through the cached/error-tolerant accessor.
        # `just_fetched=True` only when this call hit the broker NOW.
        # Cache hits and stale-after-failure both return False — destructive
        # reconciliation against either is unsafe (we'd delete tracked
        # positions that exist but the cached snapshot didn't see yet).
        broker_positions, just_fetched = self._fetch_broker_positions()
        broker_symbols = {pos['symbol'] for pos in broker_positions}

        # Clean up tracked positions that no longer exist in broker — ONLY when
        # we just got a fresh authoritative answer from the broker right now.
        # Stale cache / transient network errors must never wipe out our local
        # tracking (and the server-side stops attached to those positions).
        if just_fetched:
            tracked_positions = self.position_manager.get_all_positions()
            for position in tracked_positions:
                option_symbol = position['option_symbol']
                if option_symbol not in broker_symbols:
                    logger.info(f"Removing stale tracked position {option_symbol} - not found in broker")
                    self.position_manager.delete_position(option_symbol)

        # Auto-import untracked broker OPTION positions. The most common cause
        # of an untracked broker option position is "we placed it via the
        # platform but the position-creation step missed it" — e.g. an earlier
        # bug deleted it, the platform restarted between order placement and
        # fill, or the order was placed before this DB existed. Self-heal by
        # creating a placeholder tracked entry (no SL/TP — user can drag
        # them onto the chart). Without this, the position is visible but
        # unmanageable.
        if just_fetched:
            for broker_pos in broker_positions:
                opt_sym = broker_pos.get('symbol', '')
                if not self._is_option_symbol(opt_sym):
                    continue  # stocks aren't ours to manage
                if self.position_manager.has_position(opt_sym):
                    continue
                try:
                    underlying = self._parse_underlying_from_option(opt_sym)
                    strike, ctype = self._parse_option_details(opt_sym)
                    qty = int(broker_pos.get('qty', 0) or 0)
                    if qty <= 0:
                        continue
                    self.position_manager.open_position(
                        option_symbol=opt_sym,
                        symbol=underlying,
                        contract_type=ctype,
                        strike=strike,
                        dte=0,  # unknown without parsing OCC date; UI accepts 0
                        total_contracts=qty,
                        entry_price=float(broker_pos.get('avg_entry_price', 0.0) or 0.0),
                        underlying_entry_price=float(broker_pos.get('current_price', 0.0) or 0.0),
                        stop_loss_price=None,
                        take_profit_price=None,
                        source_order_id=None,
                    )
                    logger.info(
                        "Auto-imported untracked broker option position: %s (%d contracts) — "
                        "drag SL/TP on the chart to attach exits",
                        opt_sym, qty,
                    )
                except Exception as e:
                    logger.warning("Auto-import failed for %s: %s", opt_sym, e)

        # Track which broker positions we've processed
        processed_broker_symbols = set()

        # Refresh tracked positions after cleanup
        tracked_positions = self.position_manager.get_all_positions()

        # Process tracked positions (these have SL/TP and other metadata)
        for position in tracked_positions:
            option_symbol = position['option_symbol']
            processed_broker_symbols.add(option_symbol)

            try:
                # Get current underlying price
                underlying_price = self.broker.get_current_price(position['symbol'])

                # Get current option position from broker
                broker_position = self.broker.get_position(option_symbol)

                if broker_position:
                    current_option_price = broker_position['current_price']
                    unrealized_pnl = broker_position['unrealized_pl']
                    unrealized_pnl_pct = broker_position['unrealized_plpc'] * 100
                else:
                    # Fallback: calculate from quote
                    quote = self.broker.get_option_quote(option_symbol)
                    current_option_price = quote['mid']

                    entry_value = position['remaining_contracts'] * position['entry_price'] * 100
                    current_value = position['remaining_contracts'] * current_option_price * 100
                    unrealized_pnl = current_value - entry_value
                    unrealized_pnl_pct = (unrealized_pnl / entry_value * 100) if entry_value > 0 else 0

                # Total P&L
                realized_pnl = position.get('realized_pnl', 0.0)
                total_pnl = realized_pnl + unrealized_pnl

                # Get partial closes history
                partial_closes = self.position_manager.get_position_closes_history(option_symbol)

                positions_with_details.append({
                    'symbol': position['symbol'],
                    'option_symbol': position['option_symbol'],
                    'strike': position['strike'],
                    'contract_type': position['contract_type'],
                    'dte': position.get('dte'),
                    'entry_price': position['entry_price'],
                    'current_price': current_option_price,
                    'total_contracts': position['total_contracts'],
                    'remaining_contracts': position['remaining_contracts'],
                    'entry_time': position['entry_time'],
                    'stop_loss_price': position.get('stop_loss_price'),
                    'take_profit_price': position.get('take_profit_price'),
                    'underlying_entry_price': position.get('underlying_entry_price'),
                    'underlying_current_price': underlying_price,
                    'realized_pnl': realized_pnl,
                    'unrealized_pnl': unrealized_pnl,
                    'unrealized_pnl_pct': unrealized_pnl_pct,
                    'total_pnl': total_pnl,
                    'partial_closes': partial_closes,
                    'is_tracked': True  # This position has full metadata
                })

            except Exception as e:
                logger.error(f"Error getting position details for {option_symbol}: {e}", exc_info=True)

        # Now add any broker positions that aren't tracked (external positions)
        for broker_pos in broker_positions:
            option_symbol = broker_pos['symbol']

            if option_symbol not in processed_broker_symbols:
                try:
                    is_option = self._is_option_symbol(option_symbol)
                    # Only log untracked OPTION positions (rare).
                    # Stock positions in the user's broker account are not
                    # something OptionsCanvas manages — quiet them.
                    if is_option:
                        logger.info(f"Found untracked broker option position: {option_symbol}")

                    underlying_symbol = self._parse_underlying_from_option(option_symbol)
                    strike, contract_type = self._parse_option_details(option_symbol)

                    # Use the position's current_price as the underlying proxy.
                    # For stock positions the symbol IS the underlying, so this is
                    # exact. For untracked option positions it's an approximation
                    # but avoids firing one extra broker quote per untracked
                    # position on every /api/position poll — that was costing
                    # ~500ms × N positions of wall time and starving every other
                    # REST endpoint, which prevented the trading panel's
                    # readiness check from ever completing (Buy button stayed
                    # disabled). If a precise underlying mid is needed later,
                    # fetch it on demand from the UI, not on every poll.
                    underlying_price = broker_pos.get('current_price', 0.0) or 0.0

                    positions_with_details.append({
                        'symbol': underlying_symbol,
                        'option_symbol': option_symbol,
                        'strike': strike,
                        'contract_type': contract_type,
                        'dte': None,  # Unknown
                        'entry_price': broker_pos['avg_entry_price'],
                        'current_price': broker_pos['current_price'],
                        'total_contracts': broker_pos['qty'],
                        'remaining_contracts': broker_pos['qty'],
                        'entry_time': 'External',  # Not tracked
                        'stop_loss_price': None,  # No SL/TP for external positions
                        'take_profit_price': None,
                        'underlying_entry_price': underlying_price,  # Use current as proxy
                        'underlying_current_price': underlying_price,
                        'realized_pnl': 0.0,  # Unknown
                        'unrealized_pnl': broker_pos['unrealized_pl'],
                        'unrealized_pnl_pct': broker_pos['unrealized_plpc'] * 100,
                        'total_pnl': broker_pos['unrealized_pl'],
                        'partial_closes': [],
                        'is_tracked': False,  # External position
                        'asset_type': 'option' if is_option else 'stock'
                    })

                except Exception as e:
                    logger.error(f"Error processing untracked position {option_symbol}: {e}")

        positions_with_details.sort(key=lambda pos: (pos.get('asset_type') != 'option', pos.get('symbol', '')))
        return positions_with_details

    def _is_option_symbol(self, symbol: str) -> bool:
        """Return True when symbol matches OCC option format."""
        import re
        return bool(re.match(r'^[A-Z]+\d{6}[CP]\d{8}$', symbol or ''))

    def _parse_underlying_from_option(self, option_symbol: str) -> str:
        """Extract underlying symbol from an OCC option symbol, or return stock symbol unchanged."""
        # Option format: SPY260116C00693000
        # Find where the date starts (6 digits YYMMDD)
        import re
        match = re.match(r'([A-Z]+)\d{6}[CP]\d{8}', option_symbol)
        if match:
            return match.group(1)
        return option_symbol

    def _parse_option_details(self, option_symbol: str) -> Tuple[float, str]:
        """Extract strike and contract type from an OCC option symbol."""
        import re
        # Option format: SPY260116C00693000
        match = re.match(r'[A-Z]+\d{6}([CP])(\d{8})', option_symbol)
        if match:
            contract_type = 'CALL' if match.group(1) == 'C' else 'PUT'
            strike = int(match.group(2)) / 1000.0  # Strike is in thousandths
            return strike, contract_type
        return None, None
