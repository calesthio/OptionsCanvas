"""
Sample test to verify setup
"""
import pytest

@pytest.mark.unit
def test_sample_always_passes():
    """Sample test that always passes"""
    assert True

@pytest.mark.unit
def test_order_manager_fixture(order_manager):
    """Test that order_manager fixture works"""
    assert order_manager is not None

@pytest.mark.unit
def test_position_manager_fixture(position_manager):
    """Test that position_manager fixture works"""
    assert position_manager is not None

@pytest.mark.unit
def test_mock_broker_fixture(mock_broker):
    """Test that mock_broker fixture works"""
    assert mock_broker is not None
    success, message = mock_broker.validate_connection()
    assert success is True
    assert "Mock broker" in message

@pytest.mark.unit
def test_mock_broker_provides_expirations(mock_broker):
    """Test that mock_broker implements the full broker interface"""
    expirations = mock_broker.get_available_expirations('SPY', min_dte=0, max_dte=30)

    assert expirations
    assert expirations == sorted(expirations, key=lambda exp: exp['expiration_date'])
    assert {'expiration_date', 'dte', 'is_monthly'} <= set(expirations[0])
