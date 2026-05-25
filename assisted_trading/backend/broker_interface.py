"""
Broker Interface - Abstract Base Class for all broker implementations
Provides a unified interface for multi-broker support
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Tuple
from datetime import date
import logging

logger = logging.getLogger(__name__)


class BrokerInterface(ABC):
    """
    Abstract base class defining the interface that all broker adapters must implement.
    This enables the platform to support multiple brokers (Alpaca, IBKR, etc.) with a unified API.
    """

    @abstractmethod
    def __init__(self, api_key: str, secret_key: str, paper: bool = True, **kwargs):
        """
        Initialize broker connection

        Args:
            api_key: API key for broker
            secret_key: Secret key for broker
            paper: Whether to use paper trading (default True)
            **kwargs: Additional broker-specific configuration
        """
        pass

    # ========== Account Management ==========

    @abstractmethod
    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information

        Returns:
            Dictionary with standardized account fields:
            {
                'account_number': str,
                'status': str,
                'buying_power': float,
                'cash': float,
                'portfolio_value': float,
                'pattern_day_trader': bool,
                'trading_blocked': bool,
                'account_blocked': bool,
            }
        """
        pass

    # ========== Market Data ==========

    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """
        Get current price for symbol

        Args:
            symbol: Stock symbol (e.g., 'SPY', 'AAPL')

        Returns:
            Current price as float
        """
        pass

    @abstractmethod
    def get_historical_bars(self, symbol: str, timeframe: str,
                           start: Optional[str] = None,
                           end: Optional[str] = None,
                           limit: int = 1000) -> List[Dict[str, Any]]:
        """
        Get historical price bars for charting

        Args:
            symbol: Stock symbol
            timeframe: Bar timeframe (e.g., '1Min', '5Min', '1Hour', '1Day')
            start: Start time in ISO format (optional)
            end: End time in ISO format (optional)
            limit: Maximum number of bars to return

        Returns:
            List of bar dictionaries:
            [
                {
                    'time': unix_timestamp,
                    'open': float,
                    'high': float,
                    'low': float,
                    'close': float,
                    'volume': int
                },
                ...
            ]
        """
        pass

    # ========== Options Data ==========

    @abstractmethod
    def get_option_contracts(self, underlying_symbol: str,
                            dte: Optional[int] = None,
                            expiration_date: Optional[date] = None,
                            option_type: Optional[str] = None,
                            strike_price: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Get available option contracts

        Args:
            underlying_symbol: Underlying stock symbol
            dte: Days to expiration (optional)
            expiration_date: Specific expiration date (optional)
            option_type: 'call' or 'put' (optional)
            strike_price: Strike price filter (optional)

        Returns:
            List of contract dictionaries:
            [
                {
                    'symbol': str,              # OCC symbol
                    'underlying_symbol': str,
                    'strike_price': float,
                    'expiration_date': date,
                    'type': str,                # 'call' or 'put'
                    'style': str,               # 'american' or 'european'
                    'size': int                 # Contract size (usually 100)
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def get_available_expirations(self, underlying_symbol: str,
                                  min_dte: int = 0,
                                  max_dte: int = 365) -> List[Dict[str, Any]]:
        """
        Get all available option expiration dates for a symbol.
        Every broker must implement this for contract discovery.

        Args:
            underlying_symbol: Underlying stock symbol
            min_dte: Minimum days to expiration (default 0)
            max_dte: Maximum days to expiration (default 365)

        Returns:
            List of expiration dictionaries, sorted by date:
            [
                {
                    'expiration_date': date,     # Python date object
                    'dte': int,                  # Days to expiration
                    'is_monthly': bool           # True if 3rd Friday expiration
                },
                ...
            ]
        """
        pass

    @abstractmethod
    def get_option_quote(self, option_symbol: str) -> Dict[str, float]:
        """
        Get option quote with bid/ask/greeks

        Args:
            option_symbol: Option symbol in OCC format

        Returns:
            Dictionary with quote data:
            {
                'bid': float,
                'ask': float,
                'mid': float,
                'spread': float,
                'iv': float,        # Implied volatility (optional)
                'delta': float,     # (optional)
                'gamma': float,     # (optional)
                'theta': float,     # (optional)
                'vega': float       # (optional)
            }
        """
        pass

    @abstractmethod
    def get_atm_strike(self, underlying_symbol: str, current_price: float) -> float:
        """
        Get ATM (at-the-money) strike price based on current price

        Args:
            underlying_symbol: Underlying stock symbol
            current_price: Current stock price

        Returns:
            ATM strike price rounded to appropriate increment
        """
        pass

    # ========== Order Execution ==========

    @abstractmethod
    def place_market_order(self, symbol: str, qty: int, side: str) -> Dict[str, Any]:
        """
        Place market order for option or stock

        Args:
            symbol: Option or stock symbol
            qty: Quantity (number of contracts or shares)
            side: 'buy' or 'sell'

        Returns:
            Order details dictionary:
            {
                'order_id': str,
                'symbol': str,
                'qty': int,
                'side': str,
                'type': str,
                'status': str,
                'submitted_at': datetime,
                'filled_avg_price': Optional[float]
            }
        """
        pass

    @abstractmethod
    def place_limit_order(self, symbol: str, qty: int, side: str,
                         limit_price: float) -> Dict[str, Any]:
        """
        Place limit order for option or stock

        Args:
            symbol: Option or stock symbol
            qty: Quantity
            side: 'buy' or 'sell'
            limit_price: Limit price

        Returns:
            Order details dictionary (same format as place_market_order)
        """
        pass

    @abstractmethod
    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Get order status

        Args:
            order_id: Order ID

        Returns:
            Order status dictionary:
            {
                'order_id': str,
                'status': str,              # 'filled', 'pending', 'rejected', etc.
                'filled_qty': int,
                'filled_avg_price': Optional[float],
                'filled_at': Optional[datetime]
            }
        """
        pass

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order

        Args:
            order_id: Order ID to cancel

        Returns:
            True if successfully canceled, False otherwise
        """
        pass

    # ========== Position Management ==========

    @abstractmethod
    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current position for symbol

        Args:
            symbol: Option or stock symbol

        Returns:
            Position dictionary or None if no position:
            {
                'symbol': str,
                'qty': int,
                'avg_entry_price': float,
                'current_price': float,
                'market_value': float,
                'cost_basis': float,
                'unrealized_pl': float,
                'unrealized_plpc': float    # Percent as decimal (0.05 = 5%)
            }
        """
        pass

    @abstractmethod
    def get_all_positions(self) -> List[Dict[str, Any]]:
        """
        Get all open positions

        Returns:
            List of position dictionaries (same format as get_position)
        """
        pass

    @abstractmethod
    def close_position(self, symbol: str, qty: Optional[int] = None) -> Dict[str, Any]:
        """
        Close position (sell all or partial)

        Args:
            symbol: Option or stock symbol
            qty: Quantity to close (None = close all)

        Returns:
            Order details dictionary (same format as place_market_order)
        """
        pass

    # ========== Configuration & Metadata ==========

    @abstractmethod
    def get_tick_size(self, symbol: str, price: float) -> float:
        """
        Get tick size (minimum price increment) for a symbol at a given price

        Args:
            symbol: Option or stock symbol
            price: Current price level

        Returns:
            Tick size (e.g., 0.01, 0.05, 0.10)

        Note:
            Options typically have price-dependent tick sizes:
            - Below $3.00: $0.05 increments
            - $3.00 and above: $0.10 increments
        """
        pass

    @abstractmethod
    def get_strike_increment(self, underlying_symbol: str, price: float) -> float:
        """
        Get strike price increment for options on a given underlying at price level

        Args:
            underlying_symbol: Underlying stock symbol
            price: Current underlying price

        Returns:
            Strike increment (e.g., 1.0, 2.5, 5.0)

        Note:
            Strike increments vary by underlying and price:
            - SPY: Typically $1 increments
            - High-priced stocks: May use $5 or $10 increments
        """
        pass

    @abstractmethod
    def validate_connection(self) -> Tuple[bool, str]:
        """
        Validate broker connection and credentials

        Returns:
            Tuple of (success: bool, message: str)
        """
        pass

    # ========== Utility Methods ==========

    def round_to_tick(self, price: float, tick_size: float) -> float:
        """
        Round price to nearest tick size

        Args:
            price: Price to round
            tick_size: Tick size

        Returns:
            Rounded price
        """
        import math
        return round(price / tick_size) * tick_size

    def __repr__(self) -> str:
        """String representation"""
        return f"{self.__class__.__name__}()"
