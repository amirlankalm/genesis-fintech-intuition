"""Organizer baseline "oracle", JURY SIDE ONLY: correct findings from the closed truth, sent by a normal submit.

judge_adapter.oracle_findings(episode_dir) reads truth.json of the episode directory (never available to a policy)
and builds the findings.json object; this baseline submits it as its first action, so inspection_steps is 0 and a
correct truth gives return 1.0. Give it the directory of exactly the episode the env was reset on.
"""

from __future__ import annotations

from typing import Any

import judge_adapter
from baselines._session import Env


def run(env: Env, observation: dict[str, Any], *, episode_dir: str) -> None:
    """Submit the truth of episode_dir as findings."""
    document = judge_adapter.oracle_findings(episode_dir)
    if document["episode_id"] != observation["manifest"]["episode_id"]:
        raise ValueError("the oracle was given another episode than the one the env was reset on")
    env.step({"name": "submit", "args": {"findings": document}})
