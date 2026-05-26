#!/usr/bin/env python3
"""
OptionsCanvas Launcher
Boots the Flask + SocketIO server in one of two modes:
  • Trading mode  — config.json has valid Alpaca keys; full platform comes up
  • Setup mode    — keys missing/placeholder; only the /setup wizard is served,
                    and the user provisions everything from the browser. When
                    the wizard's "Start trading" button is clicked the live
                    services boot in-process and the SPA takes over.
"""

# CRITICAL: gevent.monkey.patch_all() MUST run before anything imports
# `requests`, `urllib3`, `socket`, `threading`, or `ssl`. Otherwise those
# modules get cached in their unpatched (blocking) form and every alpaca-py
# REST call freezes the entire gevent event loop — including SocketIO's
# ping/pong heartbeats, which then time out and disconnect the WebSocket.
# That manifests as: "WebSocket disconnected: ping timeout", repeated
# reconnect loops, REST endpoints (symbol_config, contracts, option/quote)
# hanging for seconds, and a permanently-disabled Buy button because the
# frontend's `isReady` check never completes.
from gevent import monkey
monkey.patch_all()

import sys
import os
import json
import socket
import threading
import time
import webbrowser
from pathlib import Path


# ----------------------------------------------------------------------------
# Dependency / config helpers
# ----------------------------------------------------------------------------
def check_dependencies() -> bool:
    required = ['flask', 'flask_cors', 'flask_socketio', 'pytz', 'alpaca']
    missing = [p for p in required if not _has(p)]
    if missing:
        print(f"[ERROR] Missing packages: {', '.join(missing)}")
        print("Install with: pip install -r requirements.txt")
        return False
    return True


def _has(pkg: str) -> bool:
    try:
        __import__(pkg)
        return True
    except ImportError:
        return False


def find_available_port(preferred: int = 5001, attempts: int = 10):
    for port in range(preferred, preferred + attempts):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', port))
            s.close()
            return port
        except OSError:
            continue
    return None


# ----------------------------------------------------------------------------
# Service boot — called either at startup (trading mode) or by the wizard's
# finalize button (setup mode). Idempotent: calling twice is a no-op.
# ----------------------------------------------------------------------------
_services_initialized = False


def _load_assisted_config(port: int, active_symbols):
    """Load assisted_trading_config.json or fall back to sensible defaults."""
    assisted_path = Path(__file__).parent / 'config' / 'assisted_trading_config.json'
    if assisted_path.exists():
        with open(assisted_path, 'r') as f:
            cfg = json.load(f)['assisted_trading']
        cfg['symbols'] = active_symbols
        return cfg
    return {
        'symbols': active_symbols,
        'contract_types': ['CALL', 'PUT'],
        'dtes': [0, 1, 2, 7, 14, 30],
        'position_sizes': [500, 1000, 2000, 5000],
        'trading_hours': {
            'timezone': 'America/New_York',
            'start_time': '09:30',
            'end_time': '16:00',
        },
        'order_settings': {
            'entry_timeout_seconds': 60,
            'auto_sell_on_stop_loss': True,
            'auto_sell_on_take_profit': True,
            'accept_partial_fills': True,
        },
        'logging': {'journal_dir': str(Path.home() / 'trading_journal')},
        'port': port,
    }


def boot_trading_services(port: int) -> bool:
    """Initialize broker, DB, trading engine. Returns True on success."""
    global _services_initialized
    if _services_initialized:
        return True

    try:
        from backend.chart_api_server import initialize_services
        from backend.config_migration import normalize_config
        from backend.database.db_manager import DatabaseManager
        from backend.symbol_config_service import SymbolConfigService

        config_path = Path(__file__).parent.parent / 'config' / 'config.json'
        with open(config_path, 'r') as f:
            raw_config = json.load(f)

        # Normalize old-shape (config.alpaca.*) into new-shape (config.broker.*)
        # in-memory. Does not rewrite the user's file.
        config = normalize_config(raw_config)
        broker_cfg = config['broker']

        # Echo the mode at boot so the user sees it in the launcher terminal.
        provider = broker_cfg['provider']
        mode = broker_cfg['mode']
        if mode == 'live':
            print()
            print("!" * 64)
            print(f"!  LIVE TRADING MODE detected — provider={provider}")
            print("!  Real money will move. Ctrl+C now if this wasn't intentional.")
            print("!" * 64)
            print()
        else:
            print(f"[mode] Paper trading ({provider})")

        db_path = Path(__file__).parent / 'state' / 'trading.db'
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_manager = DatabaseManager(str(db_path))
        symbol_service = SymbolConfigService(db_manager)
        active_symbols = symbol_service.get_all_active_symbols()
        if not active_symbols:
            print("[warn] No symbols onboarded yet. Falling back to defaults.")
            active_symbols = ['SPY', 'QQQ', 'IWM', 'AAPL', 'TSLA', 'NVDA']
        else:
            print(f"[ok] Loaded {len(active_symbols)} symbols: {', '.join(active_symbols)}")

        assisted_cfg = _load_assisted_config(port, active_symbols)
        initialize_services(broker_cfg, assisted_cfg)
        print("[ok] Trading services initialized")
        _services_initialized = True
        return True

    except Exception as e:
        print(f"[ERROR] Failed to initialize trading services: {e}")
        import traceback
        traceback.print_exc()
        return False


# ----------------------------------------------------------------------------
# Flask app boot
# ----------------------------------------------------------------------------
def start_server(port: int, open_browser: bool = True):
    os.chdir(Path(__file__).parent)

    # Import the Flask app (routes register at import time).
    from backend.chart_api_server import app, socketio
    from backend import setup_routes, security
    from flask import send_from_directory, redirect, Response

    frontend_dir = Path(__file__).parent / 'frontendv2'

    # ---- Security: CORS allowlist + CSRF enforcement ----
    # MUST happen before any route registers user-mutable side effects.
    security.register_security(app, socketio, port=port)

    # ---- Wire setup wizard ----
    app.register_blueprint(setup_routes.setup_bp)
    setup_routes.register_finalize_callback(lambda: boot_trading_services(port))

    # Helper: serve an HTML file with the per-process CSRF token injected so
    # the frontend can read it from a <meta> tag and include it on every POST.
    def _serve_html_with_csrf(filename: str) -> Response:
        path = frontend_dir / filename
        html = path.read_text(encoding='utf-8')
        html = security.inject_csrf_token(html)
        return Response(html, mimetype='text/html')

    # ---- Root route — gate on setup ----
    @app.route('/')
    def serve_root():
        if setup_routes.needs_setup() or not _services_initialized:
            return redirect('/setup')
        return _serve_html_with_csrf('index.html')

    @app.route('/<path:path>')
    def serve_static(path):
        # /setup and /api/setup/* are handled by the blueprint and won't match this.
        # Inject CSRF token into HTML files (currently only index.html lands here,
        # but future HTML pages get the same treatment automatically).
        if path.endswith('.html'):
            return _serve_html_with_csrf(path)
        return send_from_directory(str(frontend_dir), path)

    # ---- Decide initial mode ----
    if setup_routes.needs_setup():
        print()
        print("=" * 60)
        print("  First-run setup required.")
        print(f"  Open http://localhost:{port}/setup in your browser.")
        print("=" * 60)
        print()
        landing = f"http://localhost:{port}/setup"
    else:
        if not boot_trading_services(port):
            print("[ERROR] Trading services failed to start. Aborting.")
            sys.exit(1)
        landing = f"http://localhost:{port}"

    if open_browser:
        def _open():
            time.sleep(1.5)
            try:
                webbrowser.open(landing)
            except Exception:
                pass
        threading.Thread(target=_open, daemon=True).start()

    print(f"[ready] OptionsCanvas listening on http://localhost:{port}")
    print("        (Press Ctrl+C to stop.)")
    print()

    try:
        socketio.run(app, host='127.0.0.1', port=port, debug=False)
    except KeyboardInterrupt:
        print("\n[exit] Shutting down.")
        sys.exit(0)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    banner = """
============================================================
  OptionsCanvas
  Chart-Native Options Trading — Your Chart Is The Ticket
============================================================
"""
    print(banner)

    if not check_dependencies():
        sys.exit(1)

    port = find_available_port(5001)
    if port is None:
        print("[ERROR] Could not find an available port between 5001-5010.")
        sys.exit(1)
    if port != 5001:
        print(f"[warn] Port 5001 in use, using {port} instead.")

    start_server(port=port, open_browser=True)


if __name__ == '__main__':
    main()
