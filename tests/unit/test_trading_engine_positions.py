"""
Unit tests for TradingEngine position detail normalization.
"""
import pytest

from assisted_trading.backend.trading_engine import TradingEngine


@pytest.mark.unit
def test_stock_positions_are_not_parsed_as_options():
    """Broker stock positions should keep their full stock symbol."""
    engine = TradingEngine.__new__(TradingEngine)

    assert engine._is_option_symbol('AMZN') is False
    assert engine._parse_underlying_from_option('AMZN') == 'AMZN'
    assert engine._parse_option_details('AMZN') == (None, None)


@pytest.mark.unit
def test_occ_option_symbols_are_parsed():
    """OCC option symbols should expose underlying, type, and strike."""
    engine = TradingEngine.__new__(TradingEngine)

    assert engine._is_option_symbol('SPY260116C00693000') is True
    assert engine._parse_underlying_from_option('SPY260116C00693000') == 'SPY'
    assert engine._parse_option_details('SPY260116C00693000') == (693.0, 'CALL')
