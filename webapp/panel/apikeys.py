"""API key generation & verification for the reseller (نماینده) API.

Format of a raw key handed to the reseller (shown to them exactly once,
right after creation): `bb_<key_id>_<secret>`

- `key_id`  — a random public identifier (16 hex chars). Stored in plain
  text in the DB and used to look the key up quickly (indexed).
- `secret`  — a high-entropy random secret (~43 url-safe chars). NEVER
  stored in plain text — only its SHA-256 hash (`key_hash`) is persisted.
  Because the secret has enough entropy on its own, a plain fast hash is
  fine here (unlike a user password, it isn't guessable/brute-forceable
  offline in any practical sense) — this mirrors how GitHub/Stripe/etc.
  handle personal access tokens.

Splitting the key into an indexable `key_id` and a secret this way lets
the server find the right row with a single indexed lookup instead of
hashing-and-comparing every stored key on every request.
"""

import hashlib
import hmac
import secrets

KEY_PREFIX = "bb"
KEY_ID_BYTES = 8      # -> 16 hex chars
SECRET_BYTES = 32     # -> ~43 url-safe base64 chars


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_id, key_hash). Persist key_id + key_hash;
    show raw_key to the user exactly once and then discard it."""
    key_id = secrets.token_hex(KEY_ID_BYTES)
    secret = secrets.token_urlsafe(SECRET_BYTES)
    raw_key = f"{KEY_PREFIX}_{key_id}_{secret}"
    return raw_key, key_id, hash_secret(secret)


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def parse_api_key(raw_key: str) -> tuple[str, str] | None:
    """Splits a raw `bb_<key_id>_<secret>` key into (key_id, secret), or
    None if it doesn't look like one of ours at all."""
    if not raw_key:
        return None
    parts = raw_key.strip().split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_PREFIX or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def verify_secret(secret: str, key_hash: str) -> bool:
    return hmac.compare_digest(hash_secret(secret), key_hash)


def mask_key_id(key_id: str) -> str:
    """For display in the UI: `bb_a1b2c3d4********`"""
    if len(key_id) <= 8:
        return f"{KEY_PREFIX}_{key_id}"
    return f"{KEY_PREFIX}_{key_id[:8]}{'*' * (len(key_id) - 8)}"
