"""
Configuration Module for SPY Liquidity Grab Trading System
Handles loading and validation of configuration files
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, time
import pytz


class ConfigurationError(Exception):
    """Custom exception for configuration errors"""
    pass


class ConfigModule:
    """
    Manages system configuration from JSON files
    Provides validated access to trading parameters
    """

    def __init__(self, config_dir: str = "config"):
        """
        Initialize configuration module

        Args:
            config_dir: Directory containing configuration files
        """
        self.config_dir = Path(config_dir)
        self.api_config: Dict[str, Any] = {}
        self.market_config: Dict[str, Any] = {}
        self.backtest_config: Dict[str, Any] = {}
        self.use_backtest_overrides: bool = False

        self._load_configurations()
        self._validate_configurations()

    def enable_backtest_overrides(self):
        """Enable using backtest config to override market config"""
        self.use_backtest_overrides = True

    def _get_config_value(self, section: str, key: str, default: Any = None) -> Any:
        """
        Get config value, prioritizing backtest_config if overrides enabled
        """
        # Check backtest override
        if self.use_backtest_overrides:
            if section in self.backtest_config and key in self.backtest_config[section]:
                return self.backtest_config[section][key]
        
        # Check market config
        if section in self.market_config and key in self.market_config[section]:
            return self.market_config[section][key]
            
        return default

    def _load_configurations(self):
        """Load all configuration files"""
        try:
            # Load API credentials, alerts, and market config
            config_path = self.config_dir / "config.json"
            if config_path.exists():
                with open(config_path, 'r') as f:
                    self.api_config = json.load(f)
                    
                # Populate market_config from the main config file
                self.market_config = self.api_config.get('market_config', {})
            else:
                raise ConfigurationError(f"Config file not found: {config_path}")

            # Load backtest parameters (optional)
            backtest_config_path = self.config_dir / "backtest_configs.json"
            if backtest_config_path.exists():
                with open(backtest_config_path, 'r') as f:
                    self.backtest_config = json.load(f)

        except json.JSONDecodeError as e:
            raise ConfigurationError(f"Invalid JSON format: {e}")
        except Exception as e:
            raise ConfigurationError(f"Error loading configuration: {e}")

    def _validate_configurations(self):
        """Validate configuration parameters"""
        # Validate Alpaca credentials
        if not self.api_config.get('alpaca', {}).get('api_key'):
            raise ConfigurationError("Alpaca API key not configured")
        if not self.api_config.get('alpaca', {}).get('secret_key'):
            raise ConfigurationError("Alpaca secret key not configured")

        # Validate trading parameters
        trading = self.market_config.get('trading', {})
        if trading.get('symbol') != 'SPY':
            raise ConfigurationError("Only SPY is supported")

        dte = trading.get('dte')
        if dte is None or not (0 <= dte <= 2):
            raise ConfigurationError("DTE must be 0, 1, or 2")

        position_size = trading.get('position_size', 0)
        if position_size <= 0:
            raise ConfigurationError("Position size must be positive")

        sl_percentage = trading.get('sl_percentage', 0)
        if not (0 < sl_percentage <= 100):
            raise ConfigurationError("Stop loss percentage must be between 0 and 100")

        # Validate timezone
        tz_str = self.market_config.get('timezone', 'America/Los_Angeles')
        try:
            pytz.timezone(tz_str)
        except pytz.UnknownTimeZoneError:
            raise ConfigurationError(f"Invalid timezone: {tz_str}")

    # Alpaca API Configuration
    def get_alpaca_api_key(self) -> str:
        """Get Alpaca API key"""
        return self.api_config['alpaca']['api_key']

    def get_alpaca_secret_key(self) -> str:
        """Get Alpaca secret key"""
        return self.api_config['alpaca']['secret_key']

    def get_alpaca_base_url(self) -> str:
        """Get Alpaca base URL"""
        return self.api_config['alpaca'].get('base_url', 'https://paper-api.alpaca.markets')

    def get_data_feed(self) -> str:
        """Get data feed type (sip or iex)"""
        return self.api_config['alpaca'].get('data_feed', 'sip')

    def is_paper_trading(self) -> bool:
        """Check if paper trading mode"""
        base_url = self.get_alpaca_base_url()
        return 'paper' in base_url.lower()

    # Alert Configuration
    def is_alerts_enabled(self) -> bool:
        """Check if alerts are enabled"""
        return self.api_config.get('alerts', {}).get('enabled', False)

    def get_discord_webhook_url(self) -> Optional[str]:
        """Get Discord webhook URL"""
        return self.api_config.get('alerts', {}).get('discord_webhook_url')

    def get_alert_levels(self) -> list:
        """Get alert levels"""
        return self.api_config.get('alerts', {}).get('alert_levels', ['INFO', 'WARNING', 'ERROR', 'CRITICAL'])

    # Logging Configuration
    def get_log_level(self) -> str:
        """Get logging level"""
        return self.api_config.get('logging', {}).get('level', 'INFO')

    def get_log_folder(self) -> str:
        """Get log folder path"""
        return self.api_config.get('logging', {}).get('folder', 'logs')

    def use_dated_folders(self) -> bool:
        """Check if dated log folders should be used"""
        return self.api_config.get('logging', {}).get('dated_folders', True)

    def get_max_log_size_mb(self) -> int:
        """Get max log file size in MB"""
        return self.api_config.get('logging', {}).get('max_size_mb', 50)

    # Trading Configuration
    def get_symbol(self) -> str:
        """Get trading symbol"""
        return self._get_config_value('trading', 'symbol')

    def get_dte(self) -> int:
        """Get days to expiration for options"""
        return self._get_config_value('trading', 'dte')

    def get_position_size(self) -> float:
        """Get base position size in USD"""
        return float(self._get_config_value('trading', 'position_size'))

    def get_candle_timeframe(self) -> str:
        """Get candle timeframe (e.g., '2Min')"""
        return self._get_config_value('trading', 'candle_timeframe')

    def get_exit_strategy(self) -> str:
        """Get exit strategy name"""
        return self._get_config_value('trading', 'exit_strategy')

    def get_stop_loss_percentage(self) -> float:
        """Get stop loss percentage"""
        return float(self._get_config_value('trading', 'sl_percentage'))

    def is_price_reclaim_exit_active(self) -> bool:
        """Check if price reclaim exit validation is active"""
        return self._get_config_value('trading', 'activate_price_reclaim_exit', True)

    def get_max_trades_per_day(self) -> int:
        """Get maximum trades per day"""
        return self._get_config_value('trading', 'max_trades_per_day', 1)

    # Pre-Market Configuration
    def get_premarket_start_time(self) -> time:
        """Get pre-market start time (PST)"""
        time_str = self._get_config_value('pre_market', 'start_time_pst')
        return datetime.strptime(time_str, '%H:%M:%S').time()

    def get_premarket_end_time(self) -> time:
        """Get pre-market end time (PST)"""
        time_str = self._get_config_value('pre_market', 'end_time_pst')
        return datetime.strptime(time_str, '%H:%M:%S').time()

    # Exit Strategy Configuration
    def get_exit_strategy_config(self) -> Dict[str, Any]:
        """Get exit strategy configuration"""
        strategy_name = self.get_exit_strategy()
        if strategy_name == 'multi-level-profit-taking':
            # This is nested, so we fetch the whole strategy dict
            return self._get_config_value('exit_strategies', 'multi_level_profit_taking', {})
        return {}

    def get_t1_target(self) -> str:
        """Get T1 target type"""
        config = self.get_exit_strategy_config()
        return config.get('t1_target', 'daily_open')

    def get_t1_exit_percentage(self) -> float:
        """Get T1 exit percentage"""
        config = self.get_exit_strategy_config()
        return float(config.get('t1_exit_percentage', 0.50))

    def should_move_sl_to_breakeven_after_t1(self) -> bool:
        """Check if stop loss should move to breakeven after T1"""
        config = self.get_exit_strategy_config()
        return config.get('t1_move_sl_to_breakeven', True)

    def get_t2_target(self) -> str:
        """Get T2 target type"""
        config = self.get_exit_strategy_config()
        return config.get('t2_target', 'min_hod_pmhigh')

    def get_t2_exit_percentage(self) -> float:
        """Get T2 exit percentage"""
        config = self.get_exit_strategy_config()
        return float(config.get('t2_exit_percentage', 0.25))

    def get_t3_time(self) -> time:
        """Get T3 time exit (PST)"""
        config = self.get_exit_strategy_config()
        time_str = config.get('t3_time_pst', '12:00:00')
        return datetime.strptime(time_str, '%H:%M:%S').time()

    def get_t3_exit_percentage(self) -> float:
        """Get T3 exit percentage"""
        config = self.get_exit_strategy_config()
        return float(config.get('t3_exit_percentage', 0.25))

    # Price Reclaim Exit Configuration
    def get_price_reclaim_candle_period(self) -> int:
        """Get price reclaim validation candle period in minutes"""
        return self._get_config_value('price_reclaim_exit', 'candle_period_minutes')

    def should_require_close_above_pmlow(self) -> bool:
        """Check if close above PM low is required"""
        return self._get_config_value('price_reclaim_exit', 'require_close_above_pmlow')

    # Position Sizing Configuration
    def prefer_even_contracts(self) -> bool:
        """Check if even contract count is preferred"""
        return self._get_config_value('position_sizing', 'prefer_even_contracts')

    def get_min_contracts(self) -> int:
        """Get minimum contract count"""
        return self._get_config_value('position_sizing', 'min_contracts')

    def get_round_method(self) -> str:
        """Get rounding method for contracts (ceiling/floor/nearest)"""
        return self._get_config_value('position_sizing', 'round_method')

    # Timezone Configuration
    def get_timezone(self) -> pytz.timezone:
        """Get trading timezone object"""
        tz_str = self._get_config_value('timezone', 'timezone', default='America/Los_Angeles')
        # Since timezone is top-level in market_configs.json (line 49), but my helper assumes section/key
        # Wait, market config has 'timezone' at root. _get_config_value expects section.
        # Check market_configs.json structure again.
        # Line 49: "timezone": "America/Los_Angeles" (it IS top level).
        # My helper `if section in self.market_config` checks for a key `section`.
        # So I can pass section='timezone' but then key='timezone'? No.
        # I need to handle root level keys. or just use 'timezone' as section?
        # If I look at `_get_config_value`:
        # if section in self.market_config and key in self.market_config[section]:
        # This implies nested structure.
        # `timezone` IS NOT nested.
        # So I need to special case timezone or modify helper. Or just not use helper for root keys.
        # I will special case it here.
        if self.use_backtest_overrides and 'timezone' in self.backtest_config:
             tz_str = self.backtest_config['timezone']
        elif 'timezone' in self.market_config:
             tz_str = self.market_config['timezone']
        return pytz.timezone(tz_str)

    def get_timezone_str(self) -> str:
        """Get timezone string"""
        if self.use_backtest_overrides and 'timezone' in self.backtest_config:
             return self.backtest_config['timezone']
        return self.market_config.get('timezone', 'America/Los_Angeles')

    # Backtest Configuration
    def is_backtest_enabled(self) -> bool:
        """Check if backtesting is enabled"""
        return self.backtest_config.get('backtest', {}).get('enabled', False)

    def get_backtest_start_date(self) -> str:
        """Get backtest start date"""
        return self.backtest_config.get('backtest', {}).get('start_date', '')

    def get_backtest_end_date(self) -> str:
        """Get backtest end date"""
        return self.backtest_config.get('backtest', {}).get('end_date', '')

    def get_backtest_initial_capital(self) -> float:
        """Get initial capital for backtest"""
        return float(self.backtest_config.get('backtest', {}).get('initial_capital', 10000))

    def is_compounding_enabled(self) -> bool:
        """Check if compounding is enabled in backtest"""
        return self.backtest_config.get('backtest', {}).get('compounding', False)

    def use_opra_historical_data(self) -> bool:
        """Check if OPRA historical data should be used"""
        return self.backtest_config.get('simulation', {}).get('use_opra_historical_data', True)

    def get_slippage_pct(self) -> float:
        """Get slippage percentage for simulation"""
        return float(self.backtest_config.get('simulation', {}).get('slippage_pct', 0.5))

    def get_fill_assumption(self) -> str:
        """Get fill assumption (mid/bid/ask)"""
        return self.backtest_config.get('simulation', {}).get('fill_assumption', 'mid')

    def should_save_backtest_results(self) -> bool:
        """Check if backtest results should be saved"""
        return self.backtest_config.get('output', {}).get('save_results', True)

    def should_generate_plots(self) -> bool:
        """Check if plots should be generated"""
        return self.backtest_config.get('output', {}).get('generate_plots', True)

    def get_backtest_output_directory(self) -> str:
        """Get backtest output directory"""
        return self.backtest_config.get('output', {}).get('output_directory', 'output/backtest')

    def __repr__(self) -> str:
        """String representation"""
        return (f"ConfigModule(symbol={self.get_symbol()}, "
                f"dte={self.get_dte()}, "
                f"position_size=${self.get_position_size()}, "
                f"paper_trading={self.is_paper_trading()})")


# Singleton instance
_config_instance: Optional[ConfigModule] = None


def get_config(config_dir: str = "config") -> ConfigModule:
    """
    Get or create configuration module instance (singleton pattern)

    Args:
        config_dir: Directory containing configuration files

    Returns:
        ConfigModule instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = ConfigModule(config_dir)
    return _config_instance


def reload_config(config_dir: str = "config") -> ConfigModule:
    """
    Force reload configuration from files

    Args:
        config_dir: Directory containing configuration files

    Returns:
        New ConfigModule instance
    """
    global _config_instance
    _config_instance = ConfigModule(config_dir)
    return _config_instance
