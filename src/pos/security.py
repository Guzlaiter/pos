"""Password hashing utilities (PBKDF2-HMAC-SHA256)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

ITERATIONS = 260_000
ALGORITHM = "pbkdf2_sha256"


def hash_password(password: str) -> str:
    """Create a salted password hash in a self-describing format."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    """Verify a password against a stored hash, in constant time."""
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False
