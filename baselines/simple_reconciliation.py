"""Organizer baseline "simple reconciliation" (простая сверка): the shortest rule per family.

The decision code is policies/reconciliation_naive.py, unchanged: allocation = receipt amount minus what the ledger
allocated, duplicate = same customer and same total, fx = the rate of the printed date, cutoff = the printed dates.
It ignores the policy text, so valid look-alikes (weekly invoices, split payments, other offsets) defeat it.
"""

from __future__ import annotations

from typing import Any

from baselines._session import Env, run_script

SCRIPT = "reconciliation_naive.py"


def run(env: Env, observation: dict[str, Any]) -> None:
    """Page through invoices, payments and ledger (and fx when needed), then submit once."""
    run_script(SCRIPT, env, observation)
