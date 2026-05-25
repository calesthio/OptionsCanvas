"""
Pytest configuration and fixtures
"""
import pytest
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from assisted_trading.backend.database.db_manager import DatabaseManager
from assisted_trading.backend.order_manager import OrderManager
from assisted_trading.backend.position_manager_v2 import PositionManagerV2
import pytz

@pytest.fixture
def test_db(tmp_path):
    """Create temporary test database"""
    db_path = str(tmp_path / "test.db")
    db = DatabaseManager(db_path)
    yield db
    # Cleanup happens automatically when tmp_path is deleted

@pytest.fixture
def timezone():
    """Get Eastern timezone"""
    return pytz.timezone('US/Eastern')

@pytest.fixture
def order_manager(test_db, timezone):
    """Create order manager for testing"""
    return OrderManager(timezone, test_db)

@pytest.fixture
def position_manager(test_db, timezone):
    """Create position manager for testing"""
    config = {
        'risk_management': {
            'max_simultaneous_positions': 5,
            'max_positions_per_symbol': 2
        }
    }
    return PositionManagerV2(config, timezone, test_db)

@pytest.fixture
def mock_broker():
    """Create mock broker"""
    from tests.mocks.mock_broker import MockBroker
    return MockBroker()

@pytest.fixture
def config():
    """Test configuration"""
    return {
        'order_settings': {
            'entry_timeout_seconds': 60,
            'accept_partial_fills': True,
            'auto_sell_on_stop_loss': True,
            'auto_sell_on_take_profit': True
        },
        'position_limits': {
            'max_simultaneous_positions': 5,
            'max_positions_per_symbol': 2
        }
    }

# Hypothesis settings
from hypothesis import settings

settings.register_profile("ci", max_examples=10, deadline=500)
settings.register_profile("dev", max_examples=100, deadline=1000)
settings.register_profile("thorough", max_examples=10000, deadline=5000)
