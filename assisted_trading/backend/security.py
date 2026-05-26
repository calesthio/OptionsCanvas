"""
Security layer for OptionsCanvas.

Prevents two attack classes against the locally-hosted server:

1. **Cross-origin requests from any website you visit.** Because the server is
   bound to 127.0.0.1, browsers can still send requests to it from any open
   tab. With `CORS(app)` and no restrictions, a malicious page (a blog post,
   a Discord-embedded link, a compromised ad) could POST to `/api/open_position`
   and place real trades in your account silently. We fix this by restricting
   CORS to only our own origin.

2. **CSRF via simple form posts** that don't trigger CORS preflight (browsers
   send `application/x-www-form-urlencoded` POSTs without preflighting, so a
   misconfigured server can be hit even without `Access-Control-Allow-Origin`).
   We fix this with a per-process CSRF token: the server generates a random
   token at startup, injects it into the served HTML, and requires every
   state-changing request to carry it in an `X-CSRF-Token` header. A
   third-party page has no way to read the token, so it cannot forge a valid
   request even if CORS is somehow misconfigured.

Defense-in-depth — both layers must fail for an attack to succeed.
"""

from __future__ import annotations

import logging
import secrets
from typing import Iterable
from urllib.parse import urlparse

from flask import Flask, abort, request
from flask_cors import CORS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-process CSRF token. Generated once when this module is imported; lives
# for the lifetime of the server process. Rotating on every boot is
# intentional — a fresh process always issues a fresh token, so stale tokens
# in old browser tabs are auto-invalidated and have to refresh.
# ---------------------------------------------------------------------------
CSRF_TOKEN: str = secrets.token_urlsafe(32)

# Endpoints that must always be reachable without a CSRF token. Keep this
# list as small as possible — every entry is an attack surface.
CSRF_EXEMPT_PATHS = {
    "/api/health",   # used by Docker healthcheck + can be checked from outside
}

# State-changing HTTP methods that require a CSRF token. GETs and HEADs are
# protected by CORS alone (browsers block cross-origin reads of the response
# unless the server allows it).
CSRF_REQUIRED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def allowed_origins(port: int) -> list[str]:
    """Build the list of origins the browser is allowed to talk to us from.

    We accept both `127.0.0.1` and `localhost` because users (and some launchers)
    open the app under either name. Both resolve to the same loopback interface,
    so allowing them isn't a real expansion of the threat model.
    """
    return [
        f"http://127.0.0.1:{port}",
        f"http://localhost:{port}",
    ]


def register_security(app: Flask, socketio, *, port: int = 5001) -> None:
    """Wire up CORS + CSRF defenses on the given Flask app + SocketIO server.

    Must be called BEFORE the app starts serving requests.
    """
    origins = allowed_origins(port)
    logger.info("Security: locking CORS to %s", origins)

    # ---- Layer 1: CORS restricted to our own origin --------------------
    CORS(app, origins=origins, supports_credentials=True,
         allow_headers=["Content-Type", "X-CSRF-Token"])

    # SocketIO has its own CORS layer separate from Flask. python-socketio
    # reads `cors_allowed_origins` live during the WebSocket handshake, so
    # we tighten it here AFTER module-load (which used "*" so we wouldn't
    # accidentally reject our own legitimate connections before the port
    # was known).
    #
    # Two access paths because python-socketio exposes this differently
    # across versions. We set BOTH (idempotent) so the active version
    # gets the right value; whichever attribute the live handshake reads,
    # it sees the locked-down allowlist.
    set_count = 0
    try:
        socketio.server.eio.cors_allowed_origins = origins
        set_count += 1
    except AttributeError:
        pass
    try:
        socketio.server.cors_allowed_origins = origins
        set_count += 1
    except AttributeError:
        pass
    if set_count == 0:
        # Library shape changed; HTTP-side CSRF still protects state changes,
        # but loud-warn so it's not silent.
        logger.warning(
            "Could not tighten SocketIO cors_allowed_origins post-init. "
            "WebSocket will accept any origin. HTTP CSRF token still required "
            "for state-changing requests."
        )
    else:
        logger.info("Security: SocketIO cors_allowed_origins locked to %s", origins)

    # ---- Layer 2: CSRF token check on every state-changing request -----
    @app.before_request
    def _enforce_csrf() -> None:
        # GETs / HEADs / OPTIONS are safe — CORS already blocks cross-origin
        # reads from being delivered to attacker JS.
        if request.method not in CSRF_REQUIRED_METHODS:
            return

        # Allowed exemptions (tiny list).
        if request.path in CSRF_EXEMPT_PATHS:
            return

        # The header MUST be present, MUST match. Use compare_digest to avoid
        # timing leaks; the comparison is constant-time across length classes.
        sent = request.headers.get("X-CSRF-Token", "")
        if not sent or not secrets.compare_digest(sent, CSRF_TOKEN):
            logger.warning("Rejecting %s %s — missing/invalid CSRF token (origin=%r)",
                           request.method, request.path, request.headers.get("Origin"))
            abort(403, description="CSRF token missing or invalid")

    # ---- Layer 3: belt + suspenders Origin header check ---------------
    # Browsers send Origin on every state-changing request from a page.
    # If the Origin doesn't match ours, the request is forged.
    @app.before_request
    def _enforce_origin() -> None:
        if request.method not in CSRF_REQUIRED_METHODS:
            return
        if request.path in CSRF_EXEMPT_PATHS:
            return
        origin = request.headers.get("Origin")
        # Some clients (curl, internal SocketIO upgrades) don't send Origin.
        # We only reject when Origin IS present and doesn't match — never
        # require its presence, since that breaks legitimate non-browser tools.
        if origin and origin not in origins:
            logger.warning("Rejecting %s %s — Origin %s not in allowlist",
                           request.method, request.path, origin)
            abort(403, description="Origin not allowed")


def inject_csrf_token(html: str) -> str:
    """Substitute `{{CSRF_TOKEN}}` placeholders in the served HTML with the
    real per-process token. Used by the routes that send index.html / setup.html.

    Placeholder is wrapped in double-braces so it can't be confused with a
    Mustache/Vue template if someone wires those in later.
    """
    return html.replace("{{CSRF_TOKEN}}", CSRF_TOKEN)


def get_csrf_token() -> str:
    """Accessor for tests and any code that needs the token directly."""
    return CSRF_TOKEN
