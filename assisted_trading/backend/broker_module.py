"""
Broker Module for SPY Liquidity Grab Trading System
Handles all Alpaca API interactions for market data and order execution
"""

import time
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Tuple, Any
import logging
import pytz
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType, QueryOrderStatus, AssetStatus
from alpaca.trading.requests import MarketOrderRequest, GetOrdersRequest
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import (
    StockLatestTradeRequest,
    OptionLatestQuoteRequest,
)

from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.common.exceptions import APIError




logger = logging.getLogger(__name__)


class BrokerError(Exception):
    """Custom exception for broker-related errors"""
    pass


class BrokerModule:
    """
    Interface with Alpaca API for market data and order execution
    Handles rate limiting, retries, and error recovery
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True,
                 data_feed: str = 'sip', max_retries: int = 3):
        """
        Initialize Alpaca API clients

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            paper: Use paper trading (default True)
            data_feed: Data feed type ('sip' or 'iex')
            max_retries: Maximum API retry attempts
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.data_feed = data_feed.upper()
        self.max_retries = max_retries

        try:
            # Initialize clients
            self.trading_client = TradingClient(api_key, secret_key, paper=paper)
            self.stock_data_client = StockHistoricalDataClient(api_key, secret_key)
            self.option_data_client = OptionHistoricalDataClient(api_key, secret_key)
            # Use trading_client for options (unified in newer versions)
            self.options_client = self.trading_client

            logger.info(f"Broker module initialized (paper={paper}, feed={data_feed})")

            # Validate connection
            self._validate_connection()

        except Exception as e:
            logger.error(f"Failed to initialize broker module: {e}")
            raise BrokerError(f"Initialization failed: {e}")

    def _validate_connection(self):
        """Validate API connection and credentials"""
        try:
            account = self.trading_client.get_account()
            logger.info(f"Account validated: {account.account_number} (Status: {account.status})")

            if account.trading_blocked:
                raise BrokerError("Trading is blocked on this account")

            logger.info(f"Buying power: ${float(account.buying_power):,.2f}")
            logger.info(f"Cash: ${float(account.cash):,.2f}")

        except APIError as e:
            raise BrokerError(f"API connection failed: {e}")

    def _retry_api_call(self, func, *args, **kwargs):
        """
        Retry API call with exponential backoff

        Args:
            func: Function to call
            *args, **kwargs: Arguments to pass to function

        Returns:
            Function result

        Raises:
            BrokerError: If all retries fail
        """
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except APIError as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"API call failed after {self.max_retries} attempts: {e}")
                    raise BrokerError(f"API call failed: {e}")

                wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                logger.warning(f"API call failed (attempt {attempt + 1}/{self.max_retries}), "
                             f"retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

    def get_account_info(self) -> Dict[str, Any]:
        """
        Get account information

        Returns:
            Dictionary with account details
        """
        try:
            account = self._retry_api_call(self.trading_client.get_account)
            return {
                'account_number': account.account_number,
                'status': account.status,
                'buying_power': float(account.buying_power),
                'cash': float(account.cash),
                'portfolio_value': float(account.portfolio_value),
                'pattern_day_trader': account.pattern_day_trader,
                'trading_blocked': account.trading_blocked,
                'account_blocked': account.account_blocked,
            }
        except Exception as e:
            logger.error(f"Failed to get account info: {e}")
            raise BrokerError(f"Failed to get account info: {e}")


    def get_current_price(self, symbol: str) -> float:
        """
        Get current price for symbol

        Args:
            symbol: Stock symbol

        Returns:
            Current price
        """
        try:
            trade_request = StockLatestTradeRequest(
                symbol_or_symbols=symbol,
                feed=DataFeed[self.data_feed] if self.data_feed in ['SIP', 'IEX'] else DataFeed.SIP,
            )

            latest_trade = self._retry_api_call(
                self.stock_data_client.get_stock_latest_trade,
                trade_request
            )

            if symbol not in latest_trade:
                raise BrokerError(f"No trade data available for {symbol}")

            price = latest_trade[symbol].price
            logger.debug(f"Current price for {symbol}: ${price:.2f}")
            return price

        except Exception as e:
            logger.error(f"Failed to get current price: {e}")
            raise BrokerError(f"Failed to get current price: {e}")



    def get_atm_strike(self, underlying_symbol: str, current_price: float) -> float:
        """
        Get ATM (at-the-money) strike price

        Args:
            underlying_symbol: Underlying stock symbol
            current_price: Current stock price

        Returns:
            ATM strike price
        """
        # SPY options are typically in $1 increments for ATM strikes
        # Round to nearest dollar
        atm_strike = round(current_price)
        logger.debug(f"ATM strike for {underlying_symbol} at ${current_price:.2f}: ${atm_strike:.2f}")
        return atm_strike

    def get_option_contracts(self, underlying_symbol: str, dte: int = 0,
                           option_type: str = 'call',
                           strike_price: Optional[float] = None,
                           date_now: Optional[date] = None) -> List[Dict[str, Any]]:
        """
        Get available option contracts

        Args:
            underlying_symbol: Underlying symbol (e.g. SPY)
            dte: Days to expiration (default 0)
            option_type: 'call' or 'put' (default 'call')
            strike_price: Optional strike price filter
            date_now: Optional specific date (for backtesting)

        Returns:
            List of option contract dictionaries
        """
        try:
            # Calculate expiration date range
            today = date_now if date_now else date.today()
            target_exp_date = today + timedelta(days=dte)

            # For 0 DTE, use today
            if dte == 0:
                exp_start = today
                exp_end = today
            else:
                # Allow some flexibility in expiration date
                exp_start = target_exp_date - timedelta(days=1)
                exp_end = target_exp_date + timedelta(days=1)

            contracts_req = GetOptionContractsRequest(
                underlying_symbol=underlying_symbol,
                # status=AssetStatus.ACTIVE,  # Removed to find expired contracts for backtest
                expiration_date_gte=exp_start,
                expiration_date_lte=exp_end,
                type=option_type,
            )

            # Prepare base request parameters
            req_params = {
                'underlying_symbol': underlying_symbol,
                'expiration_date_gte': exp_start,
                'expiration_date_lte': exp_end,
                'type': option_type,
            }
            
            # Add strike price filters if specified
            if strike_price is not None:
                req_params['strike_price_gte'] = str(strike_price - 0.5)
                req_params['strike_price_lte'] = str(strike_price + 0.5)

            # Try finding ACTIVE contracts first (leaps or live trading)
            contracts_req = GetOptionContractsRequest(
                status=AssetStatus.ACTIVE,
                **req_params
            )

            contracts_response = self._retry_api_call(
                self.options_client.get_option_contracts,
                contracts_req
            )

            # Initialize results with active contracts
            all_contracts = contracts_response.option_contracts if contracts_response and hasattr(contracts_response, 'option_contracts') else []

            # If fewer than expected (arbitrary small number) and we sort of expect data, 
            # OR if we are specifically looking at past dates, try INACTIVE
            # Simple logic: If we found nothing AND we are backtesting (date_now provided), try INACTIVE.
            if not all_contracts and date_now:
                logger.debug(f"No active contracts found for {underlying_symbol} on {date_now}, checking expired/inactive...")
                contracts_req.status = AssetStatus.INACTIVE
                contracts_response = self._retry_api_call(
                    self.options_client.get_option_contracts,
                    contracts_req
                )
                if contracts_response and hasattr(contracts_response, 'option_contracts'):
                    all_contracts.extend(contracts_response.option_contracts)

            if not all_contracts:
                logger.warning(f"No option contracts found (Active or Inactive) for {underlying_symbol} "
                             f"with {dte} DTE and strike ${strike_price}")
                return []

            contracts_list = []
            contracts_list = []
            for contract in all_contracts:
                if contract.underlying_symbol != underlying_symbol:
                    logger.debug(f"Filtering out contract {contract.symbol} with underlying {contract.underlying_symbol} (requested {underlying_symbol})")
                    continue
                    
                contracts_list.append({
                    'symbol': contract.symbol,
                    'underlying_symbol': contract.underlying_symbol,
                    'strike_price': contract.strike_price,
                    'expiration_date': contract.expiration_date,
                    'type': contract.type,
                    'style': contract.style,
                    'size': contract.size,
                })

            logger.info(f"Found {len(contracts_list)} option contracts")
            return contracts_list

        except Exception as e:
            logger.error(f"Failed to get option contracts: {e}")
            raise BrokerError(f"Failed to get option contracts: {e}")

    def get_option_quote(self, option_symbol: str) -> Dict[str, float]:
        """
        Get option quote with bid/ask/greeks

        Args:
            option_symbol: Option symbol (OCC format)

        Returns:
            Dictionary with quote data
        """
        try:
            quote_request = OptionLatestQuoteRequest(
                symbol_or_symbols=option_symbol,
                feed=OptionsFeed.OPRA,
            )

            latest_quote = self._retry_api_call(
                self.option_data_client.get_option_latest_quote,
                quote_request
            )

            if option_symbol not in latest_quote:
                raise BrokerError(f"No quote data for option {option_symbol}")

            quote = latest_quote[option_symbol]

            result = {
                'bid': quote.bid_price,
                'ask': quote.ask_price,
                'mid': (quote.bid_price + quote.ask_price) / 2,
                'spread': quote.ask_price - quote.bid_price,
            }

            # Add Greeks if available
            if hasattr(quote, 'implied_volatility') and quote.implied_volatility:
                result['iv'] = quote.implied_volatility
            if hasattr(quote, 'delta') and quote.delta:
                result['delta'] = quote.delta
            if hasattr(quote, 'gamma') and quote.gamma:
                result['gamma'] = quote.gamma
            if hasattr(quote, 'theta') and quote.theta:
                result['theta'] = quote.theta
            if hasattr(quote, 'vega') and quote.vega:
                result['vega'] = quote.vega

            logger.debug(f"Option quote for {option_symbol}: Bid=${result['bid']:.2f}, "
                        f"Ask=${result['ask']:.2f}")
            return result

        except Exception as e:
            logger.error(f"Failed to get option quote: {e}")
            raise BrokerError(f"Failed to get option quote: {e}")

    def place_market_order(self, symbol: str, qty: int, side: str) -> Dict[str, Any]:
        """
        Place market order for option or stock

        Args:
            symbol: Option or stock symbol
            qty: Quantity (number of contracts or shares)
            side: 'buy' or 'sell'

        Returns:
            Order details dictionary
        """
        try:
            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

            order_request = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )

            logger.info(f"Placing market order: {side.upper()} {qty} {symbol}")

            order = self._retry_api_call(self.trading_client.submit_order, order_request)

            logger.info(f"Order submitted: ID={order.id}, Status={order.status}")

            return {
                'order_id': str(order.id),
                'symbol': order.symbol,
                'qty': int(order.qty),
                'side': order.side.value,
                'type': order.type.value,
                'status': order.status.value,
                'submitted_at': order.submitted_at,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None,
            }

        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            raise BrokerError(f"Failed to place order: {e}")

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Get order status

        Args:
            order_id: Order ID

        Returns:
            Order status dictionary
        """
        try:
            order = self._retry_api_call(self.trading_client.get_order_by_id, order_id)

            return {
                'order_id': str(order.id),
                'status': order.status.value,
                'filled_qty': int(order.filled_qty) if order.filled_qty else 0,
                'filled_avg_price': float(order.filled_avg_price) if order.filled_avg_price else None,
                'filled_at': order.filled_at,
            }

        except Exception as e:
            logger.error(f"Failed to get order status: {e}")
            raise BrokerError(f"Failed to get order status: {e}")

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Get current position for symbol

        Args:
            symbol: Option or stock symbol

        Returns:
            Position dictionary or None if no position
        """
        try:
            positions = self._retry_api_call(self.trading_client.get_all_positions)

            for position in positions:
                if position.symbol == symbol:
                    return {
                        'symbol': position.symbol,
                        'qty': int(position.qty),
                        'avg_entry_price': float(position.avg_entry_price),
                        'current_price': float(position.current_price),
                        'market_value': float(position.market_value),
                        'cost_basis': float(position.cost_basis),
                        'unrealized_pl': float(position.unrealized_pl),
                        'unrealized_plpc': float(position.unrealized_plpc),
                    }

            return None

        except Exception as e:
            logger.error(f"Failed to get position: {e}")
            raise BrokerError(f"Failed to get position: {e}")

    def close_position(self, symbol: str, qty: Optional[int] = None) -> Dict[str, Any]:
        """
        Close position (sell all or partial)

        Args:
            symbol: Option or stock symbol
            qty: Quantity to close (None = close all)

        Returns:
            Order details dictionary
        """
        try:
            position = self.get_position(symbol)

            if position is None:
                raise BrokerError(f"No position found for {symbol}")

            qty_to_close = qty if qty is not None else position['qty']

            if qty_to_close > position['qty']:
                raise BrokerError(f"Cannot close {qty_to_close} contracts, only {position['qty']} held")

            return self.place_market_order(symbol, qty_to_close, 'sell')

        except Exception as e:
            logger.error(f"Failed to close position: {e}")
            raise BrokerError(f"Failed to close position: {e}")


    def __repr__(self) -> str:
        """String representation"""
        return f"BrokerModule(paper={self.paper}, feed={self.data_feed})"

