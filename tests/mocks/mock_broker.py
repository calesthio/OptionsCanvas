"""
Mock Broker for Testing
Implements BrokerInterface with controllable responses for testing
"""

from typing import Dict, List, Optional, Any, Tuple
from datetime import date, datetime, timedelta
import logging

from assisted_trading.backend.broker_interface import BrokerInterface

logger = logging.getLogger(__name__)


class MockBroker(BrokerInterface):
    """
    Mock broker implementation for testing.
    Allows tests to control responses and simulate various broker behaviors.
    """

    def __init__(self, api_key: str = "mock_key", secret_key: str = "mock_secret",
                 paper: bool = True, **kwargs):
        """Initialize mock broker"""
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper

        # Mock state
        self.account_info = {
            'account_number': 'MOCK123456',
            'status': 'ACTIVE',
            'buying_power': 100000.0,
            'cash': 100000.0,
            'portfolio_value': 100000.0,
            'pattern_day_trader': False,
            'trading_blocked': False,
            'account_blocked': False,
        }

        # Track orders and positions
        self.orders = {}
        self.positions = {}
        self.option_chains = {}

        # Track method calls for verification
        self.call_history = []

        logger.info("MockBroker initialized")

    def _record_call(self, method_name: str, **kwargs):
        """Record method call for testing verification"""
        self.call_history.append({
            'method': method_name,
            'timestamp': datetime.now(),
            **kwargs
        })

    # ========== Account Management ==========

    def get_account_info(self) -> Dict[str, Any]:
        """Get mock account information"""
        self._record_call('get_account_info')
        return self.account_info.copy()

    # ========== Market Data ==========

    def get_current_price(self, symbol: str) -> float:
        """Get mock current price"""
        self._record_call('get_current_price', symbol=symbol)
        # Return simple mock prices
        mock_prices = {
            'SPY': 450.0,
            'AAPL': 180.0,
            'MSFT': 370.0,
            'NVDA': 450.0,
        }
        return mock_prices.get(symbol, 100.0)

    def get_historical_bars(self, symbol: str, timeframe: str,
                           start: Optional[str] = None,
                           end: Optional[str] = None,
                           limit: int = 1000) -> List[Dict[str, Any]]:
        """Get mock historical bars"""
        self._record_call('get_historical_bars', symbol=symbol, timeframe=timeframe)
        # Return simple mock bar
        return [{
            'time': int(datetime.now().timestamp()),
            'open': 100.0,
            'high': 101.0,
            'low': 99.0,
            'close': 100.5,
            'volume': 1000000
        }]

    # ========== Options Data ==========

    def get_option_contracts(self, underlying_symbol: str,
                            dte: Optional[int] = None,
                            expiration_date: Optional[date] = None,
                            option_type: Optional[str] = None,
                            strike_price: Optional[float] = None) -> List[Dict[str, Any]]:
        """Get mock option contracts"""
        self._record_call('get_option_contracts', underlying_symbol=underlying_symbol, dte=dte)
        return [{
            'symbol': f'{underlying_symbol}250131C00450000',
            'underlying_symbol': underlying_symbol,
            'strike_price': 450.0,
            'expiration_date': date(2025, 1, 31),
            'type': option_type or 'call',
            'style': 'american',
            'size': 100
        }]

    def get_available_expirations(self, underlying_symbol: str,
                                  min_dte: int = 0,
                                  max_dte: int = 365) -> List[Dict[str, Any]]:
        """Get mock option expirations sorted by date."""
        self._record_call(
            'get_available_expirations',
            underlying_symbol=underlying_symbol,
            min_dte=min_dte,
            max_dte=max_dte
        )

        today = date.today()
        candidate_dtes = [0, 1, 2, 7, 14, 30, 45, 60, 90]
        expirations = []

        for dte in candidate_dtes:
            if min_dte <= dte <= max_dte:
                expiration_date = today + timedelta(days=dte)
                expirations.append({
                    'expiration_date': expiration_date,
                    'dte': dte,
                    'is_monthly': expiration_date.weekday() == 4 and 15 <= expiration_date.day <= 21
                })

        return expirations

    def get_option_quote(self, option_symbol: str) -> Dict[str, float]:
        """Get mock option quote"""
        self._record_call('get_option_quote', option_symbol=option_symbol)
        return {
            'bid': 5.0,
            'ask': 5.5,
            'mid': 5.25,
            'spread': 0.5,
            'iv': 0.25,
            'delta': 0.50,
            'gamma': 0.05,
            'theta': -0.10,
            'vega': 0.15
        }

    def get_atm_strike(self, underlying_symbol: str, current_price: float) -> float:
        """Get mock ATM strike"""
        self._record_call('get_atm_strike', underlying_symbol=underlying_symbol, current_price=current_price)
        increment = self.get_strike_increment(underlying_symbol, current_price)
        return round(current_price / increment) * increment

    # ========== Order Execution ==========

    def place_market_order(self, symbol: str, qty: int, side: str) -> Dict[str, Any]:
        """Place mock market order"""
        self._record_call('place_market_order', symbol=symbol, qty=qty, side=side)
        order_id = f'MOCK{len(self.orders) + 1}'
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': 'market',
            'status': 'accepted',
            'submitted_at': datetime.now(),
            'filled_avg_price': None,
            'filled_qty': 0,
        }
        self.orders[order_id] = order
        return order

    def place_limit_order(self, symbol: str, qty: int, side: str,
                         limit_price: float) -> Dict[str, Any]:
        """Place mock limit order"""
        self._record_call('place_limit_order', symbol=symbol, qty=qty, side=side, limit_price=limit_price)
        order_id = f'MOCK{len(self.orders) + 1}'
        order = {
            'order_id': order_id,
            'symbol': symbol,
            'qty': qty,
            'side': side,
            'type': 'limit',
            'limit_price': limit_price,
            'status': 'accepted',
            'submitted_at': datetime.now(),
            'filled_avg_price': None,
            'filled_qty': 0,
        }
        self.orders[order_id] = order
        return order

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get mock order status"""
        self._record_call('get_order_status', order_id=order_id)
        order = self.orders.get(order_id)
        if order:
            return {
                'order_id': order['order_id'],
                'status': order.get('status', 'unknown'),
                'filled_qty': order.get('filled_qty', 0),
                'filled_avg_price': order.get('filled_avg_price'),
                'filled_at': order.get('filled_at'),
            }
        return {'order_id': order_id, 'status': 'not_found', 'filled_qty': 0, 'filled_avg_price': None, 'filled_at': None}

    def cancel_order(self, order_id: str) -> bool:
        """Cancel mock order"""
        self._record_call('cancel_order', order_id=order_id)
        if order_id in self.orders:
            self.orders[order_id]['status'] = 'canceled'
            return True
        return False

    # ========== Position Management ==========

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get mock position"""
        self._record_call('get_position', symbol=symbol)
        return self.positions.get(symbol)

    def get_all_positions(self) -> List[Dict[str, Any]]:
        """Get all mock positions"""
        self._record_call('get_all_positions')
        return list(self.positions.values())

    def close_position(self, symbol: str, qty: Optional[int] = None) -> Dict[str, Any]:
        """Close mock position"""
        self._record_call('close_position', symbol=symbol, qty=qty)
        if symbol in self.positions:
            position = self.positions[symbol]
            close_qty = qty if qty else position['qty']
            # Create market order to close
            order = self.place_market_order(symbol, close_qty, 'sell')
            # Remove or update position
            if qty is None or close_qty >= position['qty']:
                del self.positions[symbol]
            else:
                position['qty'] -= close_qty
            return order
        return {'order_id': 'NONE', 'status': 'failed', 'symbol': symbol}

    # ========== Helper Methods for Testing ==========

    def set_account_balance(self, buying_power: float, cash: float = None):
        """Set mock account balance for testing"""
        self.account_info['buying_power'] = buying_power
        if cash is not None:
            self.account_info['cash'] = cash

    def simulate_order_fill(self, order_id: str, filled_price: float):
        """Simulate an order being filled"""
        if order_id in self.orders:
            order = self.orders[order_id]
            order['status'] = 'filled'
            order['filled_qty'] = order['qty']
            order['filled_avg_price'] = filled_price

    def add_position(self, symbol: str, qty: int, avg_entry_price: float):
        """Add a mock position"""
        self.positions[symbol] = {
            'symbol': symbol,
            'qty': qty,
            'avg_entry_price': avg_entry_price,
            'market_value': qty * avg_entry_price,
            'unrealized_pl': 0.0,
        }

    def clear_call_history(self):
        """Clear call history for testing"""
        self.call_history = []

    # ========== Configuration & Metadata ==========

    def get_tick_size(self, symbol: str, price: float) -> float:
        """Get mock tick size"""
        self._record_call('get_tick_size', symbol=symbol, price=price)
        # Standard option tick sizes
        if price < 3.0:
            return 0.05
        else:
            return 0.10

    def get_strike_increment(self, underlying_symbol: str, price: float) -> float:
        """Get mock strike increment"""
        self._record_call('get_strike_increment', underlying_symbol=underlying_symbol, price=price)
        # Standard strike increments
        if price < 50:
            return 1.0
        elif price < 200:
            return 2.5
        else:
            return 5.0

    def validate_connection(self) -> Tuple[bool, str]:
        """Validate mock connection"""
        self._record_call('validate_connection')
        return (True, "Mock broker connection valid")
