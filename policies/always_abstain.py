"""Always-abstain baseline: submit an empty findings list at once.

The lazy policy every auditor must beat. It is right on clean books and wrong on
faulty ones, so its mean reward shows how much of a score the clean share alone buys.
"""

from __future__ import annotations

from _client import Session

if __name__ == "__main__":
    Session().submit([])
