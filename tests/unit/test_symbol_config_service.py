"""
Unit tests for SymbolConfigService.
"""
import pytest

from assisted_trading.backend.symbol_config_service import SymbolConfigService


@pytest.fixture
def svc(test_db):
    return SymbolConfigService(test_db)


@pytest.mark.unit
class TestSymbolLifecycle:
    def test_add_symbol(self, svc):
        assert svc.add_symbol('AAPL', 'a note') is True
        cfg = svc.get_symbol_config('AAPL')
        assert cfg is not None
        assert cfg['notes'] == 'a note'

    def test_add_duplicate_symbol_returns_false(self, svc):
        assert svc.add_symbol('TSLA') is True
        # UNIQUE constraint causes failure - service catches and returns False
        assert svc.add_symbol('TSLA') is False

    def test_get_all_active_symbols_sorted(self, svc):
        svc.add_symbol('MSFT')
        svc.add_symbol('AAPL')
        svc.add_symbol('NVDA')
        symbols = svc.get_all_active_symbols()
        assert symbols == sorted(symbols)
        assert set(symbols) >= {'AAPL', 'MSFT', 'NVDA'}

    def test_deactivate_symbol(self, svc):
        svc.add_symbol('XYZ')
        assert svc.deactivate_symbol('XYZ') is True
        assert svc.get_symbol_config('XYZ') is None
        assert 'XYZ' not in svc.get_all_active_symbols()

    def test_deactivate_nonexistent_returns_false(self, svc):
        assert svc.deactivate_symbol('NOPE') is False

    def test_reactivate_symbol(self, svc):
        svc.add_symbol('ABC')
        svc.deactivate_symbol('ABC')
        assert svc.reactivate_symbol('ABC') is True
        assert svc.get_symbol_config('ABC') is not None

    def test_reactivate_nonexistent_returns_false(self, svc):
        assert svc.reactivate_symbol('GHOST') is False

    def test_update_symbol_notes(self, svc):
        svc.add_symbol('UPD', 'old')
        assert svc.update_symbol('UPD', notes='new') is True
        assert svc.get_symbol_config('UPD')['notes'] == 'new'

    def test_update_symbol_with_no_valid_fields(self, svc):
        svc.add_symbol('NOFIELD')
        # only 'notes' is allowed; bogus field is ignored, returns False
        assert svc.update_symbol('NOFIELD', frobnicate=True) is False

    def test_get_nonexistent_symbol_returns_none(self, svc):
        assert svc.get_symbol_config('DOESNOTEXIST') is None
