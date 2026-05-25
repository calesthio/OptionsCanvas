"""
Symbol Configuration Service
Manages which symbols are enabled for trading.
The broker API is the single source of truth for option chain details
(expirations, strikes, increments). This service only tracks symbol enablement.
"""

import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class SymbolConfigService:
    """Manages which symbols are enabled for options trading"""

    def __init__(self, db_manager):
        """
        Initialize service

        Args:
            db_manager: DatabaseManager instance
        """
        self.db = db_manager

    def get_symbol_config(self, symbol: str) -> Optional[Dict]:
        """
        Get configuration for a specific symbol

        Args:
            symbol: Symbol to get config for

        Returns:
            Dictionary with symbol config or None if not found
        """
        query = """
            SELECT * FROM supported_symbols
            WHERE symbol = ? AND is_active = 1
        """
        result = self.db.execute_query(query, (symbol,))
        return result[0] if result else None

    def get_all_active_symbols(self) -> List[str]:
        """
        Get list of all active symbols

        Returns:
            List of symbol strings
        """
        query = "SELECT symbol FROM supported_symbols WHERE is_active = 1 ORDER BY symbol"
        results = self.db.execute_query(query)
        return [row['symbol'] for row in results]

    def add_symbol(self, symbol: str, notes: str = None) -> bool:
        """
        Add a new symbol to the system

        Args:
            symbol: Symbol ticker (e.g., 'SPY')
            notes: Optional notes about the symbol

        Returns:
            True if successful, False otherwise
        """
        query = """
            INSERT INTO supported_symbols (symbol, notes)
            VALUES (?, ?)
        """
        try:
            self.db.execute_insert(query, (symbol, notes))
            logger.info(f"Added symbol {symbol} to supported symbols")
            return True
        except Exception as e:
            logger.error(f"Failed to add symbol {symbol}: {e}")
            return False

    def update_symbol(self, symbol: str, **kwargs) -> bool:
        """
        Update an existing symbol's configuration

        Args:
            symbol: Symbol to update
            **kwargs: Fields to update (only 'notes' is supported)

        Returns:
            True if successful, False otherwise
        """
        allowed_fields = {'notes'}

        updates = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not updates:
            logger.warning(f"No valid fields to update for {symbol}")
            return False

        set_clause = ', '.join([f"{k} = ?" for k in updates.keys()])
        query = f"""
            UPDATE supported_symbols
            SET {set_clause}, last_updated = CURRENT_TIMESTAMP
            WHERE symbol = ?
        """

        try:
            values = tuple(updates.values()) + (symbol,)
            self.db.execute_update(query, values)
            logger.info(f"Updated symbol {symbol}")
            return True
        except Exception as e:
            logger.error(f"Failed to update symbol {symbol}: {e}")
            return False

    def deactivate_symbol(self, symbol: str) -> bool:
        """
        Deactivate a symbol (soft delete)

        Args:
            symbol: Symbol to deactivate

        Returns:
            True if successful, False otherwise
        """
        query = """
            UPDATE supported_symbols
            SET is_active = 0, last_updated = CURRENT_TIMESTAMP
            WHERE symbol = ?
        """
        try:
            rows = self.db.execute_update(query, (symbol,))
            if rows > 0:
                logger.info(f"Deactivated symbol {symbol}")
                return True
            else:
                logger.warning(f"Symbol {symbol} not found")
                return False
        except Exception as e:
            logger.error(f"Failed to deactivate symbol {symbol}: {e}")
            return False

    def reactivate_symbol(self, symbol: str) -> bool:
        """
        Reactivate a previously deactivated symbol

        Args:
            symbol: Symbol to reactivate

        Returns:
            True if successful, False otherwise
        """
        query = """
            UPDATE supported_symbols
            SET is_active = 1, last_updated = CURRENT_TIMESTAMP
            WHERE symbol = ?
        """
        try:
            rows = self.db.execute_update(query, (symbol,))
            if rows > 0:
                logger.info(f"Reactivated symbol {symbol}")
                return True
            else:
                logger.warning(f"Symbol {symbol} not found")
                return False
        except Exception as e:
            logger.error(f"Failed to reactivate symbol {symbol}: {e}")
            return False
