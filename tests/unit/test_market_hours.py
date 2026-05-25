"""
Unit tests for MarketHours.
"""
from datetime import datetime
from unittest.mock import patch
import pytest
import pytz

from assisted_trading.backend.market_hours import MarketHours


def _config():
    return {
        'trading_hours': {
            'timezone': 'America/Los_Angeles',
            'start_pst': '06:30:00',
            'end_pst': '13:00:00',
        }
    }


def _fake_now(tz, year, month, day, hour, minute=0):
    return pytz.timezone('America/Los_Angeles').localize(datetime(year, month, day, hour, minute))


@pytest.fixture
def mh():
    return MarketHours(_config())


@pytest.mark.unit
class TestIsMarketOpen:
    def test_during_hours_weekday_open(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 10, 0)  # Tuesday 10:00
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            assert mh.is_market_open() is True

    def test_weekend_closed(self, mh):
        fake = _fake_now(None, 2026, 5, 23, 10, 0)  # Saturday
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            assert mh.is_market_open() is False

    def test_pre_market_closed(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 5, 0)  # Tuesday 5am
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            assert mh.is_market_open() is False

    def test_after_hours_closed(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 14, 0)  # Tuesday 2pm
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            assert mh.is_market_open() is False

    def test_exact_open_boundary_is_open(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 6, 30)
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            assert mh.is_market_open() is True

    def test_exact_close_boundary_is_open(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 13, 0)
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            assert mh.is_market_open() is True


@pytest.mark.unit
class TestMarketStatus:
    def test_status_when_open(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 10)
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            status = mh.get_market_status()
            assert status['is_open'] is True
            assert 'open' in status['reason'].lower()

    def test_status_weekend_reason(self, mh):
        fake = _fake_now(None, 2026, 5, 24, 10)  # Sunday
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            status = mh.get_market_status()
            assert status['is_open'] is False
            assert 'weekend' in status['reason'].lower()

    def test_validate_trading_allowed_open(self, mh):
        fake = _fake_now(None, 2026, 5, 26, 10)
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            allowed, _ = mh.validate_trading_allowed()
            assert allowed is True

    def test_validate_trading_allowed_closed(self, mh):
        fake = _fake_now(None, 2026, 5, 24, 10)
        with patch('assisted_trading.backend.market_hours.datetime') as m:
            m.now.return_value = fake
            m.strptime = datetime.strptime
            m.combine = datetime.combine
            allowed, reason = mh.validate_trading_allowed()
            assert allowed is False
            assert reason
