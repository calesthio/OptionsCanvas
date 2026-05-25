"""
Contract Validator
Validates and discovers available option contracts for symbols.
Uses broker.get_available_expirations() (broker-agnostic interface method).
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class ContractValidator:
    """Validates and discovers available option contracts"""

    def __init__(self, broker):
        """
        Initialize contract validator

        Args:
            broker: Broker instance implementing BrokerInterface
        """
        self.broker = broker
        self.cache = {}  # Cache valid contracts
        self.cache_expiry = {}  # Track when cache expires

    def get_valid_contracts(self, symbol: str, refresh: bool = False) -> List[Dict]:
        """
        Get list of valid tradable contracts for a symbol.
        Delegates to broker.get_available_expirations() for broker-agnostic discovery.

        Args:
            symbol: Stock symbol
            refresh: Force refresh cache

        Returns:
            List of dicts with: {
                'dte': int,
                'expiration': 'YYYY-MM-DD',
                'expiration_display': 'DD Mon YYYY',
                'is_weekly': bool
            }
        """
        # Check cache
        cache_key = symbol
        if not refresh and cache_key in self.cache:
            # Cache valid for 1 hour
            if datetime.now().timestamp() < self.cache_expiry.get(cache_key, 0):
                return self.cache[cache_key]

        logger.info(f"Discovering valid contracts for {symbol}...")

        try:
            # Use broker interface method — works with any broker
            expirations = self.broker.get_available_expirations(symbol)

            if not expirations:
                logger.warning(f"No expirations found for {symbol}")
                return []

            # Build result list matching expected format
            valid_contracts = []
            for exp in expirations:
                exp_date = exp['expiration_date']
                dte = exp['dte']
                is_monthly = exp.get('is_monthly', False)

                valid_contracts.append({
                    'dte': dte,
                    'expiration': exp_date.strftime('%Y-%m-%d'),
                    'expiration_display': exp_date.strftime('%d %b %Y'),
                    'is_weekly': not is_monthly
                })

            logger.info(f"Found {len(valid_contracts)} valid contracts for {symbol}")

            # Cache results for 1 hour
            self.cache[cache_key] = valid_contracts
            self.cache_expiry[cache_key] = datetime.now().timestamp() + 3600

            return valid_contracts

        except Exception as e:
            logger.error(f"Error discovering contracts for {symbol}: {e}")
            return []

    def get_contract_for_dte(self, symbol: str, target_dte: int) -> Optional[Dict]:
        """
        Get contract info for a specific target DTE

        Args:
            symbol: Stock symbol
            target_dte: Target days to expiration

        Returns:
            Contract dict or None if not found
        """
        contracts = self.get_valid_contracts(symbol)

        # Find closest match to target DTE
        best_match = None
        min_diff = float('inf')

        for contract in contracts:
            diff = abs(contract['dte'] - target_dte)
            if diff < min_diff:
                min_diff = diff
                best_match = contract

        return best_match

    def validate_contract_exists(self, symbol: str, expiration: str) -> bool:
        """
        Validate that a contract with specific expiration exists

        Args:
            symbol: Stock symbol
            expiration: Expiration date 'YYYY-MM-DD'

        Returns:
            True if contract exists
        """
        contracts = self.get_valid_contracts(symbol)
        return any(c['expiration'] == expiration for c in contracts)

    def clear_cache(self, symbol: Optional[str] = None):
        """
        Clear contract cache

        Args:
            symbol: Specific symbol to clear, or None for all
        """
        if symbol:
            self.cache.pop(symbol, None)
            self.cache_expiry.pop(symbol, None)
        else:
            self.cache.clear()
            self.cache_expiry.clear()
