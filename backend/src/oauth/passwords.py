"""Password hashing for email/password accounts: scrypt from the standard library.

Stored as `scrypt$<n>$<r>$<p>$<salt>$<hash>` (base64), so the cost can be raised
later without breaking existing hashes. Plain passwords are never stored or logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

N, R, P = 2**14, 8, 1  # ~16 MB and tens of milliseconds per hash
KEY_BYTES = 32
MAX_N = 2**20  # refuse stored parameters that would exhaust memory


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                          dklen=KEY_BYTES, maxmem=256 * 1024 * 1024)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    return f"scrypt${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def verify_password(password: str, stored: str) -> bool:
    """Whether `password` matches `stored`; False for any malformed hash."""
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        n, r, p = int(n), int(r), int(p)
        if scheme != "scrypt" or not (2 <= n <= MAX_N and 1 <= r <= 32 and 1 <= p <= 16):
            return False
        actual = _derive(password, base64.b64decode(salt), n, r, p)
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# Checked against when the email is unknown, so a wrong email takes as long as a wrong password.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
