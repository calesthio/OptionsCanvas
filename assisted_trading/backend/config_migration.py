"""
Config migration shim.

Old config shape (single-broker, Alpaca-only):
    {
      "alpaca": {
        "api_key": "...", "secret_key": "...",
        "base_url": "https://paper-api.alpaca.markets",
        "data_feed": "iex"
      }
    }

New config shape (multi-broker via registry):
    {
      "broker": {
        "provider": "alpaca",
        "mode": "paper",
        "credentials": {"api_key": "...", "secret_key": "..."},
        "options": {"data_feed": "iex"}
      }
    }

This module accepts EITHER shape and always returns the new normalized shape.
It does NOT write back to disk — we treat the user's config.json as immutable
unless the wizard explicitly saves through /api/setup/save-config. That way
hand-edited configs aren't reformatted under the user's feet.

Once the wizard's save-config endpoint is rewritten to produce the new shape,
new installs land in the new shape natively. Existing installs are migrated
in-memory each boot until the user re-saves through the wizard.
"""

from __future__ import annotations

from typing import Any, Dict


def normalize_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a copy of `raw` with `broker` populated according to the new shape.
    Idempotent — calling on a new-shape config is a no-op.

    Raises ValueError if the input has neither the old nor new shape filled in.
    """
    out = dict(raw)  # shallow copy; we only mutate top-level keys.

    if "broker" in out and out["broker"]:
        # Already new-shape — ensure inner fields exist.
        b = out["broker"]
        b.setdefault("provider", "alpaca")
        b.setdefault("mode", "paper")
        b.setdefault("credentials", {})
        b.setdefault("options", {})
        return out

    # ------------------------------------------------------------------
    # Migrate old shape.
    # ------------------------------------------------------------------
    legacy = out.get("alpaca") or {}
    if not legacy:
        # Nothing to migrate, no broker block — caller will treat this as
        # "needs setup" via the wizard.
        out["broker"] = {
            "provider": "alpaca",
            "mode": "paper",
            "credentials": {},
            "options": {"data_feed": "iex"},
        }
        return out

    base_url = (legacy.get("base_url") or "").lower()
    mode = "paper" if ("paper" in base_url or base_url == "") else "live"

    out["broker"] = {
        "provider": "alpaca",
        "mode": mode,
        "credentials": {
            "api_key": legacy.get("api_key", ""),
            "secret_key": legacy.get("secret_key", ""),
        },
        "options": {
            "data_feed": legacy.get("data_feed", "iex"),
        },
    }

    # Keep `alpaca` block around for visibility / backward reads, but `broker`
    # is now the source of truth.
    return out


def credentials_present(normalized: Dict[str, Any]) -> bool:
    """Returns True iff the normalized config has non-placeholder credentials."""
    b = normalized.get("broker") or {}
    creds = b.get("credentials") or {}
    if not creds:
        return False
    placeholders = {
        "", "YOUR_API_KEY", "YOUR_SECRET_KEY",
        "YOUR_ALPACA_API_KEY", "YOUR_ALPACA_SECRET_KEY",
    }
    return all(
        isinstance(v, str) and v.strip() and v.strip() not in placeholders
        for v in creds.values()
    )
