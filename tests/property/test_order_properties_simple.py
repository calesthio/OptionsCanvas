"""
Property-Based Tests for OrderManager (Simplified)
Uses Hypothesis to test with thousands of random examples
"""

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck
import pytz
import tempfile
from pathlib import Path

from assisted_trading.backend.state_machine import OrderState, StateTransitionError
from assisted_trading.backend.database.db_manager import DatabaseManager
from assisted_trading.backend.order_manager import OrderManager


# Helper to create fresh order manager
def create_order_manager():
    """Create a fresh OrderManager instance for testing"""
    temp_dir = tempfile.mkdtemp()
    db_path = str(Path(temp_dir) / "test.db")
    db = DatabaseManager(db_path)
    timezone = pytz.timezone('US/Eastern')
    return OrderManager(timezone, db)


# Data strategies
symbols = st.sampled_from(['SPY', 'QQQ', 'AAPL', 'MSFT', 'NVDA'])
contract_types = st.sampled_from(['CALL', 'PUT'])
order_types = st.sampled_from(['equity_market', 'equity_limit'])
dte_range = st.integers(min_value=1, max_value=90)
position_size = st.floats(
    min_value=100.0,
    max_value=50000.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
    width=32
)
price_range = st.floats(
    min_value=1.0,
    max_value=1000.0,
    allow_nan=False,
    allow_infinity=False,
    allow_subnormal=False,
    width=32
)
quantity_range = st.integers(min_value=1, max_value=1000)


@pytest.mark.property
@given(
    symbol=symbols,
    contract_type=contract_types,
    dte=dte_range,
    pos_size=position_size,
    order_type=order_types
)
@settings(max_examples=200, deadline=2000)
def test_create_order_always_succeeds(symbol, contract_type, dte, pos_size, order_type):
    """Property: Creating valid orders always succeeds"""
    order_manager = create_order_manager()
    equity_limit_price = 450.0 if order_type == 'equity_limit' else None

    order_id = order_manager.create_order(
        symbol=symbol,
        contract_type=contract_type,
        dte=dte,
        position_size=pos_size,
        order_type=order_type,
        equity_limit_price=equity_limit_price
    )

    assert isinstance(order_id, str)
    assert len(order_id) > 0

    order = order_manager.get_order(order_id)
    assert order is not None
    assert order['symbol'] == symbol
    assert order['contract_type'] == contract_type


@pytest.mark.property
@given(
    symbol=symbols,
    pos_size=position_size,
    filled_qty=quantity_range,
    filled_price=price_range
)
@settings(max_examples=200, deadline=2000)
def test_filled_orders_stay_filled(symbol, pos_size, filled_qty, filled_price):
    """Property: Once filled, orders remain filled"""
    order_manager = create_order_manager()

    order_id = order_manager.create_order(
        symbol=symbol,
        contract_type='CALL',
        dte=30,
        position_size=pos_size,
        order_type='equity_market'
    )

    order_manager.mark_order_filled(order_id, filled_qty, filled_price)
    order = order_manager.get_order(order_id)

    assert order['status'] == 'filled'
    assert order['filled_qty'] == filled_qty
    assert order['filled_avg_price'] == filled_price

    # Cannot cancel filled order
    result = order_manager.cancel_order(order_id)
    assert result is False

    # Still filled
    order = order_manager.get_order(order_id)
    assert order['status'] == 'filled'


@pytest.mark.property
@given(
    symbol=symbols,
    pos_size=position_size,
    qty=quantity_range,
    price=price_range
)
@settings(max_examples=200, deadline=2000)
def test_cannot_fill_order_twice(symbol, pos_size, qty, price):
    """Property: Filling an already-filled order raises error"""
    order_manager = create_order_manager()

    order_id = order_manager.create_order(
        symbol=symbol,
        contract_type='PUT',
        dte=30,
        position_size=pos_size,
        order_type='equity_market'
    )

    # Fill once
    order_manager.mark_order_filled(order_id, qty, price)

    # Second fill should fail
    with pytest.raises(StateTransitionError):
        order_manager.mark_order_filled(order_id, qty, price)


@pytest.mark.property
@given(symbol=symbols, pos_size=position_size)
@settings(max_examples=100, deadline=2000)
def test_order_ids_are_unique(symbol, pos_size):
    """Property: Every created order has unique ID"""
    order_manager = create_order_manager()

    order_ids = set()
    for _ in range(10):
        order_id = order_manager.create_order(
            symbol=symbol,
            contract_type='CALL',
            dte=30,
            position_size=pos_size,
            order_type='equity_market'
        )
        order_ids.add(order_id)

    assert len(order_ids) == 10


@pytest.mark.property
@given(
    symbol=symbols,
    pos_size=position_size,
    order_type=order_types
)
@settings(max_examples=200, deadline=2000)
def test_initial_state_depends_on_order_type(symbol, pos_size, order_type):
    """Property: Order initial state depends on order_type"""
    order_manager = create_order_manager()
    equity_limit_price = 450.0 if order_type == 'equity_limit' else None

    order_id = order_manager.create_order(
        symbol=symbol,
        contract_type='CALL',
        dte=30,
        position_size=pos_size,
        order_type=order_type,
        equity_limit_price=equity_limit_price
    )

    order = order_manager.get_order(order_id)

    if order_type == 'equity_limit':
        assert order['status'] == 'monitoring_equity'
    else:
        assert order['status'] == 'pending'


@pytest.mark.property
@given(
    symbols_list=st.lists(symbols, min_size=2, max_size=5, unique=True),
    pos_size=position_size
)
@settings(max_examples=100, deadline=3000)
def test_get_pending_orders_filters_correctly(symbols_list, pos_size):
    """Property: get_pending_orders returns only non-terminal states"""
    order_manager = create_order_manager()

    pending_ids = []
    filled_ids = []

    for symbol in symbols_list:
        # Create pending
        pending_id = order_manager.create_order(
            symbol=symbol,
            contract_type='CALL',
            dte=30,
            position_size=pos_size,
            order_type='equity_market'
        )
        pending_ids.append(pending_id)

        # Create and fill
        filled_id = order_manager.create_order(
            symbol=symbol,
            contract_type='PUT',
            dte=30,
            position_size=pos_size,
            order_type='equity_market'
        )
        order_manager.mark_order_filled(filled_id, 10, 5.0)
        filled_ids.append(filled_id)

    pending_orders = order_manager.get_pending_orders()
    statuses = [o['status'] for o in pending_orders]

    # Should not have filled
    assert 'filled' not in statuses

    # Should have pending
    pending_order_ids = {o['order_id'] for o in pending_orders}
    for pid in pending_ids:
        assert pid in pending_order_ids


@pytest.mark.property
@given(
    symbol=symbols,
    pos_size=position_size,
    sl_price=price_range,
    tp_price=price_range
)
@settings(max_examples=200, deadline=2000)
def test_stop_loss_take_profit_stored(symbol, pos_size, sl_price, tp_price):
    """Property: SL/TP prices are stored correctly"""
    order_manager = create_order_manager()

    order_id = order_manager.create_order(
        symbol=symbol,
        contract_type='CALL',
        dte=30,
        position_size=pos_size,
        order_type='equity_market',
        stop_loss_price=sl_price,
        take_profit_price=tp_price
    )

    order = order_manager.get_order(order_id)
    assert order['stop_loss_price'] == sl_price
    assert order['take_profit_price'] == tp_price
