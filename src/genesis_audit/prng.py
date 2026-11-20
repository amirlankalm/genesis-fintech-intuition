"""A keyed, version-independent random stream.

Python's `random` module is deterministic for a seed, but some of its methods have
changed between versions, and its seed is recoverable from enough output. This
stream is HMAC-SHA256 in counter mode: the same key and label give the same
values on every Python version, and without the key the output says nothing
about the seed.
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")

# A public key gives no secrecy. Private evaluation must pass its own secret, kept outside agent-readable paths.
DEV_SECRET = b"genesis-audit-public-dev-key"


class KeyedStream:
    def __init__(self, key: bytes, label: str) -> None:
        if not key:
            raise ValueError("an empty key gives no protection")
        self._key = key
        self._label = label.encode("utf-8")
        self._counter = 0

    def _block(self) -> bytes:
        message = self._label + b"|" + str(self._counter).encode("ascii")
        self._counter += 1
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def below(self, bound: int) -> int:
        """A uniform integer in [0, bound), by rejection sampling."""
        if bound <= 0:
            raise ValueError("bound must be positive")
        limit = (1 << 64) - ((1 << 64) % bound)
        while True:
            value = int.from_bytes(self._block()[:8], "big")
            if value < limit:
                return value % bound

    def shuffled(self, items: Sequence[T]) -> list[T]:
        """A new list in Fisher-Yates order; the input is not modified."""
        result = list(items)
        for index in range(len(result) - 1, 0, -1):
            other = self.below(index + 1)
            result[index], result[other] = result[other], result[index]
        return result

    def token(self, length: int, alphabet: str) -> str:
        return "".join(alphabet[self.below(len(alphabet))] for _ in range(length))


def keyed_hex(key: bytes, label: str, length: int) -> str:
    """A short keyed digest, for identifiers that must not reveal what they were derived from."""
    return hmac.new(key, label.encode("utf-8"), hashlib.sha256).hexdigest()[:length]
