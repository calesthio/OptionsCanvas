"""
Chart-Based Trading API Server with WebSocket Support
Provides REST endpoints and WebSocket streaming for real-time chart data
"""

import logging
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import pytz
import threading

from .alpaca_broker import AlpacaBroker  # kept for backward import; factory uses registry
from .broker_factory import build_broker, validate_connection
from .trading_engine import TradingEngine
from .position_manager_v2 import PositionManagerV2
from .order_manager import OrderManager
from .market_hours import MarketHours
from .database import DatabaseManager
from .contract_validator import ContractValidator

logger = logging.getLogger(__name__)

# import eventlet
# eventlet.monkey_patch()

# Initialize Flask app with SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'trading-secret-key-change-in-production'
# CORS + CSRF are configured by security.register_security() which is called
# from run_platform.start_server() once the bind port is known. SocketIO's
# cors_allowed_origins is also tightened there. We start with "*" here
# (rather than [] which would reject every WebSocket handshake before
# register_security gets a chance to run); register_security narrows it
# to localhost-only before socketio.run() actually accepts traffic.
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

# Global variables
trading_engine = None
position_manager = None
order_manager = None
db_manager = None
market_hours = None
config = None
broker = None
journal_dir = None
contract_validator = None

# Streaming state
streaming_symbols = set()  # Set of (symbol, timeframe) being streamed
# Per-session subscription tracking so we can prune streaming_symbols when
# clients disconnect or unsubscribe. Without this, a closed browser tab leaves
# its (symbol, timeframe) entries in streaming_symbols forever and the
# streaming loop keeps fetching bars for symbols nobody is watching.
client_subscriptions = {}  # sid -> set of (symbol, timeframe)
streaming_thread = None
streaming_active = False


def _release_subscription(symbol: str, timeframe: str, sid: str = None) -> None:
    """Remove one client's claim on a (symbol, timeframe). If no client has
    it anymore, stop streaming for it."""
    if sid is not None:
        subs = client_subscriptions.get(sid)
        if subs:
            subs.discard((symbol, timeframe))
            if not subs:
                client_subscriptions.pop(sid, None)
    # Is anyone still subscribed?
    still_wanted = any((symbol, timeframe) in s for s in client_subscriptions.values())
    if not still_wanted:
        streaming_symbols.discard((symbol, timeframe))
        logger.info(
            "Stopped streaming %s %s — no clients subscribed",
            symbol, timeframe,
        )


def initialize_services(broker_config, assisted_config):
    """
    Initialize all services.

    Args:
        broker_config: Normalized broker config dict matching the new shape:
            {
              "provider": "alpaca",
              "mode":     "paper" | "live",
              "credentials": { ... per-broker ... },
              "options":     { ... per-broker ... },
            }
            For backward compatibility we also accept the legacy
            (api_key, secret_key, base_url, data_feed) flat shape — the
            shim below converts it.
        assisted_config: Assisted trading configuration.
    """
    global trading_engine, position_manager, order_manager, db_manager, market_hours, config, broker, journal_dir, contract_validator

    config = assisted_config

    # Initialize timezone
    timezone = pytz.timezone(config['trading_hours']['timezone'])

    # ------------------------------------------------------------------
    # Accept legacy flat shape (old run_platform.py path) and adapt it.
    # ------------------------------------------------------------------
    if 'provider' not in broker_config:
        base_url = (broker_config.get('base_url') or '').lower()
        mode = 'paper' if ('paper' in base_url or base_url == '') else 'live'
        broker_config = {
            'provider': 'alpaca',
            'mode': mode,
            'credentials': {
                'api_key': broker_config['api_key'],
                'secret_key': broker_config['secret_key'],
            },
            'options': {'data_feed': broker_config.get('data_feed', 'iex')},
        }

    provider = broker_config['provider']
    mode = broker_config['mode']

    # ------------------------------------------------------------------
    # Build broker via factory (provider-agnostic).
    # ------------------------------------------------------------------
    broker = build_broker(
        provider=provider,
        mode=mode,
        credentials=broker_config['credentials'],
        extra=broker_config.get('options', {}),
    )

    success, message = validate_connection(broker)
    if not success:
        raise Exception(f"Broker connection failed ({provider}/{mode}): {message}")
    logger.info("[%s/%s] %s", provider, mode, message)

    # Loud, unmistakable warning when running against a funded account.
    if mode == 'live':
        logger.warning("=" * 64)
        logger.warning("  LIVE TRADING MODE — orders will hit your funded %s account.", provider.upper())
        logger.warning("  Stops/targets are still server-side (not in the broker book),")
        logger.warning("  but fills are real money. Verify config/config.json is intentional.")
        logger.warning("=" * 64)
    else:
        logger.info("Paper trading mode (no real money at risk).")

    # Initialize market hours validator
    market_hours = MarketHours(config)

    # Initialize database
    # Fix: Use absolute path relative to this backend package
    backend_dir = Path(__file__).parent
    state_dir = backend_dir.parent / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = (state_dir / 'trading.db').absolute()
    
    db_manager = DatabaseManager(str(db_path))
    logger.info(f"Database initialized at: {db_path}")

    # Initialize order manager (database-backed)
    order_manager = OrderManager(timezone, db_manager)

    # Initialize position manager V2 (database-backed, broker as source of truth)
    position_manager = PositionManagerV2(config, timezone, db_manager)

    # Initialize trading engine
    trading_engine = TradingEngine(
        broker=broker,
        config=config,
        position_manager=position_manager,
        order_manager=order_manager,
        market_hours=market_hours,
        timezone=timezone
    )

    # Setup journal directory
    journal_dir = Path(config['logging']['journal_dir'])
    journal_dir.mkdir(parents=True, exist_ok=True)

    # Initialize contract validator
    contract_validator = ContractValidator(broker)
    logger.info("Contract validator initialized")

    logger.info("All services initialized successfully")


# ========== REST API Endpoints ==========

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    global db_manager
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'broker': broker.__class__.__name__,
        'db_path': str(db_manager.db_path) if db_manager else 'Not Initialized'
    })


@app.route('/api/config', methods=['GET'])
def get_config():
    """Get frontend configuration including available symbols"""
    global config
    return jsonify({
        'symbols': config.get('symbols', []),
        'contract_types': config.get('contract_types', []),
        'dtes': config.get('dtes', []),
        'position_sizes': config.get('position_sizes', [])
    })


@app.route('/api/broker/info', methods=['GET'])
def get_broker_info():
    """Get broker information and configuration"""
    try:
        account_info = broker.get_account_info()
        return jsonify({
            'broker_type': broker.__class__.__name__,
            'paper_trading': broker.paper,
            'account': account_info
        })
    except Exception as e:
        logger.error(f"Error getting broker info: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/chart/historical/<symbol>', methods=['GET'])
def get_historical_chart_data(symbol):
    """
    Get historical chart data for a symbol

    Query params:
        timeframe: Chart timeframe (default '5Min')
        limit: Number of bars (default 1000)
        start: Start time in ISO format (optional)
        end: End time in ISO format (optional)
    """
    try:
        timeframe = request.args.get('timeframe', '5Min')
        limit = int(request.args.get('limit', 1000))
        start = request.args.get('start')
        end = request.args.get('end')

        # Default start date if not provided (needed for Alpaca)
        if not start:
            # Look back roughly enough for the limit
            # 5 days is usually safe for 1000 minute bars
            start_dt = datetime.now(pytz.utc) - timedelta(days=5)
            start = start_dt.isoformat()

        bars = broker.get_historical_bars(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit
        )

        return jsonify({
            'symbol': symbol,
            'timeframe': timeframe,
            'bars': bars,
            'count': len(bars)
        })

    except Exception as e:
        logger.error(f"Error getting historical data: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/symbol/contracts/<symbol>', methods=['GET'])
def get_symbol_contracts(symbol):
    """
    Get valid tradable contracts for a symbol

    Query params:
        refresh: Force refresh cache (optional, default false)
    """
    try:
        global contract_validator

        refresh = request.args.get('refresh', 'false').lower() == 'true'

        valid_contracts = contract_validator.get_valid_contracts(symbol, refresh=refresh)

        return jsonify({
            'symbol': symbol,
            'contracts': valid_contracts,
            'count': len(valid_contracts)
        })

    except Exception as e:
        logger.error(f"Error getting valid contracts for {symbol}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/symbol/config/<symbol>', methods=['GET'])
def get_symbol_config(symbol):
    """
    Get symbol configuration including tick sizes and strike increments

    Query params:
        price: Current price (optional, for price-dependent values)
    """
    try:
        price = float(request.args.get('price', 100.0))

        # Get current price if not provided
        if not request.args.get('price'):
            price = broker.get_current_price(symbol)

        tick_size = broker.get_tick_size(symbol, price)
        strike_increment = broker.get_strike_increment(symbol, price)

        return jsonify({
            'symbol': symbol,
            'current_price': price,
            'tick_size': tick_size,
            'strike_increment': strike_increment,
            'option_tick_rules': {
                'below_3': 0.05,
                'above_3': 0.10
            }
        })

    except Exception as e:
        logger.error(f"Error getting symbol config: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/symbol/strikes/<symbol>', methods=['GET'])
def get_symbol_strikes(symbol):
    """
    Return the actual list of strike prices the broker lists for this
    underlying at the requested DTE + contract type. Frontend snaps to
    nearest strike in this list instead of synthesizing via increment math
    — that's the only way to get it right for symbols like MSTR where
    different expirations have different strike grids.

    Query params:
        dte (required, int)
        type (required, 'call' or 'put')
    """
    try:
        dte = int(request.args.get('dte', '0'))
        opt_type = (request.args.get('type', 'call') or 'call').lower()
        if opt_type not in ('call', 'put'):
            return jsonify({'error': "type must be 'call' or 'put'"}), 400

        strikes = broker.get_strikes_for_dte(symbol, dte, opt_type)
        return jsonify({
            'symbol': symbol,
            'dte': dte,
            'type': opt_type,
            'strikes': strikes,
            'count': len(strikes),
        })
    except Exception as e:
        logger.error("Error getting strikes for %s: %s", symbol, e, exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/option/quote/<option_symbol>', methods=['GET'])
def get_option_quote(option_symbol):
    """
    Get real-time option quote (bid, ask, last, mark)

    Args:
        option_symbol: OCC option symbol (e.g., SPY260117C00595000)

    Returns:
        {
            'option_symbol': str,
            'bid': float,
            'ask': float,
            'last': float,
            'mark': float (midpoint),
            'timestamp': str
        }
    """
    try:
        quote = broker.get_option_quote(option_symbol)

        # Broker returns 'mid' field, map it to 'mark' for frontend
        bid = quote.get('bid', 0.0)
        ask = quote.get('ask', 0.0)
        mid = quote.get('mid', (bid + ask) / 2)

        return jsonify({
            'success': True,
            'option_symbol': option_symbol,
            'bid': bid,
            'ask': ask,
            'last': quote.get('last', mid),  # Fallback to mid if no last
            'mark': mid,  # Use mid as mark (midpoint)
            'timestamp': quote.get('timestamp', ''),
            'volume': quote.get('volume', 0),
            'spread': quote.get('spread', ask - bid),
            # Greeks
            'delta': quote.get('delta'),
            'gamma': quote.get('gamma'),
            'theta': quote.get('theta'),
            'vega': quote.get('vega'),
            'iv': quote.get('iv')
        })

    except Exception as e:
        # Don't throw 500 error for market closed / no quote data - return gracefully
        logger.warning(f"Could not get option quote for {option_symbol}: {e}")
        return jsonify({
            'success': False,
            'error': str(e),
            'option_symbol': option_symbol,
            'bid': 0.0,
            'ask': 0.0,
            'last': 0.0,
            'mark': 0.0
        }), 200  # Return 200 instead of 500 - this is expected when markets are closed


@app.route('/api/position', methods=['GET'])
def get_all_positions():
    """Get all open positions"""
    try:
        # Process pending orders first (check for fills and equity limits)
        trading_engine.process_pending_orders()

        # Also check stop loss and take profit
        trading_engine.check_stop_loss()
        trading_engine.check_take_profit()

        # Get position details with live pricing
        positions = trading_engine.get_position_details()

        return jsonify({'positions': positions})
    except Exception as e:
        logger.error(f"Error getting positions: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/position/<symbol>', methods=['GET'])
def get_position(symbol):
    """Get position for a specific symbol"""
    try:
        position = broker.get_position(symbol)
        if position:
            return jsonify(position)
        else:
            return jsonify({}), 404
    except Exception as e:
        logger.error(f"Error getting position for {symbol}: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/position/update_sl_tp', methods=['POST'])
def update_sl_tp():
    """
    Update stop loss or take profit for a position (from drag-and-drop)

    Body:
        {
            "option_symbol": str,
            "stop_loss_price": float (optional),
            "take_profit_price": float (optional)
        }
    """
    try:
        data = request.json

        if 'option_symbol' not in data:
            return jsonify({'error': 'Missing required field: option_symbol'}), 400

        option_symbol = data['option_symbol']
        stop_loss_price = data.get('stop_loss_price')
        take_profit_price = data.get('take_profit_price')

        results = {}

        if stop_loss_price is not None:
            result = trading_engine.update_stop_loss(option_symbol, float(stop_loss_price))
            results['stop_loss'] = result

        if take_profit_price is not None:
            result = trading_engine.update_take_profit(option_symbol, float(take_profit_price))
            results['take_profit'] = result

        return jsonify({
            'success': True,
            'results': results
        })

    except Exception as e:
        logger.error(f"Error updating SL/TP: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/open_position', methods=['POST'])
def open_new_position():
    """
    Open a new position

    Body:
        {
            "symbol": str, (SPY/QQQ)
            "contract_type": str, (CALL/PUT)
            "dte": int,
            "strike": float (optional, calculated if not provided),
            "position_size": float,
            "stop_loss_price": float (optional),
            "take_profit_price": float (optional),
            "order_type": str (optional, default 'equity_market'),
            "equity_limit_price": float (optional),
            "option_order_type": str (optional, 'market'/'limit', default 'limit')
        }
    """
    try:
        data = request.json
        required_fields = ['symbol', 'contract_type', 'dte', 'position_size']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400

        result = trading_engine.open_position(
            symbol=data['symbol'],
            contract_type=data['contract_type'],
            dte=int(data['dte']),
            strike=float(data['strike']) if data.get('strike') else None,
            position_size=float(data['position_size']),
            stop_loss_price=float(data['stop_loss_price']) if data.get('stop_loss_price') else None,
            take_profit_price=float(data['take_profit_price']) if data.get('take_profit_price') else None,
            order_type=data.get('order_type', 'equity_market'),
            equity_limit_price=float(data['equity_limit_price']) if data.get('equity_limit_price') else None,
            option_order_type=data.get('option_order_type', 'limit')
        )

        if result.get('success'):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error opening position: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/close_position', methods=['POST'])
def close_current_position():
    """
    Close a position

    Body:
        {
            "option_symbol": str,
            "contracts": int
        }
    """
    try:
        data = request.json
        if 'option_symbol' not in data or 'contracts' not in data:
            return jsonify({'error': 'Missing required fields'}), 400

        result = trading_engine.close_position(
            option_symbol=data['option_symbol'],
            contracts=int(data['contracts'])
        )

        if result.get('success'):
            return jsonify(result)
        else:
            return jsonify(result), 400

    except Exception as e:
        logger.error(f"Error closing position: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/orders', methods=['GET'])
def get_pending_orders():
    """
    Get all pending/queued orders.

    For orders in `pending_fill` (broker has them, waiting to fill), we
    enrich each row with:
      - strike + option_symbol (already in our DB after transition)
      - limit_price (the broker's limit we sent — was "midpoint at submit")
      - current bid/ask/mark on the option (live quote)
    so the UI can show the user where their order sits vs. the live market
    instead of just "Limit @ Midpoint" with no numbers.
    """
    global order_manager, broker
    try:
        orders = order_manager.get_pending_orders()

        # Enrich pending_fill rows with broker limit + live quote. Done
        # server-side so the UI does one round-trip instead of N.
        for order in orders:
            if order.get('status') != 'pending_fill':
                continue
            broker_oid = order.get('broker_order_id')
            opt_sym = order.get('option_symbol')

            if broker_oid:
                try:
                    bo = broker.get_order_status(broker_oid)
                    if bo.get('limit_price') is not None:
                        order['limit_price'] = bo['limit_price']
                    if bo.get('qty') is not None:
                        order['broker_qty'] = bo['qty']
                except Exception as e:
                    # Don't fail the whole list if one broker fetch hiccups.
                    logger.debug("Could not enrich order %s with broker data: %s",
                                 order.get('order_id'), e)

            if opt_sym:
                try:
                    q = broker.get_option_quote(opt_sym)
                    order['current_bid'] = q.get('bid')
                    order['current_ask'] = q.get('ask')
                    order['current_mark'] = q.get('mark') or q.get('mid')
                except Exception as e:
                    logger.debug("Could not enrich order %s with quote: %s",
                                 order.get('order_id'), e)

        return jsonify({'orders': orders})
    except Exception as e:
        logger.error(f"Error getting pending orders: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


@app.route('/api/cancel_pending_order', methods=['POST'])
def cancel_pending_order():
    """
    Cancel a pending order

    Body:
        {
            "order_id": str
        }

    Returns user-friendly error messages for display
    """
    try:
        data = request.json
        if 'order_id' not in data:
            return jsonify({
                'success': False,
                'message': 'No order ID provided'
            }), 400

        result = trading_engine.cancel_pending_order(data['order_id'])

        if result.get('success'):
            return jsonify(result), 200
        else:
            # Return user-friendly error with 200 status so frontend can show message
            return jsonify(result), 200

    except Exception as e:
        logger.error(f"Unexpected error canceling order: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': 'An unexpected error occurred. Please try again or contact support.'
        }), 200


# ========== WebSocket Events ==========

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connection_established', {
        'sid': request.sid,
        'timestamp': datetime.now().isoformat()
    })


@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection. Clean up streaming for any (symbol,
    timeframe) this client had subscribed to — if no other client wants it,
    stop polling it. Without this, every closed tab / disconnect leaks
    entries into streaming_symbols and the background loop keeps fetching
    bars for symbols nobody is watching."""
    sid = request.sid
    logger.info(f"Client disconnected: {sid}")
    subs = client_subscriptions.pop(sid, set())
    for (symbol, timeframe) in subs:
        # _release_subscription with sid=None because we already popped
        _release_subscription(symbol, timeframe, sid=None)


@socketio.on('subscribe_chart')
def handle_subscribe_chart(data):
    """
    Subscribe to real-time chart updates for a symbol

    Data:
        {
            "symbol": str,
            "timeframe": str (optional, default '1Min')
        }
    """
    try:
        symbol = data.get('symbol')
        timeframe = data.get('timeframe', '1Min')

        if not symbol:
            emit('error', {'message': 'Symbol is required'})
            return

        room = f"chart_{symbol}_{timeframe}"
        join_room(room)

        # Track per-client so we can release the streaming claim on disconnect.
        client_subscriptions.setdefault(request.sid, set()).add((symbol, timeframe))
        streaming_symbols.add((symbol, timeframe))

        # Start streaming thread if not already running
        start_streaming_thread()

        logger.info(f"Client {request.sid} subscribed to {symbol} {timeframe}")
        emit('subscribed', {
            'symbol': symbol,
            'timeframe': timeframe,
            'room': room
        })

    except Exception as e:
        logger.error(f"Error subscribing to chart: {e}", exc_info=True)
        emit('error', {'message': str(e)})


@socketio.on('unsubscribe_chart')
def handle_unsubscribe_chart(data):
    """
    Unsubscribe from chart updates

    Data:
        {
            "symbol": str,
            "timeframe": str (optional, default '1Min')
        }
    """
    try:
        symbol = data.get('symbol')
        timeframe = data.get('timeframe', '1Min')

        if not symbol:
            emit('error', {'message': 'Symbol is required'})
            return

        room = f"chart_{symbol}_{timeframe}"
        leave_room(room)

        # Release this client's claim. Only stops streaming if no other
        # client wants the same (symbol, timeframe). Previous version did an
        # unconditional discard which broke multi-client setups; we keep
        # the per-client semantics even though OptionsCanvas is single-user
        # so the data flow stays correct if someone opens a second tab.
        _release_subscription(symbol, timeframe, sid=request.sid)

        logger.info(f"Client {request.sid} unsubscribed from {symbol} {timeframe}")
        emit('unsubscribed', {
            'symbol': symbol,
            'timeframe': timeframe
        })

    except Exception as e:
        logger.error(f"Error unsubscribing from chart: {e}", exc_info=True)
        emit('error', {'message': str(e)})


def start_streaming_thread():
    """Start the background thread for streaming chart data"""
    global streaming_thread, streaming_active

    if streaming_thread is None or not streaming_thread.is_alive():
        streaming_active = True
        streaming_thread = threading.Thread(target=stream_chart_updates, daemon=True)
        streaming_thread.start()
        logger.info("Started chart streaming thread")


# ---------------------------------------------------------------------------
# Risk monitor — SERVER-SIDE SL/TP polling.
#
# Previously, check_stop_loss / check_take_profit ran only inside the
# /api/position request handler, meaning stops only checked when the browser
# happened to be polling. A closed tab, throttled background tab, network
# blip, or user-on-lunch meant stops simply did not fire — defeating the
# whole "stops live locally, not on the broker book" promise. This loop
# runs unconditionally as long as the server is up.
# ---------------------------------------------------------------------------

risk_monitor_thread = None
risk_monitor_active = False
RISK_MONITOR_INTERVAL = 2.0  # seconds — fast enough to catch typical wicks


def start_risk_monitor_thread():
    """Start the background thread that polls SL/TP/pending-orders."""
    global risk_monitor_thread, risk_monitor_active

    if risk_monitor_thread is None or not risk_monitor_thread.is_alive():
        risk_monitor_active = True
        risk_monitor_thread = threading.Thread(target=risk_monitor_loop, daemon=True)
        risk_monitor_thread.start()
        logger.info("Started risk monitor thread (SL/TP polling every %.1fs)",
                    RISK_MONITOR_INTERVAL)


def risk_monitor_loop():
    """
    Server-side loop that checks every open position's SL/TP and processes
    pending orders on a fixed cadence. Failures in any single iteration are
    caught + logged so the loop keeps running — losing this loop silently
    is the worst-case outcome.

    Market-hours gating: options trade 9:30–16:00 ET, so a SL/TP "trigger"
    outside that window can't actually close anything (any sell we'd send
    rejects or queues). We still call the loop on its 2s cadence — the
    cost is one is_market_open() check — but skip the broker work when
    closed. At the open, the very first tick after 9:30:00 sweeps every
    position, so an overnight gap through your SL fires on the next tick
    (not waiting for the browser to poll).
    """
    global risk_monitor_active
    logger.info("Risk monitor loop started (gated on market hours)")

    last_open_state = None  # log open/close transitions once each

    while risk_monitor_active:
        try:
            is_open = market_hours.is_market_open() if market_hours else True

            # Log only when state flips, so we don't spam every 2s.
            if is_open != last_open_state:
                logger.info(
                    "Risk monitor: market %s — SL/TP checks %s",
                    "OPEN" if is_open else "CLOSED",
                    "active" if is_open else "paused",
                )
                last_open_state = is_open

            if is_open:
                # Process pending orders first so a freshly-filled order gets
                # its SL/TP checked in the same tick.
                trading_engine.process_pending_orders()
                trading_engine.check_stop_loss()
                trading_engine.check_take_profit()
        except Exception as e:
            logger.error("Risk monitor iteration failed: %s", e, exc_info=True)
        time.sleep(RISK_MONITOR_INTERVAL)


def stream_chart_updates():
    """
    Background thread that streams chart updates to subscribed clients
    Runs every 1 second to update current bar data
    """
    global streaming_active

    logger.info("Chart streaming thread started")

    while streaming_active:
        try:
            # Get unique symbols and their latest prices
            for symbol, timeframe in list(streaming_symbols):
                try:
                    # Get current price
                    current_price = broker.get_current_price(symbol)

                    # Get the latest bar (last completed + current forming)
                    bars = broker.get_historical_bars(
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=2
                    )

                    if bars:
                        # Take the most recent bar (current forming bar)
                        latest_bar = bars[-1]

                        # Update the close price with current price
                        latest_bar['close'] = current_price

                        # Update high/low if needed
                        latest_bar['high'] = max(latest_bar['high'], current_price)
                        latest_bar['low'] = min(latest_bar['low'], current_price)

                        room = f"chart_{symbol}_{timeframe}"

                        # Emit bar update to all clients in this room
                        socketio.emit('bar_update', {
                            'symbol': symbol,
                            'timeframe': timeframe,
                            'bar': latest_bar,
                            'timestamp': datetime.now().isoformat()
                        }, room=room)

                except Exception as e:
                    logger.error(f"Error streaming {symbol}: {e}")

            # Sleep for 1 second before next update
            time.sleep(1)

        except Exception as e:
            logger.error(f"Error in streaming thread: {e}", exc_info=True)
            time.sleep(5)  # Wait longer on error

    logger.info("Chart streaming thread stopped")


@app.route('/api/market_status', methods=['GET'])
def get_market_status():
    """Get current market status"""
    status = market_hours.get_market_status()
    return jsonify(status)


@app.route('/api/day_pnl', methods=['GET'])
def get_day_pnl():
    """Get day P&L: realized (from today's closes) + unrealized (from open positions).

    Reads realized P&L from the SQLite journal_entries table — that's the
    source of truth, written automatically every time a position closes (see
    PositionManagerV2._record_daily_aggregate_for_date). The legacy code path
    here read from `journal_dir/<date>/trades.json` which no code actually
    writes to in v0.1.x, so Day P&L always showed $0 after a close. Now we
    query the same table /api/journal already uses.
    """
    try:
        today = datetime.now().strftime('%Y-%m-%d')

        realized_pnl = 0.0
        try:
            entries = db_manager.get_journal_entries(start_date=today, end_date=today)
            if entries:
                # journal_entries is upserted on every close — there is at most
                # one row per date. Take the first (and only) match.
                realized_pnl = float(entries[0].get('net_pnl', 0.0) or 0.0)
        except Exception as e:
            logger.warning("Could not read journal_entries for %s: %s", today, e)

        # Unrealized P&L from currently-open positions
        unrealized_pnl = 0.0
        try:
            if position_manager.has_any_position():
                for pos in trading_engine.get_position_details() or []:
                    unrealized_pnl += float(pos.get('unrealized_pnl', 0.0) or 0.0)
        except Exception as e:
            logger.warning("Could not compute unrealized P&L: %s", e)

        return jsonify({
            'day_pnl': realized_pnl + unrealized_pnl,
            'realized_pnl': realized_pnl,
            'unrealized_pnl': unrealized_pnl,
            'date': today,
        })

    except Exception as e:
        logger.error(f"Error getting day P&L: {e}", exc_info=True)
        return jsonify({'error': str(e), 'day_pnl': 0.0}), 500


@app.route('/api/journal', methods=['GET'])
def get_journal():
    """Get journal entries, optionally filtered by date or date range."""
    try:
        date_filter = request.args.get('date')
        start_date = request.args.get('start_date') or date_filter
        end_date = request.args.get('end_date') or date_filter

        entries = db_manager.get_journal_entries(start_date=start_date, end_date=end_date)

        return jsonify({
            'entries': entries,
            'count': len(entries)
        })

    except Exception as e:
        logger.error(f"Error getting journal entries: {e}", exc_info=True)
        return jsonify({'error': str(e), 'entries': []}), 500


# ========== Server Run Function ==========

def run_chart_server(alpaca_config, assisted_config, host='127.0.0.1', port=5000):
    """
    Run the Flask-SocketIO server

    Args:
        alpaca_config: Alpaca API configuration
        assisted_config: Assisted trading configuration
        host: Server host
        port: Server port
    """
    # Initialize services
    initialize_services(alpaca_config, assisted_config)

    # Start the server-side SL/TP poller. CRITICAL — without this, stops
    # only check when the browser asks for /api/position, so a closed tab
    # = no SL protection.
    start_risk_monitor_thread()

    # Run server with SocketIO
    logger.info(f"Starting Chart API server on {host}:{port}")
    socketio.run(app, host=host, port=port, debug=False)


if __name__ == '__main__':
    # For testing
    import sys
    sys.path.append(str(Path(__file__).parent.parent.parent))

    from assisted_trading.backend.config_module import ConfigModule

    # Load configs
    config_dir = Path(__file__).parent.parent.parent / 'config'
    config_module = ConfigModule(config_dir=str(config_dir))

    alpaca_cfg = {
        'api_key': config_module.get_alpaca_api_key(),
        'secret_key': config_module.get_alpaca_secret_key(),
        'data_feed': config_module.get_data_feed()
    }

    # Load assisted trading config
    assisted_config_path = Path(__file__).parent.parent / 'config' / 'assisted_trading_config.json'
    with open(assisted_config_path, 'r') as f:
        assisted_cfg = json.load(f)['assisted_trading']

    run_chart_server(alpaca_cfg, assisted_cfg, port=5001)
