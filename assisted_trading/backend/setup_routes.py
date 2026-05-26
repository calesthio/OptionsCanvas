"""
First-run setup wizard routes.

Exposes a Flask Blueprint that powers the browser-based wizard so non-technical
users never need to touch config.json or the CLI to get started.

Steps the wizard drives:
  1. Paste + validate Alpaca paper-trading API keys
  2. Onboard a trading universe (Tier-1 / all / custom)
  3. Finalize — boot the live trading services in-process and redirect to /

All state mutations live in:
  - config/config.json                            (Alpaca keys)
  - assisted_trading/state/trading.db             (supported_symbols)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, request, send_from_directory

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "config.json"
CONFIG_EXAMPLE_PATH = PROJECT_ROOT / "config" / "config.example.json"
DB_PATH = PROJECT_ROOT / "assisted_trading" / "state" / "trading.db"
FRONTEND_DIR = PROJECT_ROOT / "assisted_trading" / "frontendv2"

# Import curated universe constants + helpers from the onboarding script so
# there is exactly one source of truth.
sys.path.insert(0, str(PROJECT_ROOT))
from scripts.onboard_symbol import (  # noqa: E402
    TIER_1,
    TIER_2,
    TIER_3,
    UNIVERSE_ALL,
    ensure_table_exists,
    upsert_symbol,
)

# ---------------------------------------------------------------------------
# Module-level state — set by run_platform when finalize succeeds.
# ---------------------------------------------------------------------------
# A callable that boots the live trading services. Signature: () -> bool
# Returning True means services initialized successfully and the main `/`
# route can serve the trading UI; False means a runtime error occurred.
_finalize_callback = None


def register_finalize_callback(callback) -> None:
    """Plumbing — wired from run_platform.py so the wizard can flip the app
    from setup-mode into trading-mode without a process restart."""
    global _finalize_callback
    _finalize_callback = callback


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
PLACEHOLDER_TOKENS = {"", "YOUR_ALPACA_API_KEY", "YOUR_ALPACA_SECRET_KEY", "YOUR_API_KEY", "YOUR_SECRET_KEY"}


def config_is_valid() -> bool:
    """True iff config.json exists and contains non-placeholder credentials in
    either the new `broker` block or the legacy `alpaca` block."""
    if not CONFIG_PATH.exists():
        return False
    try:
        with open(CONFIG_PATH, "r") as f:
            cfg = json.load(f)
    except Exception:
        return False

    # Prefer the new shape.
    broker = cfg.get("broker") or {}
    creds = broker.get("credentials") or {}
    if creds:
        return all(
            isinstance(v, str) and v.strip() and v.strip() not in PLACEHOLDER_TOKENS
            for v in creds.values()
        )

    # Fall back to the legacy shape.
    alpaca = cfg.get("alpaca") or {}
    api_key = (alpaca.get("api_key") or "").strip()
    secret = (alpaca.get("secret_key") or "").strip()
    return (
        bool(api_key) and bool(secret)
        and api_key not in PLACEHOLDER_TOKENS
        and secret not in PLACEHOLDER_TOKENS
    )


def has_onboarded_symbols() -> bool:
    """True iff the supported_symbols table exists and has at least one active row."""
    if not DB_PATH.exists():
        return False
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='supported_symbols'"
        )
        if cur.fetchone() is None:
            conn.close()
            return False
        cur.execute("SELECT COUNT(*) FROM supported_symbols WHERE is_active=1")
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def needs_setup() -> bool:
    return not config_is_valid()


def _load_or_init_config() -> dict:
    """Load config.json if it exists; otherwise seed from the example."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    if CONFIG_EXAMPLE_PATH.exists():
        try:
            with open(CONFIG_EXAMPLE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"alpaca": {}}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def _build_alpaca_client(api_key: str, secret_key: str, paper: bool):
    """Build a raw Alpaca TradingClient — used by the onboarding step where we
    need the alpaca-py types (GetOptionContractsRequest etc.). For broker
    *validation* we go through the factory."""
    from alpaca.trading.client import TradingClient
    return TradingClient(api_key=api_key, secret_key=secret_key, paper=paper)


def _build_broker_via_factory(provider: str, mode: str, credentials: dict, extra: dict | None = None):
    """Construct a BrokerInterface via the registry/factory."""
    from .broker_factory import build_broker
    return build_broker(provider=provider, mode=mode, credentials=credentials, extra=extra or {})


# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
setup_bp = Blueprint("setup", __name__)


@setup_bp.route("/setup", methods=["GET"])
def serve_wizard():
    """Serve the setup wizard SPA with the per-process CSRF token injected.

    The wizard's POSTs (test-broker, save-broker, onboard, finalize) all
    require the token now — same enforcement as the main trading UI."""
    from flask import Response
    from .security import inject_csrf_token
    html = (FRONTEND_DIR / "setup.html").read_text(encoding="utf-8")
    return Response(inject_csrf_token(html), mimetype="text/html")


@setup_bp.route("/api/setup/status", methods=["GET"])
def api_status():
    """Wizard polls this on load to decide where to start."""
    return jsonify({
        "needs_setup": needs_setup(),
        "has_config": config_is_valid(),
        "has_symbols": has_onboarded_symbols(),
        "tier_counts": {
            "tier1": len(TIER_1),
            "tier1_2": len(TIER_1) + len(TIER_2),
            "all": len(UNIVERSE_ALL),
        },
    })


@setup_bp.route("/api/setup/brokers", methods=["GET"])
def api_brokers():
    """Return the list of available brokers + their metadata for the wizard
    to render. New endpoint introduced in Phase 0 — not yet consumed by
    setup.html, but the next-turn wizard rewrite will read from here."""
    from .broker_registry import list_brokers
    return jsonify({"brokers": list_brokers()})


@setup_bp.route("/api/setup/test-broker", methods=["POST"])
def api_test_broker():
    """Provider-agnostic connection check.

    Body: {"provider": "alpaca", "mode": "paper"|"live",
           "credentials": {...}, "options": {...optional...}}
    """
    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "").strip().lower()
    mode = (body.get("mode") or "paper").strip().lower()
    credentials = body.get("credentials") or {}
    extra = body.get("options") or {}

    if not provider:
        return jsonify({"ok": False, "error": "Missing 'provider'."}), 400

    try:
        broker_obj = _build_broker_via_factory(provider, mode, credentials, extra)
        ok, message = broker_obj.validate_connection()
        if not ok:
            return jsonify({"ok": False, "error": message}), 200

        # Try to pull a snapshot of account info for the UI.
        try:
            info = broker_obj.get_account_info() if hasattr(broker_obj, "get_account_info") else {}
        except Exception:
            info = {}
        return jsonify({"ok": True, "provider": provider, "mode": mode,
                        "account": info, "message": message})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


@setup_bp.route("/api/setup/test-alpaca", methods=["POST"])
def api_test_alpaca():
    """Backwards-compatible Alpaca-only endpoint — the legacy setup.html still
    calls this. Internally it now delegates to the provider-agnostic factory
    path so the code under it is unified with /api/setup/test-broker.

    Body: {"api_key": "...", "secret_key": "...", "paper": true}
    """
    body = request.get_json(silent=True) or {}
    api_key = (body.get("api_key") or "").strip()
    secret_key = (body.get("secret_key") or "").strip()
    paper = bool(body.get("paper", True))

    if not api_key or not secret_key:
        return jsonify({"ok": False, "error": "Both API key and secret are required."}), 400

    try:
        broker_obj = _build_broker_via_factory(
            provider="alpaca",
            mode=("paper" if paper else "live"),
            credentials={"api_key": api_key, "secret_key": secret_key},
            extra={"data_feed": "iex"},
        )
        ok, message = broker_obj.validate_connection()
        if not ok:
            # Fall through to the legacy error mapping below.
            raise RuntimeError(message)

        info = {}
        try:
            info = broker_obj.get_account_info() if hasattr(broker_obj, "get_account_info") else {}
        except Exception:
            pass
        return jsonify({
            "ok": True,
            "account": {
                "id": str(info.get("id", "") or ""),
                "account_number": info.get("account_number", "") or "",
                "status": str(info.get("status", "") or ""),
                "buying_power": str(info.get("buying_power", "") or ""),
                "currency": info.get("currency", "USD"),
                "paper": paper,
            },
        })
    except Exception as e:
        msg = str(e)
        if "forbidden" in msg.lower() or "401" in msg or "403" in msg:
            friendly = (
                "Alpaca rejected the keys. Double-check you copied the right pair, "
                "and that you generated them under the appropriate section "
                "(paper vs live use different keys)."
            )
        elif "name resolution" in msg.lower() or "connection" in msg.lower():
            friendly = "Couldn't reach Alpaca. Check your internet connection and try again."
        else:
            friendly = msg
        return jsonify({"ok": False, "error": friendly}), 200


@setup_bp.route("/api/setup/save-broker", methods=["POST"])
def api_save_broker():
    """Provider-agnostic save endpoint — the new wizard calls this.

    Body: {"provider": "alpaca" | "tradier" | ...,
           "mode": "paper" | "live",
           "credentials": { ... per-broker ... },
           "options":     { ... per-broker, optional ... }
          }

    Writes the new `broker` config block. Validates `provider` against the
    registry and `mode` against the broker's `supports_modes`. Does NOT
    initialize trading services — wizard calls /api/setup/finalize after
    onboarding to do that.
    """
    from .broker_registry import BROKER_REGISTRY, get_broker

    body = request.get_json(silent=True) or {}
    provider = (body.get("provider") or "").strip().lower()
    mode = (body.get("mode") or "paper").strip().lower()
    credentials = body.get("credentials") or {}
    options = body.get("options") or {}

    if provider not in BROKER_REGISTRY:
        return jsonify({
            "ok": False,
            "error": f"Unknown broker {provider!r}. Available: {list(BROKER_REGISTRY)}",
        }), 400

    meta = get_broker(provider)
    if mode not in meta["supports_modes"]:
        return jsonify({
            "ok": False,
            "error": f"Broker {provider!r} does not support mode {mode!r}. "
                     f"Supported: {meta['supports_modes']}",
        }), 400

    # Required credential fields must all be filled.
    missing = [f["label"] for f in meta["credentials_schema"]
               if f.get("required") and not str(credentials.get(f["key"], "")).strip()]
    if missing:
        return jsonify({"ok": False, "error": f"Required field(s) missing: {', '.join(missing)}"}), 400

    cfg = _load_or_init_config()
    cfg["broker"] = {
        "provider": provider,
        "mode": mode,
        "credentials": {k: v for k, v in credentials.items() if v != ""},
        "options": options,
    }

    # For Alpaca, mirror to the legacy `alpaca` block so any out-of-band
    # tooling that still reads the old shape continues to work. For all
    # other providers we never wrote to `alpaca` so there's nothing to mirror.
    if provider == "alpaca":
        legacy = cfg.setdefault("alpaca", {})
        legacy["api_key"] = credentials.get("api_key", "")
        legacy["secret_key"] = credentials.get("secret_key", "")
        legacy["base_url"] = (
            "https://paper-api.alpaca.markets" if mode == "paper"
            else "https://api.alpaca.markets"
        )
        legacy["data_feed"] = options.get("data_feed", "iex")
    else:
        # Stale Alpaca creds from a previous setup would confuse anything
        # still reading the legacy block. Drop it on broker switch.
        cfg.pop("alpaca", None)

    try:
        _save_config(cfg)
    except Exception as e:
        logger.exception("Failed to save config.json")
        return jsonify({"ok": False, "error": f"Could not write config.json: {e}"}), 500

    return jsonify({"ok": True, "path": str(CONFIG_PATH), "provider": provider, "mode": mode})


@setup_bp.route("/api/setup/save-config", methods=["POST"])
def api_save_config():
    """Persist Alpaca credentials to config.json. Does NOT initialize services.

    Body: {"api_key": "...", "secret_key": "...", "paper": true, "data_feed": "iex"}
    """
    body = request.get_json(silent=True) or {}
    api_key = (body.get("api_key") or "").strip()
    secret_key = (body.get("secret_key") or "").strip()
    paper = bool(body.get("paper", True))
    data_feed = (body.get("data_feed") or "iex").strip()

    if not api_key or not secret_key:
        return jsonify({"ok": False, "error": "Both API key and secret are required."}), 400

    cfg = _load_or_init_config()

    # Write the NEW (provider-agnostic) shape. We keep the legacy "alpaca"
    # block in sync too so any external tooling that still reads the old
    # path continues to work.
    cfg["broker"] = {
        "provider": "alpaca",
        "mode": "paper" if paper else "live",
        "credentials": {"api_key": api_key, "secret_key": secret_key},
        "options": {"data_feed": data_feed},
    }
    legacy = cfg.setdefault("alpaca", {})
    legacy["api_key"] = api_key
    legacy["secret_key"] = secret_key
    legacy["base_url"] = (
        "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    )
    legacy["data_feed"] = data_feed

    try:
        _save_config(cfg)
    except Exception as e:
        logger.exception("Failed to save config.json")
        return jsonify({"ok": False, "error": f"Could not write config.json: {e}"}), 500

    return jsonify({"ok": True, "path": str(CONFIG_PATH)})


@setup_bp.route("/api/setup/onboard", methods=["POST"])
def api_onboard():
    """Run symbol onboarding against Alpaca. Synchronous; returns per-symbol results.

    Body: {"mode": "tier1" | "tier1_2" | "all" | "custom",
           "symbols": ["AAPL", ...]   # required if mode == "custom"
          }
    """
    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or "tier1").lower()

    if mode == "tier1":
        symbols = list(TIER_1)
    elif mode == "tier1_2":
        symbols = list(TIER_1 + TIER_2)
    elif mode == "all":
        symbols = list(UNIVERSE_ALL)
    elif mode == "custom":
        raw = body.get("symbols") or []
        symbols = [s.strip().upper() for s in raw if isinstance(s, str) and s.strip()]
        if not symbols:
            return jsonify({"ok": False, "error": "Provide at least one custom symbol."}), 400
    else:
        return jsonify({"ok": False, "error": f"Unknown mode: {mode}"}), 400

    if not config_is_valid():
        return jsonify({"ok": False, "error": "Save your broker keys first."}), 400

    # Load + normalize config, then build the broker via the factory. From here
    # on the code is provider-agnostic — adding a 3rd broker that supports
    # options requires zero changes to this endpoint.
    from .broker_factory import build_broker
    from .config_migration import normalize_config

    with open(CONFIG_PATH, "r") as f:
        cfg = normalize_config(json.load(f))
    broker_cfg = cfg["broker"]

    try:
        broker_obj = build_broker(
            provider=broker_cfg["provider"],
            mode=broker_cfg["mode"],
            credentials=broker_cfg["credentials"],
            extra=broker_cfg.get("options", {}),
        )
    except Exception as e:
        return jsonify({"ok": False,
                        "error": f"Couldn't connect to {broker_cfg['provider']}: {e}"}), 500

    # Open DB (creates file + table on first run).
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    ensure_table_exists(conn)

    results = []
    stats = {"added": 0, "skipped": 0, "no_options": 0, "errors": 0}

    # "Has an active options chain in the next 30 days?" — the broker-agnostic
    # version of what the old Alpaca-py call did. Every broker that implements
    # options support exposes get_available_expirations() per BrokerInterface.
    for symbol in symbols:
        try:
            expirations = broker_obj.get_available_expirations(
                symbol, min_dte=0, max_dte=30
            )
            if not expirations:
                results.append({"symbol": symbol, "status": "no_options",
                                "message": "No active option chain in next 30 days"})
                stats["no_options"] += 1
                continue

            outcome = upsert_symbol(conn, symbol, notes="Onboarded via setup wizard")
            results.append({
                "symbol": symbol,
                "status": outcome,
                "message": f"{len(expirations)} expiration(s) verified",
            })
            if outcome == "inserted":
                stats["added"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            logger.warning("Onboard failed for %s: %s", symbol, e)
            results.append({"symbol": symbol, "status": "error", "message": str(e)})
            stats["errors"] += 1

    conn.close()

    return jsonify({
        "ok": True,
        "mode": mode,
        "total": len(symbols),
        "stats": stats,
        "results": results,
    })


@setup_bp.route("/api/setup/finalize", methods=["POST"])
def api_finalize():
    """Boot the live trading services in-process. After this returns ok=true
    the browser should redirect to `/` and start trading.
    """
    if not config_is_valid():
        return jsonify({"ok": False, "error": "Config still invalid — save your keys first."}), 400

    if _finalize_callback is None:
        return jsonify({
            "ok": False,
            "error": "Server wasn't started in setup-mode; restart with OptionsCanvas.bat / .sh.",
        }), 500

    try:
        ok = _finalize_callback()
    except Exception as e:
        logger.exception("Finalize callback failed")
        return jsonify({"ok": False, "error": f"Service init failed: {e}"}), 500

    if not ok:
        return jsonify({"ok": False, "error": "Service init returned failure — check server logs."}), 500

    return jsonify({"ok": True, "redirect": "/"})
