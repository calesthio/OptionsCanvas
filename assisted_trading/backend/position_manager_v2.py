"""
Position Manager V2 - Database-backed position tracking
Uses broker as source of truth, database for metadata
"""

import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import pytz

from .database.db_manager import DatabaseManager
from .state_machine import InvariantValidator

logger = logging.getLogger(__name__)


class PositionManagerV2:
    """
    Manages positions using SQLite database
    Broker is the source of truth for what exists
    Database stores metadata (SL/TP, entry times, etc.)
    """

    def __init__(self, config: Dict, timezone: pytz.timezone, db_manager: DatabaseManager):
        """
        Initialize position manager

        Args:
            config: Assisted trading configuration
            timezone: Timezone for timestamps
            db_manager: Database manager instance
        """
        self.config = config
        self.timezone = timezone
        self.db = db_manager

        logger.info("PositionManagerV2 initialized with database backend")

        # One-shot backfill: if journal_entries is empty but position_closes has
        # rows, populate it. This catches up databases written by earlier code
        # paths that never wrote to journal_entries (the table schema existed
        # but no production code called update_journal_entry).
        try:
            self._backfill_daily_aggregates_if_empty()
        except Exception as e:
            # Backfill is a nice-to-have; never let it block boot.
            logger.warning("journal_entries backfill skipped: %s", e)

    def _backfill_daily_aggregates_if_empty(self) -> None:
        """If journal_entries has no rows but position_closes does, recompute
        and persist daily aggregates for every date in position_closes."""
        existing = self.db.execute_query("SELECT COUNT(*) AS n FROM journal_entries")
        if existing and existing[0].get('n', 0) > 0:
            return  # already populated

        dates = self.db.execute_query(
            "SELECT DISTINCT substr(exit_time, 1, 10) AS d FROM position_closes ORDER BY d"
        )
        if not dates:
            return  # no trades to backfill

        for row in dates:
            d = row.get('d')
            if not d:
                continue
            self._record_daily_aggregate_for_date(d)

        logger.info("journal_entries backfill: aggregated %d day(s) from position_closes", len(dates))

    def _record_daily_aggregate_for_date(self, date_str: str) -> None:
        """Compute today's summary from position_closes and upsert into journal_entries.
        Cheap (one aggregate query, one row write) so we call it after every close —
        keeps journal_entries in sync as a side-effect of trading."""
        summary = self.get_daily_summary(date_str)
        # update_journal_entry takes date separately; strip it from the value dict.
        summary.pop('date', None)
        self.db.update_journal_entry(date_str, summary)

    # ========== Position Operations ==========

    def open_position(self, option_symbol: str, symbol: str, contract_type: str,
                     strike: float, dte: int, total_contracts: int,
                     entry_price: float, underlying_entry_price: float,
                     stop_loss_price: Optional[float] = None,
                     take_profit_price: Optional[float] = None,
                     source_order_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Record a new position opening

        Args:
            option_symbol: Option contract symbol
            symbol: Underlying symbol
            contract_type: CALL or PUT
            strike: Strike price
            dte: Days to expiration
            total_contracts: Number of contracts
            entry_price: Entry price per share
            underlying_entry_price: Underlying price at entry
            stop_loss_price: Stop loss price (optional)
            take_profit_price: Take profit price (optional)
            source_order_id: Order ID that created this position (optional)

        Returns:
            Position data dictionary
        """
        entry_time = datetime.now(self.timezone).isoformat()

        position_data = {
            'option_symbol': option_symbol,
            'symbol': symbol,
            'contract_type': contract_type,
            'strike': strike,
            'dte': dte,
            'total_contracts': total_contracts,
            'remaining_contracts': total_contracts,
            'entry_price': entry_price,
            'entry_time': entry_time,
            'underlying_entry_price': underlying_entry_price,
            'stop_loss_price': stop_loss_price,
            'take_profit_price': take_profit_price,
            'is_tracked': True,
            'source_order_id': source_order_id
        }

        # Enforce invariants before persisting — catches schema-mismatched
        # writes early instead of letting bad rows sit in the DB.
        InvariantValidator.check_and_log_violation(
            'position(open)',
            {**position_data, 'status': 'open'},
            InvariantValidator.validate_position_invariants,
        )

        self.db.create_position(position_data)

        logger.info(f"Position opened: {option_symbol} - {total_contracts} contracts @ ${entry_price:.2f}")

        return position_data

    def add_to_position(self, option_symbol: str, additional_contracts: int,
                       new_entry_price: float, new_underlying_price: float) -> Dict[str, Any]:
        """
        Add contracts to an existing position (position accumulation)
        Calculates weighted average entry price

        Args:
            option_symbol: Option contract symbol
            additional_contracts: Number of contracts to add
            new_entry_price: Entry price per share for new contracts
            new_underlying_price: Underlying price for new contracts

        Returns:
            Updated position data dictionary
        """
        # Get existing position
        existing_position = self.get_position(option_symbol)
        if not existing_position:
            raise ValueError(f"Cannot add to position - position does not exist: {option_symbol}")

        # Calculate weighted average entry price
        # IMPORTANT: weight by REMAINING contracts (cost basis of what we actually
        # hold), not lifetime total. After a partial close + add-on the basis
        # should reflect only the contracts still on the books — matches how
        # mainstream brokers (IB / Schwab / RH) compute it.
        old_total = existing_position['total_contracts']
        old_remaining = existing_position['remaining_contracts']
        old_price = existing_position['entry_price']

        new_total = old_total + additional_contracts
        new_remaining = old_remaining + additional_contracts

        # Weighted average over the basis of the contracts we currently hold.
        # `total_contracts` remains a lifetime accumulator for audit only.
        weighted_avg_price = (
            ((old_remaining * old_price) + (additional_contracts * new_entry_price))
            / new_remaining
        )

        # Update position data
        updated_data = {
            'total_contracts': new_total,
            'remaining_contracts': new_remaining,
            'entry_price': weighted_avg_price,
            'underlying_entry_price': new_underlying_price  # Update to latest underlying price
        }

        # Update in database
        self.db.update_position(option_symbol, updated_data)

        logger.info(f"Added to position: {option_symbol} - Added {additional_contracts} contracts @ ${new_entry_price:.2f}")
        logger.info(f"  Previous: {old_total} contracts @ ${old_price:.2f}")
        logger.info(f"  New total: {new_total} contracts @ ${weighted_avg_price:.2f} (weighted avg)")

        # Return updated position
        return self.get_position(option_symbol)

    def get_position(self, option_symbol: str) -> Optional[Dict[str, Any]]:
        """Get position by option symbol"""
        return self.db.get_position(option_symbol)

    def get_all_positions(self) -> List[Dict[str, Any]]:
        """Get all open positions from database"""
        return self.db.get_all_positions()

    def has_position(self, option_symbol: str) -> bool:
        """Check if position exists"""
        position = self.db.get_position(option_symbol)
        return position is not None and position['remaining_contracts'] > 0

    def has_any_position(self) -> bool:
        """Check if any positions exist"""
        positions = self.db.get_all_positions()
        return len(positions) > 0

    def close_position(self, option_symbol: str, contracts_closed: int,
                      exit_price: float) -> Dict[str, Any]:
        """
        Record position close (full or partial)

        Args:
            option_symbol: Option symbol
            contracts_closed: Number of contracts closed
            exit_price: Exit price per share

        Returns:
            Close record dictionary
        """
        position = self.db.get_position(option_symbol)
        if not position:
            raise ValueError(f"Position not found: {option_symbol}")

        if contracts_closed > position['remaining_contracts']:
            raise ValueError(
                f"Cannot close {contracts_closed} contracts, only {position['remaining_contracts']} remaining"
            )

        exit_time = datetime.now(self.timezone).isoformat()

        # Calculate realized P&L for this close
        entry_value = contracts_closed * position['entry_price'] * 100
        exit_value = contracts_closed * exit_price * 100
        close_pnl = exit_value - entry_value

        # Record the close
        close_data = {
            'option_symbol': option_symbol,
            'contracts_closed': contracts_closed,
            'exit_price': exit_price,
            'exit_time': exit_time,
            'realized_pnl': close_pnl
        }
        self.db.record_position_close(close_data)

        # Refresh the daily aggregate row in journal_entries so dashboards /
        # /api/journal see today's stats immediately. Best-effort: a failure
        # here must NOT block the close from being recorded.
        try:
            if isinstance(exit_time, str) and len(exit_time) >= 10:
                self._record_daily_aggregate_for_date(exit_time[:10])
        except Exception as e:
            logger.warning("journal_entries refresh failed for %s: %s", exit_time, e)

        # Update position
        new_remaining = position['remaining_contracts'] - contracts_closed
        new_realized_pnl = position.get('realized_pnl', 0.0) + close_pnl

        self.db.update_position(option_symbol, {
            'remaining_contracts': new_remaining,
            'realized_pnl': new_realized_pnl
        })

        # Invariant check on the post-update view (skip if we're about to delete).
        if new_remaining > 0:
            InvariantValidator.check_and_log_violation(
                'position(close-partial)',
                {**position, 'remaining_contracts': new_remaining, 'realized_pnl': new_realized_pnl, 'status': 'open'},
                InvariantValidator.validate_position_invariants,
            )

        logger.info(
            f"Position closed: {option_symbol} - {contracts_closed} contracts @ ${exit_price:.2f}, "
            f"P&L: ${close_pnl:.2f}"
        )

        # If fully closed, delete position record
        if new_remaining == 0:
            self.delete_position(option_symbol)
            logger.info(f"Position fully closed and removed: {option_symbol}")

        return close_data

    def delete_position(self, option_symbol: str):
        """Delete position record (when fully closed or stale)"""
        self.db.delete_position(option_symbol)
        logger.info(f"Position deleted: {option_symbol}")

    def update_stop_loss(self, option_symbol: str, stop_loss_price: float):
        """Update stop loss for position"""
        self.db.update_position(option_symbol, {'stop_loss_price': stop_loss_price})
        logger.info(f"Stop loss updated for {option_symbol}: ${stop_loss_price:.2f}")

    def update_take_profit(self, option_symbol: str, take_profit_price: float):
        """Update take profit for position"""
        self.db.update_position(option_symbol, {'take_profit_price': take_profit_price})
        logger.info(f"Take profit updated for {option_symbol}: ${take_profit_price:.2f}")

    # ========== Broker Reconciliation ==========

    def reconcile_with_broker(self, broker_positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Reconcile database positions with broker positions
        Broker is the source of truth - remove positions not in broker

        Args:
            broker_positions: List of positions from broker

        Returns:
            Reconciliation summary
        """
        broker_symbols = {pos['symbol'] for pos in broker_positions}
        db_positions = self.db.get_all_positions()

        removed = []
        added = []

        # Remove positions not in broker
        for db_pos in db_positions:
            if db_pos['option_symbol'] not in broker_symbols:
                logger.info(f"Removing stale position {db_pos['option_symbol']} - not in broker")
                self.delete_position(db_pos['option_symbol'])
                removed.append(db_pos['option_symbol'])

        # Add external broker positions (not tracked in our DB)
        db_symbols = {pos['option_symbol'] for pos in db_positions}
        for broker_pos in broker_positions:
            if broker_pos['symbol'] not in db_symbols:
                logger.info(f"Found external broker position: {broker_pos['symbol']}")
                added.append(broker_pos['symbol'])

        return {
            'removed': removed,
            'added': added,
            'removed_count': len(removed),
            'added_count': len(added)
        }

    # ========== Position Limits ==========

    def can_open_new_position(self, symbol: str) -> tuple[bool, str]:
        """
        Check if can open new position based on limits

        Args:
            symbol: Underlying symbol

        Returns:
            (allowed, reason)
        """
        positions = self.db.get_all_positions()

        # Check max simultaneous positions
        max_positions = self.config['risk_management']['max_simultaneous_positions']
        if len(positions) >= max_positions:
            return False, f"Maximum {max_positions} simultaneous positions reached"

        # Check max positions per symbol
        max_per_symbol = self.config['risk_management']['max_positions_per_symbol']
        symbol_positions = [p for p in positions if p['symbol'] == symbol]
        if len(symbol_positions) >= max_per_symbol:
            return False, f"Maximum {max_per_symbol} positions for {symbol} reached"

        return True, "OK"

    # ========== Journal Operations ==========

    def get_position_closes_history(self, option_symbol: str) -> List[Dict[str, Any]]:
        """Get all closes for a position"""
        return self.db.get_position_closes(option_symbol)

    def get_daily_summary(self, date: str) -> Dict[str, Any]:
        """
        Get daily trading summary

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            Daily summary dictionary
        """
        # Get all closes for the date.
        # NOTE: cannot use SQLite's DATE() here because exit_time is stored as
        # a tz-aware ISO string (e.g. "2026-05-24T20:41:32-04:00") and SQLite's
        # DATE() converts to UTC, shifting evening Eastern timestamps to the
        # next day. Compare the leading YYYY-MM-DD substring instead so the
        # date matches the timezone the caller is operating in.
        all_closes = self.db.execute_query(
            "SELECT * FROM position_closes WHERE substr(exit_time, 1, 10) = ?",
            (date,)
        )

        if not all_closes:
            return {
                'date': date,
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'gross_profit': 0.0,
                'gross_loss': 0.0,
                'net_pnl': 0.0,
                'largest_win': 0.0,
                'largest_loss': 0.0
            }

        winning_trades = [c for c in all_closes if c['realized_pnl'] > 0]
        losing_trades = [c for c in all_closes if c['realized_pnl'] < 0]

        gross_profit = sum(c['realized_pnl'] for c in winning_trades)
        gross_loss = sum(c['realized_pnl'] for c in losing_trades)
        net_pnl = gross_profit + gross_loss

        largest_win = max([c['realized_pnl'] for c in winning_trades], default=0.0)
        largest_loss = min([c['realized_pnl'] for c in losing_trades], default=0.0)

        return {
            'date': date,
            'total_trades': len(all_closes),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'net_pnl': net_pnl,
            'largest_win': largest_win,
            'largest_loss': largest_loss
        }
