"""
Broker factory — turns a (provider, mode, credentials) triple into a live
BrokerInterface instance. All instantiation goes through here; no code outside
this module should construct broker classes directly.

Design notes:
  - We import the implementation class lazily from `factory_path` (set in the
    registry) so adding a broker never requires a top-level import edit here.
  - Brokers are expected to expose a `from_credentials(mode, **creds)` classmethod.
    Where they don't (e.g. existing AlpacaBroker, which takes `paper: bool`),
    we adapt at the factory boundary so the registry stays declarative.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Dict

from .broker_interface import BrokerInterface
from .broker_registry import BROKER_REGISTRY, MODE_PAPER, MODE_LIVE, get_broker

logger = logging.getLogger(__name__)


def _import_class(dotted_path: str):
    module_path, _, class_name = dotted_path.rpartition(".")
    if not module_path:
        raise ValueError(f"factory_path must be fully qualified: {dotted_path!r}")
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def build_broker(
    provider: str,
    mode: str,
    credentials: Dict[str, Any],
    extra: Dict[str, Any] | None = None,
) -> BrokerInterface:
    """
    Construct and return a connected BrokerInterface instance.

    Args:
        provider:    Broker ID from BROKER_REGISTRY (e.g. "alpaca").
        mode:        MODE_PAPER or MODE_LIVE.
        credentials: Per-broker credential dict matching `credentials_schema`.
        extra:       Per-broker options (data feed, retry count, etc.).

    Raises:
        KeyError    if provider is not registered.
        ValueError  if mode is not supported by the provider.
    """
    meta = get_broker(provider)

    if mode not in meta["supports_modes"]:
        raise ValueError(
            f"Broker {provider!r} does not support mode {mode!r}. "
            f"Supported: {meta['supports_modes']}"
        )

    cls = _import_class(meta["factory_path"])
    extra = extra or {}

    # ------------------------------------------------------------------
    # Per-broker adaptation. Newer brokers should implement
    # `from_credentials(mode, **creds)` directly and this branch goes away.
    # Until then, we adapt AlpacaBroker's existing (api_key, secret_key, paper)
    # signature here so the registry stays declarative.
    # ------------------------------------------------------------------
    if provider == "alpaca":
        return cls(
            api_key=credentials["api_key"],
            secret_key=credentials["secret_key"],
            paper=(mode == MODE_PAPER),
            data_feed=extra.get("data_feed", "iex"),
        )

    # Generic path for future brokers — they must expose `from_credentials`.
    if hasattr(cls, "from_credentials"):
        return cls.from_credentials(mode=mode, **credentials, **extra)

    raise TypeError(
        f"Broker {provider!r} class {cls.__name__} has no adapter in build_broker "
        "and does not expose from_credentials(mode, **creds)."
    )


def validate_connection(broker: BrokerInterface) -> tuple[bool, str]:
    """Provider-agnostic connection check. Returns (ok, message)."""
    try:
        return broker.validate_connection()
    except Exception as e:
        logger.exception("Broker validation raised")
        return False, str(e)
