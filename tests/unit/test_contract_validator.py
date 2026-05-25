"""
Unit tests for ContractValidator.
"""
from datetime import date, timedelta
from unittest.mock import MagicMock
import pytest

from assisted_trading.backend.contract_validator import ContractValidator


def _exp(days, monthly=False):
    return {
        'expiration_date': date.today() + timedelta(days=days),
        'dte': days,
        'is_monthly': monthly,
    }


@pytest.fixture
def broker():
    b = MagicMock()
    b.get_available_expirations.return_value = [
        _exp(0), _exp(1), _exp(7), _exp(30, monthly=True), _exp(60, monthly=True)
    ]
    return b


@pytest.mark.unit
class TestGetValidContracts:
    def test_returns_normalized_contracts(self, broker):
        cv = ContractValidator(broker)
        contracts = cv.get_valid_contracts('SPY')
        assert len(contracts) == 5
        assert all('dte' in c and 'expiration' in c for c in contracts)
        # monthly maps to is_weekly=False
        monthly = [c for c in contracts if not c['is_weekly']]
        assert len(monthly) == 2

    def test_caches_results(self, broker):
        cv = ContractValidator(broker)
        cv.get_valid_contracts('SPY')
        cv.get_valid_contracts('SPY')
        assert broker.get_available_expirations.call_count == 1

    def test_refresh_bypasses_cache(self, broker):
        cv = ContractValidator(broker)
        cv.get_valid_contracts('SPY')
        cv.get_valid_contracts('SPY', refresh=True)
        assert broker.get_available_expirations.call_count == 2

    def test_no_expirations_returns_empty(self):
        b = MagicMock()
        b.get_available_expirations.return_value = []
        cv = ContractValidator(b)
        assert cv.get_valid_contracts('XYZ') == []

    def test_broker_error_returns_empty_and_swallows(self):
        b = MagicMock()
        b.get_available_expirations.side_effect = RuntimeError('boom')
        cv = ContractValidator(b)
        assert cv.get_valid_contracts('XYZ') == []


@pytest.mark.unit
class TestGetContractForDte:
    def test_exact_match(self, broker):
        cv = ContractValidator(broker)
        c = cv.get_contract_for_dte('SPY', 7)
        assert c['dte'] == 7

    def test_closest_match(self, broker):
        cv = ContractValidator(broker)
        c = cv.get_contract_for_dte('SPY', 10)
        # closest to 10 is 7
        assert c['dte'] == 7

    def test_no_contracts_returns_none(self):
        b = MagicMock()
        b.get_available_expirations.return_value = []
        cv = ContractValidator(b)
        assert cv.get_contract_for_dte('XYZ', 1) is None


@pytest.mark.unit
class TestValidateContractExists:
    def test_exists(self, broker):
        cv = ContractValidator(broker)
        contracts = cv.get_valid_contracts('SPY')
        assert cv.validate_contract_exists('SPY', contracts[0]['expiration']) is True

    def test_not_exists(self, broker):
        cv = ContractValidator(broker)
        assert cv.validate_contract_exists('SPY', '1999-01-01') is False


@pytest.mark.unit
class TestClearCache:
    def test_clear_specific_symbol(self, broker):
        cv = ContractValidator(broker)
        cv.get_valid_contracts('SPY')
        cv.clear_cache('SPY')
        cv.get_valid_contracts('SPY')
        assert broker.get_available_expirations.call_count == 2

    def test_clear_all(self, broker):
        cv = ContractValidator(broker)
        cv.get_valid_contracts('SPY')
        cv.clear_cache()
        cv.get_valid_contracts('SPY')
        assert broker.get_available_expirations.call_count == 2
