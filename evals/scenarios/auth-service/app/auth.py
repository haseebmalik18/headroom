"""Password hashing (PBKDF2-HMAC-SHA256) and session tokens."""

import hashlib
import hmac
import os
import secrets

from . import telemetry

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or os.urandom(16)
    with telemetry.span("auth.hash_password"):
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    algorithm, iterations, salt, expected = stored.split("$")
    if algorithm != ALGORITHM:
        return False
    with telemetry.span("auth.verify_password"):
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    return hmac.compare_digest(digest.hex(), expected)


def new_token() -> str:
    return secrets.token_urlsafe(32)
