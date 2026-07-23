"""Tunable security constants for the reseller (نماینده) JSON API.

Kept in one place so operators can tighten/loosen them without hunting
through view code. All values are conservative defaults suitable for a
"reseller builds a Telegram bot on top of this" use case.
"""

# Request must carry X-Timestamp within this many seconds of server time
# (in either direction) — protects against very old, replayed requests and
# catches clients with badly wrong clocks.
TIMESTAMP_WINDOW_SECONDS = 120

# How long a used nonce is remembered server-side. Must be at least
# 2x TIMESTAMP_WINDOW_SECONDS so a nonce can't become valid again (via
# cleanup) while still inside the timestamp window.
NONCE_RETENTION_SECONDS = 600

# Rate limits: (max_requests, window_seconds) per API key.
RATE_LIMIT_GLOBAL = (120, 60)          # all endpoints combined
RATE_LIMIT_CREATE_CONFIG = (10, 60)    # config creation specifically (costly: hits the x-ui panel)
RATE_LIMIT_MUTATIONS = (30, 60)        # create/update/toggle/delete combined

# Max active (non-revoked) API keys a single reseller may hold at once.
MAX_ACTIVE_KEYS_PER_RESELLER = 10
