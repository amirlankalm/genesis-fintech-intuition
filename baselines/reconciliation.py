"""Extra baseline (not one of the four): our rule-following solver.

The decision code is policies/reconciliation.py, unchanged: it applies the published policy (accounts,
open-balance allocation, the fx date and direction rule, the cutoff rule, the duplicate rule) to what the tools
return. It reads no truth.
"""

from __future__ import annotations

from typing import Any

from baselines._session import Env, run_script

SCRIPT = "reconciliation.py"


def run(env: Env, observation: dict[str, Any]) -> None:
    run_script(SCRIPT, env, observation)
