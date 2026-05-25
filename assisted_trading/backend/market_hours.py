"""
Market Hours Validation Module for Assisted Trading
Validates trading hours and checks if markets are open
"""

import logging
from datetime import datetime, time
import pytz

logger = logging.getLogger(__name__)


class MarketHours:
    """Validates market trading hours"""

    def __init__(self, config):
        """
        Initialize market hours validator

        Args:
            config: Assisted trading configuration
        """
        self.config = config
        self.timezone = pytz.timezone(config['trading_hours']['timezone'])

        # Parse trading hours
        start_str = config['trading_hours']['start_pst']
        end_str = config['trading_hours']['end_pst']

        self.start_time = datetime.strptime(start_str, '%H:%M:%S').time()
        self.end_time = datetime.strptime(end_str, '%H:%M:%S').time()

        logger.info(f"Market hours: {self.start_time} - {self.end_time} {self.timezone}")

    def is_market_open(self):
        """
        Check if market is currently open

        Returns:
            bool: True if market is open, False otherwise
        """
        now = datetime.now(self.timezone)

        # Check if weekend
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            logger.debug("Market closed: Weekend")
            return False

        # Check if within trading hours
        current_time = now.time()

        if self.start_time <= current_time <= self.end_time:
            return True
        else:
            logger.debug(f"Market closed: Outside trading hours ({current_time})")
            return False

    def get_market_status(self):
        """
        Get detailed market status

        Returns:
            dict: Market status information
        """
        now = datetime.now(self.timezone)
        is_open = self.is_market_open()

        status = {
            'is_open': is_open,
            'current_time': now.strftime('%H:%M:%S %Z'),
            'current_date': now.strftime('%Y-%m-%d'),
            'day_of_week': now.strftime('%A'),
            'trading_hours': f"{self.start_time} - {self.end_time} PST"
        }

        if not is_open:
            if now.weekday() >= 5:
                status['reason'] = 'Weekend - Markets are closed'
            elif now.time() < self.start_time:
                status['reason'] = f'Pre-market - Markets open at {self.start_time} PST'
            else:
                status['reason'] = f'After-hours - Markets closed at {self.end_time} PST'
        else:
            status['reason'] = 'Markets are open for trading'

        return status

    def time_until_open(self):
        """
        Calculate time until market opens

        Returns:
            str: Human-readable time until open, or None if market is open
        """
        if self.is_market_open():
            return None

        now = datetime.now(self.timezone)

        # If weekend, calculate to next Monday
        if now.weekday() >= 5:
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 1
            return f"{days_until_monday} day(s)"

        # If before market open today
        if now.time() < self.start_time:
            open_today = self.timezone.localize(
                datetime.combine(now.date(), self.start_time)
            )
            delta = open_today - now
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            return f"{hours}h {minutes}m"

        # If after market close, opens tomorrow
        return "Next trading day"

    def validate_trading_allowed(self):
        """
        Validate if trading is allowed

        Returns:
            tuple: (bool, str) - (allowed, reason)
        """
        status = self.get_market_status()

        if status['is_open']:
            return True, "Trading allowed"
        else:
            return False, status['reason']
