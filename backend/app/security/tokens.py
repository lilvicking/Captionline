"""Opaque bearer session tokens.

A 256-bit random token is generated with `secrets`, returned to the client once,
and stored only as a SHA-256 hash. Consequences:

* A database leak does not yield usable session tokens.
* Revoking a session row invalidates the token immediately, which a stateless
  JWT cannot do.

This is a Bearer token carried in the Authorization header rather than an httpOnly
cookie, because the Captionline web and API are separate Railway origins. That
keeps SameSite/credential handling simple; the hardening path, if wanted, is to
move to httpOnly `SameSite=None; Secure` cookies plus CSRF protection.
"""

from __future__ import annotations

import hashlib
import secrets

# 32 random bytes -> 256 bits of entropy, URL-safe encoded.
TOKEN_BYTES = 32


def generate_token() -> str:
    """Create a new session token. Only its hash is ever persisted."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hash a token for storage and lookup.

    SHA-256 is appropriate here (unlike for passwords) because the input already
    has full entropy, so the hash is not brute-forceable.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
