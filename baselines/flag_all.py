"""Organizer baseline "mass flagging" (массовая пометка): accuse every candidate of every family.

The decision code is policies/flag_all.py, unchanged: after paging the books it takes turns between the four
families (every same-total invoice pair as a duplicate, every referenced invoice as under-allocated, every
foreign receipt as mistranslated, every invoice as a cutoff) up to the 30-finding cap, so it stays a valid
structure and is scored. A sound reward makes it lose.
"""

from __future__ import annotations

from typing import Any

from baselines._session import Env, run_script

SCRIPT = "flag_all.py"


def run(env: Env, observation: dict[str, Any]) -> None:
    run_script(SCRIPT, env, observation)
