"""
Broker registry — single source of metadata for every broker the platform can
connect to. Used by:
  - The setup wizard (renders the credential form dynamically)
  - The broker factory (knows which class to instantiate)
  - Docs / introspection (lists available brokers in /api/setup/brokers)

To add a new broker:
  1. Implement assisted_trading/backend/<broker>_broker.py with a class that
     subclasses BrokerInterface and exposes a `from_credentials(mode, **creds)`
     classmethod.
  2. Register it in BROKER_REGISTRY below.
  3. (No frontend changes required — the wizard renders from this metadata.)
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Credential field types accepted by the wizard. Used by setup.html to render
# the right HTML input for each field.
# ---------------------------------------------------------------------------
FIELD_TEXT = "text"
FIELD_PASSWORD = "password"
FIELD_NUMBER = "number"

# ---------------------------------------------------------------------------
# Mode constants.
# ---------------------------------------------------------------------------
MODE_PAPER = "paper"
MODE_LIVE = "live"


# ---------------------------------------------------------------------------
# Registry. Each entry describes one broker.
#
#   id                — short slug used in config.broker.provider
#   display_name      — shown in the wizard
#   factory_path      — "module.ClassName" — class must expose:
#                         classmethod from_credentials(mode, **creds) -> BrokerInterface
#                       (today AlpacaBroker uses a thin shim — see broker_factory.py)
#   supports_modes    — list of MODE_* values
#   supports_options  — bool. Brokers that don't support US options are filtered
#                       out of the wizard so users can't pick them by mistake.
#   credentials_schema — ordered list of fields the wizard renders
#   docs_url          — link the wizard surfaces under the form
#   notes             — short hint shown below the form
# ---------------------------------------------------------------------------
BROKER_REGISTRY: Dict[str, Dict[str, Any]] = {
    "alpaca": {
        "id": "alpaca",
        "display_name": "Alpaca",
        "factory_path": "assisted_trading.backend.alpaca_broker.AlpacaBroker",
        "supports_modes": [MODE_PAPER, MODE_LIVE],
        "supports_options": True,
        "credentials_schema": [
            {"key": "api_key",    "label": "API Key ID",
             "type": FIELD_TEXT,     "required": True, "placeholder": "PK..."},
            {"key": "secret_key", "label": "Secret Key",
             "type": FIELD_PASSWORD, "required": True, "placeholder": "(hidden)"},
        ],
        "options": {
            "data_feed": {
                "label": "Market data feed",
                "choices": ["iex", "sip"],
                "default": "iex",
                "notes": "IEX is free. SIP requires a paid Alpaca subscription.",
            },
        },
        "docs_url": "https://app.alpaca.markets/paper/dashboard/overview",
        "notes": (
            "Paper and live use *different* API key pairs — generate them under the "
            "appropriate section of the Alpaca dashboard."
        ),
    },
    "tradier": {
        "id": "tradier",
        "display_name": "Tradier",
        "factory_path": "assisted_trading.backend.tradier_broker.TradierBroker",
        "supports_modes": [MODE_PAPER, MODE_LIVE],
        "supports_options": True,
        "credentials_schema": [
            {"key": "access_token", "label": "Access Token (Bearer)",
             "type": FIELD_PASSWORD, "required": True,
             "placeholder": "Token from Tradier API settings"},
            {"key": "account_id",   "label": "Account ID",
             "type": FIELD_TEXT,     "required": True,
             "placeholder": "VA00000000",
             "help": "Found in your Tradier dashboard. Each token may scope multiple accounts."},
        ],
        "docs_url": "https://documentation.tradier.com/",
        "notes": (
            "Sandbox (paper) and production (live) use SEPARATE access tokens — "
            "generate each one from its own section of your Tradier account API settings."
        ),
    },
    # ------------------------------------------------------------------
    # Future brokers — schema sketched out so adding them is mechanical.
    # Commented out so they don't appear in the wizard until implemented.
    # ------------------------------------------------------------------
    # "ibkr": {
    #     "id": "ibkr",
    #     "display_name": "Interactive Brokers",
    #     "factory_path": "assisted_trading.backend.ibkr_broker.IBKRBroker",
    #     "supports_modes": [MODE_PAPER, MODE_LIVE],
    #     "supports_options": True,
    #     "credentials_schema": [
    #         {"key": "host",      "label": "TWS / Gateway Host",
    #          "type": FIELD_TEXT,   "default": "127.0.0.1"},
    #         {"key": "port",      "label": "Port",
    #          "type": FIELD_NUMBER, "default": 7497,
    #          "help": "7497=paper TWS, 7496=live TWS, 4002=paper Gateway, 4001=live Gateway"},
    #         {"key": "client_id", "label": "Client ID",
    #          "type": FIELD_NUMBER, "default": 1},
    #     ],
    #     "docs_url": "https://www.interactivebrokers.com/en/trading/tws.php",
    #     "notes": "Requires TWS or IB Gateway running locally.",
    # },
}


def list_brokers() -> List[Dict[str, Any]]:
    """Return a public list of broker metadata, safe to ship to the wizard frontend."""
    return [_public_view(b) for b in BROKER_REGISTRY.values()]


def get_broker(provider: str) -> Dict[str, Any]:
    if provider not in BROKER_REGISTRY:
        raise KeyError(f"Unknown broker provider: {provider!r}. "
                       f"Known: {list(BROKER_REGISTRY.keys())}")
    return BROKER_REGISTRY[provider]


def _public_view(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Strip factory_path (implementation detail) for safe API exposure."""
    return {k: v for k, v in meta.items() if k != "factory_path"}
