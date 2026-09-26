"""Password hashing.

Uses Argon2id via `argon2-cffi`, the reference Argon2 implementation. Argon2id is
the current OWASP first recommendation for password storage, and it resists both
GPU cracking (memory-hard) and side-channel attacks (data-independent).

`pwdlib` was evaluated first and rejected: version 0.3.1 produces valid
`$argon2id$` hashes but its own `verify` cannot identify them, raising
`UnknownHashError` on a hash it just created. That silent asymmetry would have
made every login fail, so `argon2-cffi` is used directly with no wrapper layer.

Plaintext passwords are never stored or logged.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# OWASP-recommended Argon2id parameters (64 MiB, 3 iterations, parallelism 4)
# are argon2-cffi's defaults.
_hasher = PasswordHasher()


class PasswordTooShortError(ValueError):
    """Raised when a candidate password does not meet the minimum length."""


def validate_password_strength(password: str, minimum_length: int) -> None:
    if len(password) < minimum_length:
        raise PasswordTooShortError(
            f"Password must be at least {minimum_length} characters long."
        )


def hash_password(password: str) -> str:
    """Hash a password with Argon2id. The plaintext is never retained."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored hash.

    Returns False for a wrong password, a malformed hash, or a hash produced by a
    different algorithm, so a failure never authenticates anyone.
    """
    if not password_hash:
        return False

    try:
        _hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """True when a stored hash should be upgraded on the next successful login."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, VerificationError):
        return True
