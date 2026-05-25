"""
Tradier broker adapter.

API conventions sourced from https://docs.tradier.com/ (May 2026).

Auth model:
  - Tradier issues SEPARATE bearer tokens for sandbox (paper) and production (live).
    A sandbox token will not authenticate against api.tradier.com and vice versa.
  - The user must also supply the account_id (e.g. "VA00000000") because a token
    can scope to multiple accounts.

Base URLs:
  - paper: https://sandbox.tradier.com/v1
  - live:  https://api.tradier.com/v1

Response quirks:
  - Tradier wraps every payload in a typed outer key, e.g. `{"quotes": {"quote": [...]}}`.
  - When a *list* contains only one item, Tradier often UNWRAPS it to a single object
    instead of returning a 1-element array. The `_as_list()` helper below normalizes.
  - Errors come back as `{"errors": {"error": ["msg", ...]}}` with a non-200 status,
    but a 200 with `errors` is also possible in practice; handled by `_request()`.

Option symbol format is OCC (same as Alpaca), e.g. `SPY240315C00450000`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests

from .broker_interface import BrokerInterface

logger = logging.getLogger(__name__)

PAPER_BASE = "https://sandbox.tradier.com/v1"
LIVE_BASE = "https://api.tradier.com/v1"

# Map our internal timeframe strings (Alpaca-style) to Tradier's interval values.
# Tradier splits intraday (timesales endpoint) vs >=daily (history endpoint).
_INTRADAY = {"1Min": "1min", "5Min": "5min", "15Min": "15min"}
_DAILY = {"1Day": "daily", "1Week": "weekly", "1Month": "monthly"}


class TradierError(RuntimeError):
    """Raised when Tradier returns a structured error."""


class TradierBroker(BrokerInterface):
    """Tradier implementation of BrokerInterface."""

    # ---------- construction ----------

    def __init__(
        self,
        access_token: str,
        account_id: str,
        paper: bool = True,
        **kwargs,
    ):
        if not access_token:
            raise ValueError("Tradier access_token is required")
        if not account_id:
            raise ValueError("Tradier account_id is required (e.g. 'VA00000000')")

        self.access_token = access_token
        self.account_id = account_id
        self.paper = paper
        self.base = PAPER_BASE if paper else LIVE_BASE

        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        })
        # Reasonable network defaults.
        self._timeout = float(kwargs.get("timeout", 15.0))

        logger.info("TradierBroker initialized (paper=%s, account=%s)", paper, account_id)

    @classmethod
    def from_credentials(cls, mode: str, access_token: str, account_id: str, **extra) -> "TradierBroker":
        """Factory entry point used by broker_factory.build_broker."""
        return cls(
            access_token=access_token,
            account_id=account_id,
            paper=(mode == "paper"),
            **extra,
        )

    # ---------- low-level helpers ----------

    def _request(self, method: str, path: str, *,
                 params: Optional[Dict[str, Any]] = None,
                 data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        try:
            resp = self._session.request(method, url, params=params, data=data, timeout=self._timeout)
        except requests.RequestException as e:
            raise TradierError(f"Network error talking to Tradier: {e}") from e

        # Tradier can return JSON-shaped errors at any status; try to parse first.
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            body = {}

        if not resp.ok:
            err = self._extract_error(body) or f"HTTP {resp.status_code}: {resp.text[:200]}"
            raise TradierError(err)

        # Some endpoints return 200 with a body-level error.
        if isinstance(body, dict) and "errors" in body:
            raise TradierError(self._extract_error(body) or "Unknown Tradier error")

        return body or {}

    @staticmethod
    def _extract_error(body: Any) -> Optional[str]:
        try:
            errs = body.get("errors", {}).get("error")
            if isinstance(errs, list):
                return "; ".join(str(e) for e in errs)
            if isinstance(errs, str):
                return errs
        except AttributeError:
            pass
        return None

    @staticmethod
    def _as_list(obj: Any) -> List[Any]:
        """Tradier unwraps single-element arrays. Normalize to always-a-list."""
        if obj is None:
            return []
        if isinstance(obj, list):
            return obj
        return [obj]

    # ---------- BrokerInterface: account ----------

    def validate_connection(self) -> Tuple[bool, str]:
        try:
            body = self._request("GET", "/user/profile")
            accounts = self._as_list(body.get("profile", {}).get("account"))
            numbers = [a.get("account_number") for a in accounts]
            if not numbers:
                return False, "Profile returned no accounts for this token."
            if self.account_id not in numbers:
                return False, (
                    f"account_id {self.account_id!r} not found in this token's profile. "
                    f"Accounts available: {', '.join(numbers)}"
                )
            return True, f"Connection valid. Account: {self.account_id}"
        except TradierError as e:
            return False, str(e)

    def get_account_info(self) -> Dict[str, Any]:
        body = self._request("GET", f"/accounts/{self.account_id}/balances")
        bal = body.get("balances", {}) or {}
        # Tradier reports buying power under margin.option_buying_power, cash.cash_available,
        # or pdt.option_buying_power depending on account type. Pick the highest-fidelity field
        # available, falling back gracefully.
        margin = bal.get("margin") or {}
        cash_block = bal.get("cash") or {}
        pdt = bal.get("pdt") or {}

        option_bp = (
            margin.get("option_buying_power")
            or pdt.get("option_buying_power")
            or cash_block.get("cash_available")
            or bal.get("total_cash")
            or 0.0
        )

        return {
            "account_number": bal.get("account_number", self.account_id),
            "status": "ACTIVE" if bal else "UNKNOWN",
            "buying_power": float(option_bp or 0.0),
            "cash": float(bal.get("total_cash", 0.0) or 0.0),
            "portfolio_value": float(bal.get("total_equity", 0.0) or 0.0),
            "pattern_day_trader": "pdt" in bal,
            "trading_blocked": False,   # Tradier exposes no equivalent; default False.
            "account_blocked": False,
            # Tradier-specific extras kept under non-standard keys for the popover.
            "account_type": bal.get("account_type"),
        }

    # ---------- BrokerInterface: market data ----------

    def get_current_price(self, symbol: str) -> float:
        body = self._request("GET", "/markets/quotes", params={"symbols": symbol})
        quotes = self._as_list(body.get("quotes", {}).get("quote"))
        if not quotes:
            raise TradierError(f"No quote returned for {symbol!r}")
        q = quotes[0]
        # Prefer last; fall back to mid; fall back to close.
        last = q.get("last") or q.get("close")
        bid, ask = q.get("bid"), q.get("ask")
        if last is None and bid is not None and ask is not None:
            last = (float(bid) + float(ask)) / 2.0
        if last is None:
            raise TradierError(f"Quote for {symbol!r} has no price field")
        return float(last)

    def get_historical_bars(self, symbol: str, timeframe: str,
                            start: Optional[str] = None,
                            end: Optional[str] = None,
                            limit: int = 1000) -> List[Dict[str, Any]]:
        """Tradier splits intraday vs daily across two endpoints; we hide the seam."""
        if timeframe in _INTRADAY:
            return self._intraday_bars(symbol, _INTRADAY[timeframe], start, end, limit)
        if timeframe in _DAILY:
            return self._daily_bars(symbol, _DAILY[timeframe], start, end, limit)
        # Be permissive — accept Tradier's own strings too.
        if timeframe in ("1min", "5min", "15min"):
            return self._intraday_bars(symbol, timeframe, start, end, limit)
        if timeframe in ("daily", "weekly", "monthly"):
            return self._daily_bars(symbol, timeframe, start, end, limit)
        raise ValueError(f"Unsupported timeframe for Tradier: {timeframe!r}")

    def _intraday_bars(self, symbol, interval, start, end, limit):
        params = {"symbol": symbol, "interval": interval, "session_filter": "open"}
        if start: params["start"] = self._fmt_intraday_dt(start)
        if end:   params["end"]   = self._fmt_intraday_dt(end)
        body = self._request("GET", "/markets/timesales", params=params)
        rows = self._as_list(body.get("series", {}).get("data"))
        bars = []
        for r in rows[-limit:]:
            ts = self._parse_intraday_time(r.get("time"))
            bars.append({
                "time": ts,
                "open": float(r.get("open", 0.0)),
                "high": float(r.get("high", 0.0)),
                "low":  float(r.get("low", 0.0)),
                "close": float(r.get("close", 0.0)),
                "volume": int(r.get("volume", 0) or 0),
            })
        return bars

    def _daily_bars(self, symbol, interval, start, end, limit):
        params = {"symbol": symbol, "interval": interval}
        if start: params["start"] = start[:10]
        if end:   params["end"]   = end[:10]
        body = self._request("GET", "/markets/history", params=params)
        rows = self._as_list(body.get("history", {}).get("day"))
        bars = []
        for r in rows[-limit:]:
            d = r.get("date")
            ts = int(datetime.fromisoformat(d).replace(tzinfo=timezone.utc).timestamp())
            bars.append({
                "time": ts,
                "open": float(r.get("open", 0.0)),
                "high": float(r.get("high", 0.0)),
                "low":  float(r.get("low", 0.0)),
                "close": float(r.get("close", 0.0)),
                "volume": int(r.get("volume", 0) or 0),
            })
        return bars

    @staticmethod
    def _fmt_intraday_dt(s: str) -> str:
        # Tradier timesales takes "YYYY-MM-DD HH:MM". Accept ISO and normalize.
        if "T" in s:
            return s.replace("T", " ")[:16]
        return s[:16]

    @staticmethod
    def _parse_intraday_time(s: str) -> int:
        # "2021-02-01 09:30:00" → unix timestamp (ET local; Tradier returns it that way).
        # We treat as UTC for charting consistency — Lightweight Charts re-renders by zone.
        return int(datetime.fromisoformat(s.replace(" ", "T")).replace(tzinfo=timezone.utc).timestamp())

    # ---------- BrokerInterface: options ----------

    def get_available_expirations(self, underlying_symbol: str,
                                   min_dte: int = 0,
                                   max_dte: int = 365) -> List[Dict[str, Any]]:
        body = self._request(
            "GET", "/markets/options/expirations",
            params={"symbol": underlying_symbol, "includeAllRoots": "true"},
        )
        # Basic shape: {"expirations": {"date": ["YYYY-MM-DD", ...]}}.
        # When strikes=true the shape is {"expirations": {"expiration": [{date,...}]}}.
        block = body.get("expirations") or {}
        dates: List[str] = []
        if isinstance(block.get("date"), (list, str)):
            dates = self._as_list(block["date"])
        elif isinstance(block.get("expiration"), (list, dict)):
            for x in self._as_list(block["expiration"]):
                if x.get("date"): dates.append(x["date"])

        today = date.today()
        out = []
        for d in dates:
            try:
                exp = date.fromisoformat(d)
            except ValueError:
                continue
            dte = (exp - today).days
            if dte < min_dte or dte > max_dte:
                continue
            out.append({
                "expiration_date": exp,
                "dte": dte,
                # 3rd Friday rule — same heuristic as the rest of the codebase.
                "is_monthly": exp.weekday() == 4 and 15 <= exp.day <= 21,
            })
        out.sort(key=lambda x: x["expiration_date"])
        return out

    def get_option_contracts(self, underlying_symbol: str,
                              dte: Optional[int] = None,
                              expiration_date: Optional[date] = None,
                              option_type: Optional[str] = None,
                              strike_price: Optional[float] = None) -> List[Dict[str, Any]]:
        # Tradier's chain endpoint requires an exact expiration date.
        if expiration_date is None:
            if dte is None:
                raise ValueError("Tradier requires either expiration_date or dte")
            expirations = self.get_available_expirations(underlying_symbol)
            if not expirations:
                return []
            # Find the closest expiration >= requested dte.
            picked = next((e for e in expirations if e["dte"] >= dte), expirations[-1])
            expiration_date = picked["expiration_date"]

        body = self._request(
            "GET", "/markets/options/chains",
            params={
                "symbol": underlying_symbol,
                "expiration": expiration_date.isoformat(),
                "greeks": "false",
            },
        )
        options = self._as_list(body.get("options", {}).get("option"))

        out = []
        for o in options:
            t = (o.get("option_type") or "").lower()
            if option_type and t != option_type.lower():
                continue
            if strike_price is not None and float(o.get("strike", 0.0)) != float(strike_price):
                continue
            out.append({
                "symbol": o.get("symbol"),
                "underlying_symbol": o.get("underlying") or underlying_symbol,
                "strike_price": float(o.get("strike", 0.0)),
                "expiration_date": date.fromisoformat(o.get("expiration_date")),
                "type": t,
                "style": "american",  # All US equity options
                "size": int(o.get("contract_size", 100)),
            })
        return out

    def get_option_quote(self, option_symbol: str) -> Dict[str, float]:
        body = self._request(
            "GET", "/markets/quotes",
            params={"symbols": option_symbol, "greeks": "true"},
        )
        quotes = self._as_list(body.get("quotes", {}).get("quote"))
        if not quotes:
            raise TradierError(f"No quote for option {option_symbol!r}")
        q = quotes[0]
        bid = float(q.get("bid") or 0.0)
        ask = float(q.get("ask") or 0.0)
        mid = (bid + ask) / 2.0 if (bid and ask) else (bid or ask or float(q.get("last") or 0.0))
        g = q.get("greeks") or {}
        return {
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "spread": ask - bid if (ask and bid) else 0.0,
            "iv": float(g.get("mid_iv") or 0.0),
            "delta": float(g.get("delta") or 0.0),
            "gamma": float(g.get("gamma") or 0.0),
            "theta": float(g.get("theta") or 0.0),
            "vega":  float(g.get("vega") or 0.0),
            "last":  float(q.get("last") or 0.0),
            "volume": int(q.get("volume", 0) or 0),
            "open_interest": int(q.get("open_interest", 0) or 0),
        }

    def get_atm_strike(self, underlying_symbol: str, current_price: float) -> float:
        increment = self.get_strike_increment(underlying_symbol, current_price)
        return round(current_price / increment) * increment

    # ---------- BrokerInterface: orders ----------

    def place_market_order(self, symbol: str, qty: int, side: str) -> Dict[str, Any]:
        return self._place_order(symbol=symbol, qty=qty, side=side, order_type="market")

    def place_limit_order(self, symbol: str, qty: int, side: str,
                          limit_price: float) -> Dict[str, Any]:
        return self._place_order(symbol=symbol, qty=qty, side=side,
                                 order_type="limit", price=limit_price)

    def _place_order(self, *, symbol: str, qty: int, side: str,
                     order_type: str, price: Optional[float] = None,
                     duration: str = "day") -> Dict[str, Any]:
        is_option = self._looks_like_option_symbol(symbol)
        form: Dict[str, Any] = {
            "class": "option" if is_option else "equity",
            "side": self._map_side(side, is_option),
            "quantity": int(qty),
            "type": order_type,
            "duration": duration,
        }
        if is_option:
            form["symbol"] = self._underlying_from_option(symbol)
            form["option_symbol"] = symbol
        else:
            form["symbol"] = symbol
        if order_type in ("limit", "stop_limit") and price is not None:
            form["price"] = f"{float(price):.2f}"

        body = self._request("POST", f"/accounts/{self.account_id}/orders", data=form)
        o = body.get("order") or {}
        return {
            "order_id": str(o.get("id", "")),
            "symbol": symbol,
            "qty": int(qty),
            "side": side,
            "type": order_type,
            "status": o.get("status", "pending"),
            "submitted_at": datetime.now(timezone.utc),
            "filled_avg_price": None,
        }

    @staticmethod
    def _map_side(side: str, is_option: bool) -> str:
        """Map our generic side ('buy'/'sell') to Tradier's option-specific verbs.

        For options Tradier requires buy_to_open / sell_to_close / etc. The trading
        engine only ever asks us for 'buy' (entering a long premium position) or
        'sell' (closing it), so we map:
            buy  → buy_to_open
            sell → sell_to_close
        Anyone needing buy_to_close / sell_to_open can pass those strings directly.
        """
        side = side.lower().strip()
        if side in ("buy_to_open", "buy_to_close", "sell_to_open", "sell_to_close",
                    "buy", "sell", "sell_short", "buy_to_cover"):
            if is_option:
                if side == "buy":  return "buy_to_open"
                if side == "sell": return "sell_to_close"
            else:
                if side in ("buy_to_open", "buy_to_close"): return "buy"
                if side in ("sell_to_open", "sell_to_close"): return "sell"
            return side
        raise ValueError(f"Unknown side: {side!r}")

    def get_order_status(self, order_id: str) -> Dict[str, Any]:
        body = self._request("GET", f"/accounts/{self.account_id}/orders/{order_id}")
        o = body.get("order") or {}
        return {
            "order_id": str(o.get("id", order_id)),
            "status": o.get("status", "unknown"),
            "filled_qty": int(float(o.get("exec_quantity", 0) or 0)),
            "filled_avg_price": float(o["avg_fill_price"]) if o.get("avg_fill_price") else None,
            "filled_at": self._parse_iso(o.get("transaction_date")),
        }

    def cancel_order(self, order_id: str) -> bool:
        try:
            self._request("DELETE", f"/accounts/{self.account_id}/orders/{order_id}")
            return True
        except TradierError as e:
            logger.warning("Cancel order %s failed: %s", order_id, e)
            return False

    # ---------- BrokerInterface: positions ----------

    def get_position(self, symbol: str) -> Optional[Dict[str, Any]]:
        for p in self.get_all_positions():
            if p["symbol"] == symbol:
                return p
        return None

    def get_all_positions(self) -> List[Dict[str, Any]]:
        body = self._request("GET", f"/accounts/{self.account_id}/positions")
        # When no positions, Tradier returns "null" — handle that.
        block = body.get("positions")
        if block in (None, "null", ""):
            return []
        rows = self._as_list(block.get("position"))

        # Tradier doesn't include current_price / unrealized_pl. Enrich with one
        # batched quote call so the trading UI has what it needs.
        symbols = [r["symbol"] for r in rows if r.get("symbol")]
        prices = self._batch_prices(symbols) if symbols else {}

        out = []
        for r in rows:
            sym = r["symbol"]
            qty = float(r.get("quantity", 0))
            cost_basis = float(r.get("cost_basis", 0))
            avg_entry = (cost_basis / qty) if qty else 0.0
            current_price = prices.get(sym, 0.0)
            # Options report cost basis in dollars (i.e. premium * 100 * qty already), so
            # for option positions current_price needs the 100x multiplier when computing
            # market value.
            is_opt = self._looks_like_option_symbol(sym)
            multiplier = 100.0 if is_opt else 1.0
            market_value = current_price * qty * multiplier
            unrealized = market_value - cost_basis
            out.append({
                "symbol": sym,
                "qty": int(qty),
                "avg_entry_price": avg_entry / multiplier if avg_entry else 0.0,
                "current_price": current_price,
                "market_value": market_value,
                "cost_basis": cost_basis,
                "unrealized_pl": unrealized,
                "unrealized_plpc": (unrealized / cost_basis) if cost_basis else 0.0,
            })
        return out

    def close_position(self, symbol: str, qty: Optional[int] = None) -> Dict[str, Any]:
        pos = self.get_position(symbol)
        if pos is None:
            raise TradierError(f"No open position to close: {symbol}")
        close_qty = qty if qty is not None else abs(int(pos["qty"]))
        side = "sell_to_close" if self._looks_like_option_symbol(symbol) else "sell"
        return self.place_market_order(symbol=symbol, qty=close_qty, side=side)

    def _batch_prices(self, symbols: List[str]) -> Dict[str, float]:
        if not symbols:
            return {}
        body = self._request("GET", "/markets/quotes", params={"symbols": ",".join(symbols)})
        out: Dict[str, float] = {}
        for q in self._as_list(body.get("quotes", {}).get("quote")):
            sym = q.get("symbol")
            if not sym:
                continue
            last = q.get("last") or q.get("close") or 0.0
            try:
                out[sym] = float(last)
            except (TypeError, ValueError):
                out[sym] = 0.0
        return out

    # ---------- BrokerInterface: tick / strike sizing ----------

    def get_tick_size(self, symbol: str, price: float) -> float:
        # Standard US options ticks. Equities are penny-tick.
        if self._looks_like_option_symbol(symbol):
            return 0.05 if price < 3.0 else 0.10
        return 0.01

    def get_strike_increment(self, underlying_symbol: str, price: float) -> float:
        # Conservative heuristic — matches what AlpacaBroker uses elsewhere in
        # the codebase. Real strike grids come from the actual chain; this is
        # only a fallback for ATM rounding before chain inspection.
        if price < 25:    return 0.5
        if price < 200:   return 1.0
        if price < 1000:  return 5.0
        return 10.0

    # ---------- utilities ----------

    @staticmethod
    def _looks_like_option_symbol(symbol: str) -> bool:
        # OCC: <root><YYMMDD><C|P><strike*1000 padded to 8>. Root is 1-6 chars.
        # Distinguishing test: at least 15 chars and a 'C' or 'P' followed by 8 digits.
        if not symbol or len(symbol) < 15:
            return False
        # Walk from the end: last 8 digits = strike, preceded by C/P.
        if not symbol[-8:].isdigit():
            return False
        return symbol[-9] in ("C", "P")

    @staticmethod
    def _underlying_from_option(option_symbol: str) -> str:
        # Strip OCC suffix: <YYMMDD><C|P><8-digit strike> = 15 chars.
        return option_symbol[:-15]

    @staticmethod
    def _parse_iso(s: Optional[str]):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None

    def __repr__(self) -> str:
        return f"TradierBroker(paper={self.paper}, account={self.account_id})"
