"""
Alpaca Broker Adapter - Implementation of BrokerInterface for Alpaca
Wraps the existing BrokerModule to conform to the new interface
"""

import time
import logging
from datetime import datetime, timedelta, date, timezone
from typing import Dict, List, Optional, Any, Tuple

from .broker_interface import BrokerInterface
from .broker_module import BrokerModule, BrokerError

logger = logging.getLogger(__name__)


class AlpacaBroker(BrokerInterface):
    """
    Alpaca broker adapter implementing the BrokerInterface.
    Wraps the existing BrokerModule for compatibility with the new abstraction layer.
    """

    def __init__(self, api_key: str, secret_key: str, paper: bool = True, **kwargs):
        """
        Initialize Alpaca broker connection

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            paper: Use paper trading (default True)
            **kwargs: Additional configuration:
                - data_feed: 'sip' or 'iex' (default 'sip')
                - max_retries: Maximum API retry attempts (default 3)
        """
        self.api_key = api_key
        self.secret_key = secret_key
        self.paper = paper
        self.data_feed = kwargs.get('data_feed', 'sip')
        self.max_retries = kwargs.get('max_retries', 3)

        # Initialize the underlying BrokerModule
        self.broker = BrokerModule(
            api_key=api_key,
            secret_key=secret_key,
            paper=paper,
            data_feed=self.data_feed,
            max_retries=self.max_retries
        )

        logger.info(f"AlpacaBroker initialized (paper={paper}, feed={self.data_feed})")

    # ========== Account Management ==========

    def get_account_info(self) -> Dict[str, Any]:
        """Get account information from Alpaca"""
        return self.broker.get_account_info()

    # ========== Market Data ==========

    def get_current_price(self, symbol: str) -> float:
        """Get current price for symbol"""
        return self.broker.get_current_price(symbol)

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
            List of bar dictionaries with standardized format
        """
        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
            from alpaca.data.enums import DataFeed
            import pytz

            # Parse timeframe string (e.g., '1Min', '5Min', '1Hour', '1Day')
            timeframe_map = {
                '1Min': TimeFrame(1, TimeFrameUnit.Minute),
                '5Min': TimeFrame(5, TimeFrameUnit.Minute),
                '15Min': TimeFrame(15, TimeFrameUnit.Minute),
                '30Min': TimeFrame(30, TimeFrameUnit.Minute),
                '1Hour': TimeFrame(1, TimeFrameUnit.Hour),
                '4Hour': TimeFrame(4, TimeFrameUnit.Hour),
                '1Day': TimeFrame(1, TimeFrameUnit.Day),
            }

            tf = timeframe_map.get(timeframe)
            if not tf:
                raise ValueError(f"Unsupported timeframe: {timeframe}")

            # Parse datetime strings if provided
            start_dt = None
            end_dt = None
            if start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
            else:
                # Dynamic start calculation
                # If limit is small (streaming), look back just enough
                # If limit is large (chart load), look back far enough
                timeFrames_minutes = {
                    '1Min': 1, '5Min': 5, '15Min': 15, '30Min': 30,
                    '1Hour': 60, '4Hour': 240, '1Day': 1440
                }
                
                minutes_per_bar = timeFrames_minutes.get(timeframe, 1)
                
                # Calculate required lookback in minutes
                # Use a multiplier (e.g. 5x) to account for weekends/market closures
                lookback_minutes = limit * minutes_per_bar * 10
                
                # Minimum lookback of 1 day to be safe
                lookback_minutes = max(lookback_minutes, 1440)
                
                start_dt = datetime.now(timezone.utc) - timedelta(minutes=lookback_minutes)

            if end:
                end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))

            # Create request
            feed_type = DataFeed[self.data_feed.upper()] if self.data_feed.upper() in ['SIP', 'IEX'] else DataFeed.SIP
            
            request_params = {
                'symbol_or_symbols': symbol,
                'timeframe': tf,
                # 'limit': limit, # Don't limit API call if we want LATEST bars (since Alpaca sorts ASC)
                'feed': feed_type
            }

            # Only pass limit if START was explicitly provided (meaning user wants "N bars after X")
            # If start was auto-calculated, we want "Latest N bars", so we fetch all from start and slice later
            if start:
                 request_params['limit'] = limit

            if start_dt:
                request_params['start'] = start_dt
            if end_dt:
                request_params['end'] = end_dt

            logger.info(f"Fetching bars for {symbol}: Timeframe={timeframe}, Limit={limit}, Start={start_dt}, Feed={feed_type}")

            bars_request = StockBarsRequest(**request_params)

            # Get bars
            bars_response = self.broker._retry_api_call(
                self.broker.stock_data_client.get_stock_bars,
                bars_request
            )

            # Extract data from BarSet
            # BarSet has a .data property which is the dictionary {symbol: [bars]}
            bars_data = {}
            if hasattr(bars_response, 'data'):
                bars_data = bars_response.data
            else:
                bars_data = bars_response

            if symbol not in bars_data:
                logger.warning(f"No bar data available for {symbol}. keys: {list(bars_data.keys()) if hasattr(bars_data, 'keys') else 'No keys'}")
                return []

            # Convert to standardized format
            bars_list = []
            # Check if there is data for the symbol
            if bars_data[symbol]:
                for bar in bars_data[symbol]:
                    bars_list.append({
                        'time': int(bar.timestamp.timestamp()),  # Unix timestamp
                        'open': float(bar.open),
                        'high': float(bar.high),
                        'low': float(bar.low),
                        'close': float(bar.close),
                        'volume': int(bar.volume)
                    })
            
            if not bars_list:
                logger.warning(f"Response contained key {symbol} but list was empty.")
                return []
            
            # If no start was provided (auto-calc), we wanted the LATEST 'limit' bars
            # Implementation: We fetched everything since calculated start, now take the tail
            if not start and limit < len(bars_list):
                 bars_list = bars_list[-limit:]

            logger.info(f"Retrieved {len(bars_list)} bars for {symbol}")
            return bars_list

        except Exception as e:
            logger.error(f"Failed to get historical bars: {e}", exc_info=True)
            raise BrokerError(f"Failed to get historical bars: {e}")

    # ========== Options Data ==========

    def get_option_contracts(self, underlying_symbol: str,
                            dte: Optional[int] = None,
                            expiration_date: Optional[date] = None,
                            option_type: Optional[str] = None,
                            strike_price: Optional[float] = None) -> List[Dict[str, Any]]:
        """Get available option contracts"""
        # Use existing broker method (handles both dte and expiration_date)
        date_now = None
        if expiration_date:
            date_now = expiration_date - timedelta(days=(dte or 0))

        contracts = self.broker.get_option_contracts(
            underlying_symbol=underlying_symbol,
            dte=dte if dte is not None else 0,
            option_type=option_type or 'call',
            strike_price=strike_price,
            date_now=date_now
        )

        return contracts

    def get_option_chain(self, symbol: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """
        Get option chain for discovery of available expirations

        Args:
            symbol: Underlying symbol
            start_date: Start date 'YYYY-MM-DD'
            end_date: End date 'YYYY-MM-DD'

        Returns:
            List of contracts with expiration_date field
        """
        try:
            from alpaca.data.requests import OptionChainRequest

            # Use Alpaca option chain API
            request = OptionChainRequest(
                underlying_symbol=symbol,
                feed='indicative',  # Use indicative feed for snapshot data
                expiration_date_gte=start_date,  # Filter by start date
                expiration_date_lte=end_date      # Filter by end date
            )

            # Get option chain snapshot
            option_chain = self.broker._retry_api_call(
                self.broker.option_data_client.get_option_chain,
                request
            )

            contracts = []
            if option_chain:
                # Extract contracts from the chain
                for contract_symbol, snapshot in option_chain.items():
                    # Parse contract symbol to extract expiration
                    # Format: SYMBOLYYMMDD C/P STRIKE (no spaces)
                    # e.g., SPY260121C00600000
                    symbol_len = len(symbol)
                    if len(contract_symbol) >= symbol_len + 15:
                        exp_str = contract_symbol[symbol_len:symbol_len+6]
                        try:
                            # Parse YYMMDD
                            year = 2000 + int(exp_str[0:2])
                            month = int(exp_str[2:4])
                            day = int(exp_str[4:6])
                            exp_date = date(year, month, day)

                            # Filter by date range
                            start = datetime.strptime(start_date, '%Y-%m-%d').date()
                            end = datetime.strptime(end_date, '%Y-%m-%d').date()

                            if start <= exp_date <= end:
                                contracts.append({
                                    'symbol': contract_symbol,
                                    'expiration_date': exp_date.strftime('%Y-%m-%d')
                                })
                        except (ValueError, IndexError):
                            continue

            logger.info(f"Found {len(contracts)} contracts for {symbol} between {start_date} and {end_date}")
            return contracts

        except Exception as e:
            logger.error(f"Failed to get option chain for {symbol}: {e}", exc_info=True)
            # Fallback: return empty list instead of raising
            return []

    def get_available_expirations(self, underlying_symbol: str,
                                  min_dte: int = 0,
                                  max_dte: int = 365) -> List[Dict[str, Any]]:
        """
        Get all available option expiration dates from Alpaca.
        Uses get_option_chain() internally to discover expirations.
        """
        import pytz
        est = pytz.timezone('America/New_York')
        now_est = datetime.now(est)
        current_date = now_est.date()

        # After 4 PM EST, today's options have expired
        market_close_time = datetime.strptime("16:00", "%H:%M").time()
        if now_est.time() > market_close_time:
            current_date = current_date + timedelta(days=1)
            logger.info(f"After market close, treating {current_date} as earliest valid date")

        start_date = current_date + timedelta(days=min_dte)
        end_date = current_date + timedelta(days=max_dte)

        option_chain = self.get_option_chain(
            symbol=underlying_symbol,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )

        # Extract unique expirations
        expirations = set()
        for contract in option_chain:
            exp_str = contract.get('expiration_date')
            if exp_str:
                try:
                    exp_date = datetime.strptime(exp_str, '%Y-%m-%d').date()
                    if exp_date >= current_date:
                        expirations.add(exp_date)
                except ValueError:
                    continue

        # Build sorted result
        result = []
        for exp_date in sorted(expirations):
            dte = (exp_date - current_date).days
            result.append({
                'expiration_date': exp_date,
                'dte': dte,
                'is_monthly': self._is_monthly_expiration(exp_date)
            })

        logger.info(f"Found {len(result)} expirations for {underlying_symbol}")
        return result

    @staticmethod
    def _is_monthly_expiration(exp_date: date) -> bool:
        """Check if expiration date is a 3rd-Friday monthly."""
        if exp_date.weekday() != 4:  # Not Friday
            return False
        first_day = exp_date.replace(day=1)
        first_friday = first_day + timedelta(days=(4 - first_day.weekday()) % 7)
        third_friday = first_friday + timedelta(weeks=2)
        return exp_date == third_friday

    def get_option_quote(self, option_symbol: str) -> Dict[str, float]:
        """Get option quote with bid/ask/greeks"""
        return self.broker.get_option_quote(option_symbol)

    def get_atm_strike(self, underlying_symbol: str, current_price: float) -> float:
        """Get ATM strike price"""
        return self.broker.get_atm_strike(underlying_symbol, current_price)

    # ========== Order Execution ==========

    def place_market_order(self, symbol: str, qty: int, side: str) -> Dict[str, Any]:
        """Place market order"""
        return self.broker.place_market_order(symbol, qty, side)

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
            Order details dictionary
        """
        try:
            from alpaca.trading.requests import LimitOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

            order_request = LimitOrderRequest(
                symbol=symbol,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
                limit_price=limit_price
            )

            logger.info(f"Placing limit order: {side.upper()} {qty} {symbol} @ ${limit_price:.2f}")

            order = self.broker._retry_api_call(
                self.broker.trading_client.submit_order,
                order_request
            )

            logger.info(f"Limit order submitted: ID={order.id}, Status={order.status}")

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
            logger.error(f"Failed to place limit order: {e}")
            raise BrokerError(f"Failed to place limit order: {e}")

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status"""
        return self.broker.get_order_status(order_id)

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order

        Args:
            order_id: Order ID to cancel

        Returns:
            True if successfully canceled
        """
        try:
            self.broker._retry_api_call(
                self.broker.trading_client.cancel_order_by_id,
                order_id
            )
            logger.info(f"Order canceled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    # ========== Position Management ==========

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current position for symbol"""
        return self.broker.get_position(symbol)

    def get_all_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions"""
        try:
            positions = self.broker._retry_api_call(
                self.broker.trading_client.get_all_positions
            )

            positions_list = []
            for position in positions:
                positions_list.append({
                    'symbol': position.symbol,
                    'qty': int(position.qty),
                    'avg_entry_price': float(position.avg_entry_price),
                    'current_price': float(position.current_price),
                    'market_value': float(position.market_value),
                    'cost_basis': float(position.cost_basis),
                    'unrealized_pl': float(position.unrealized_pl),
                    'unrealized_plpc': float(position.unrealized_plpc),
                })

            return positions_list

        except Exception as e:
            logger.error(f"Failed to get all positions: {e}")
            raise BrokerError(f"Failed to get all positions: {e}")

    def close_position(self, symbol: str, qty: Optional[int] = None) -> Dict[str, Any]:
        """Close position (sell all or partial)"""
        return self.broker.close_position(symbol, qty)

    # ========== Configuration & Metadata ==========

    def get_tick_size(self, symbol: str, price: float) -> float:
        """
        Get tick size (minimum price increment) for options

        For options:
        - Below $3.00: $0.05 increments
        - $3.00 and above: $0.10 increments

        For stocks: $0.01 increments
        """
        # Check if it's an option symbol (OCC format has specific length/pattern)
        is_option = len(symbol) > 10  # Simple heuristic

        if is_option:
            if price < 3.00:
                return 0.05
            else:
                return 0.10
        else:
            return 0.01

    # Cache for strike increments: {symbol: (increment, timestamp)}
    _strike_increment_cache = {}            # verified (chain-derived) values
    _strike_increment_fallback_cache = {}   # heuristic fallbacks (don't poison long-TTL)
    _STRIKE_CACHE_TTL = 3600                # 1 hour for verified values
    _STRIKE_FALLBACK_TTL = 60               # 60s for heuristic — long enough to dedupe
                                            # within a single user flow, short enough
                                            # to retry the chain query soon after

    # Cache for per-expiration strike lists: {(symbol, exp_iso, opt_type): (strikes, ts)}
    _strikes_cache = {}
    _STRIKES_CACHE_TTL = 300  # 5 min — strike grids don't churn during a session

    def get_strikes_for_dte(self, underlying_symbol: str, dte: int,
                            option_type: str = 'call') -> List[float]:
        """
        Return the ACTUAL sorted list of strike prices the broker lists for
        this underlying at the given DTE + contract type.

        This replaces increment-math everywhere it mattered: instead of
        guessing "MSTR uses $2.50 increments" and synthesizing strikes, we
        ask the broker what strikes actually exist. Solves the case where a
        weekly expiration has a coarser grid ($2.50) than longer-dated ones
        ($1.00), or vice versa — symbol-wide increment detection can't
        capture that, but per-expiration listing does.
        """
        import time as _time
        option_type = (option_type or 'call').lower()
        today = date.today()
        target = today + timedelta(days=max(0, dte))
        cache_key = (underlying_symbol, target.isoformat(), option_type)

        now = _time.time()
        hit = self._strikes_cache.get(cache_key)
        if hit and now - hit[1] < self._STRIKES_CACHE_TTL:
            return hit[0]

        try:
            contracts = self.broker.get_option_contracts(
                underlying_symbol=underlying_symbol,
                dte=dte,
                option_type=option_type,
            )
            strikes = sorted({float(c['strike_price']) for c in contracts})
            if strikes:
                self._strikes_cache[cache_key] = (strikes, now)
                logger.info(
                    "Strikes for %s %s DTE=%d (exp ~%s): %d strikes (range $%.2f-$%.2f)",
                    underlying_symbol, option_type.upper(), dte, target,
                    len(strikes), strikes[0], strikes[-1],
                )
            else:
                logger.warning(
                    "No strikes returned for %s %s DTE=%d", underlying_symbol, option_type, dte
                )
            return strikes
        except Exception as e:
            logger.error("get_strikes_for_dte failed for %s DTE=%d: %s",
                         underlying_symbol, dte, e)
            return []

    def get_strike_increment(self, underlying_symbol: str, price: float) -> float:
        """
        Get strike price increment for options.

        Primary: derives from live option chain data near ATM.
        Fallback: hardcoded heuristics if API call fails.

        Cache strategy (added in v0.1.8 to prevent fallback poisoning):
          - "verified" cache: only chain-derived values, 1 hour TTL.
            These are trustworthy and stable per symbol.
          - "fallback" cache: heuristic guesses, 60 second TTL.
            If the chain query fails on first load and we cache a bad
            heuristic for 1 hour, every order for that symbol gets a wrong
            strike for the rest of the hour. The short TTL means a transient
            API failure self-heals on the next request instead of poisoning.
        """
        import time as _time
        from collections import Counter

        now = _time.time()

        # Prefer verified — it's the long-TTL trustworthy bucket.
        verified = self._strike_increment_cache.get(underlying_symbol)
        if verified:
            increment, cached_at = verified
            if now - cached_at < self._STRIKE_CACHE_TTL:
                return increment

        # Fall through to short-TTL fallback bucket (only used when verified is stale).
        fallback = self._strike_increment_fallback_cache.get(underlying_symbol)
        if fallback:
            increment, cached_at = fallback
            if now - cached_at < self._STRIKE_FALLBACK_TTL:
                return increment

        try:
            # Query contracts near ATM, next 14 days
            atm_range = 20.0
            today = date.today()
            end_date = today + timedelta(days=14)

            option_chain = self.get_option_chain(
                symbol=underlying_symbol,
                start_date=today.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d')
            )

            if not option_chain:
                raise ValueError("No option chain data")

            # Collect strikes from contracts near ATM
            strikes_by_exp = {}
            for contract in option_chain:
                exp = contract.get('expiration_date')
                sym = contract.get('symbol', '')
                # Filter to calls only (avoid double-counting puts)
                if 'C' not in sym.upper():
                    continue
                # Extract strike from OCC symbol (last 8 chars = price * 1000)
                try:
                    strike = int(sym[-8:]) / 1000.0
                except (ValueError, IndexError):
                    continue
                # Only near ATM
                if abs(strike - price) <= atm_range:
                    if exp not in strikes_by_exp:
                        strikes_by_exp[exp] = set()
                    strikes_by_exp[exp].add(strike)

            # Pick expiration with most strikes near ATM
            if not strikes_by_exp:
                raise ValueError("No strikes found near ATM")

            best_exp = max(strikes_by_exp, key=lambda e: len(strikes_by_exp[e]))
            strikes = sorted(strikes_by_exp[best_exp])

            if len(strikes) < 2:
                raise ValueError("Not enough strikes to compute increment")

            # Compute increment ONLY from strikes IMMEDIATELY adjacent to ATM.
            # The old algorithm widened to ±$20 from ATM and picked min — but
            # chains often have $1 strikes at deep ITM/OTM (for hedging) AND
            # $2.5 strikes near ATM. Picking min returns $1 even though the
            # right "where to actually trade" increment is $2.5. For MSTR at
            # $161 the widened range had 9× $1 increments and 12× $2.5; the
            # old algorithm picked $1, leading to strikes like $161 that
            # don't exist (real chain has $160 and $162.5).
            #
            # New algorithm: find the strike closest to ATM, take 4 neighbors
            # on each side (9-strike window), compute adjacent diffs in that
            # window only, and pick the mode (most common). This is what
            # actual trading platforms do for "find the ATM increment."
            closest_idx = min(range(len(strikes)), key=lambda i: abs(strikes[i] - price))
            lo = max(0, closest_idx - 4)
            hi = min(len(strikes), closest_idx + 5)
            atm_window = strikes[lo:hi]

            increments = []
            for i in range(1, len(atm_window)):
                diff = round(atm_window[i] - atm_window[i - 1], 2)
                if diff > 0:
                    increments.append(diff)

            if not increments:
                raise ValueError("No valid increments in ATM window")

            # Use the MOST COMMON increment in the ATM window (mode), not min.
            # If the window happens to span an increment boundary (e.g. $1 wing
            # transitioning to $2.5 near ATM), mode still picks the dominant
            # value at ATM rather than the smaller wing value.
            counter = Counter(increments)
            result = counter.most_common(1)[0][0]
            logger.info(
                "Strike increment for %s near $%.2f: $%s (from ATM window %s, diffs %s)",
                underlying_symbol, price, result, atm_window, dict(counter),
            )

            # Cache it
            self._strike_increment_cache[underlying_symbol] = (result, _time.time())
            logger.info(f"Detected strike increment for {underlying_symbol}: ${result}")
            return result

        except Exception as e:
            logger.warning(
                "Could not detect strike increment for %s: %s, using heuristic fallback",
                underlying_symbol, e,
            )
            # Fallback heuristics — cached briefly so we retry the real chain
            # query soon. Caching the heuristic for 1 hour (the previous bug)
            # made a single chain-query failure poison the symbol for an hour.
            if underlying_symbol in ['SPY', 'QQQ', 'IWM', 'DIA']:
                fallback_val = 1.0
            elif price > 200:
                fallback_val = 5.0
            elif price > 100:
                fallback_val = 2.5
            else:
                fallback_val = 1.0
            self._strike_increment_fallback_cache[underlying_symbol] = (fallback_val, _time.time())
            return fallback_val

    def validate_connection(self) -> Tuple[bool, str]:
        """
        Validate broker connection and credentials

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            account = self.broker.trading_client.get_account()

            if account.trading_blocked:
                return False, "Trading is blocked on this account"

            if account.account_blocked:
                return False, "Account is blocked"

            return True, f"Connection valid. Account: {account.account_number}"

        except Exception as e:
            return False, f"Connection failed: {str(e)}"

    def __repr__(self) -> str:
        """String representation"""
        return f"AlpacaBroker(paper={self.paper}, feed={self.data_feed})"
