"""Default locations. Public and private episode halves live under different roots.

The teaching episodes ship both halves in this repository on purpose: they are
worked examples with a published answer. Held-out episodes must not. Point
GENESIS_AUDIT_PRIVATE_ROOT (and GENESIS_AUDIT_PUBLIC_ROOT) at directories outside
any agent-readable path, and GENESIS_AUDIT_SECRET_FILE at a file holding the
evaluator's key.
"""

from __future__ import annotations

import os
from pathlib import Path

from .prng import DEV_SECRET

REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_ROOT = Path(os.environ.get("GENESIS_AUDIT_PUBLIC_ROOT") or REPO_ROOT / "episodes" / "public")
PRIVATE_ROOT = Path(os.environ.get("GENESIS_AUDIT_PRIVATE_ROOT") or REPO_ROOT / "episodes" / "private")


def evaluator_secret() -> bytes:
    """The evaluator's key. Without a secret file this is the public dev key, which protects nothing."""
    path = os.environ.get("GENESIS_AUDIT_SECRET_FILE")
    if not path:
        return DEV_SECRET
    secret = Path(path).read_bytes().strip()
    if len(secret) < 16:
        raise ValueError("the evaluator secret must be at least 16 bytes")
    return secret
