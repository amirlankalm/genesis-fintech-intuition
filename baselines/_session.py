"""The policies/_client.py Session interface, spoken over a judge_adapter environment.

The policy scripts in policies/ normally talk JSON lines to the sandboxed bridge. Here the same decision code is
driven in process through `env.step({"name": ..., "args": {...}})`, so the benchmark baselines and our own
policies use one envelope and one set of observations: {"result", "error", "remaining_steps"}.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Protocol

POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


class Env(Protocol):
    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]: ...


class EnvSession:
    """One episode as a policy sees it through the adapter."""

    def __init__(self, env: Env, observation: dict[str, Any]) -> None:
        self.env = env
        self.observation = observation
        self.manifest: dict[str, Any] = observation["manifest"]
        self.policy: dict[str, Any] = observation["policy"]
        self.steps_remaining: int = observation["remaining_steps"]
        self.done = False
        self.reward: float | None = None

    def act(self, name: str, **args: Any) -> dict[str, Any]:
        """Send one action in the official envelope; return the official observation."""
        observation, reward, terminated, truncated, _ = self.env.step({"name": name, "args": args})
        self.steps_remaining = observation["remaining_steps"]
        if terminated or truncated:
            self.done, self.reward = True, reward
        return observation

    def list_all(self, table: str) -> list[dict[str, Any]]:
        """Page through a whole table, always keeping one step in reserve for the submit."""
        records: list[dict[str, Any]] = []
        cursor = None
        while not self.done and self.steps_remaining > 1:
            result = self.act("list_records", table=table, cursor=cursor)["result"]
            if not isinstance(result, dict):
                break
            records.extend(result["records"])
            cursor = result["next_cursor"]
            if cursor is None:
                break
        return records

    def submit(self, findings: list[dict[str, Any]]) -> None:
        if not self.done:
            self.act("submit", findings={"episode_id": self.manifest["episode_id"], "findings": findings})


_SCRIPTS: dict[str, types.ModuleType] = {}


def load_script(filename: str) -> types.ModuleType:
    """Import a policies/ script with its `_client` import bound to this module (loaded once)."""
    if filename not in _SCRIPTS:
        spec = importlib.util.spec_from_file_location(f"_baseline_{Path(filename).stem}", POLICY_DIR / filename)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load policies/{filename}")
        module = importlib.util.module_from_spec(spec)
        shim = types.ModuleType("_client")
        vars(shim)["Session"] = EnvSession
        saved = sys.modules.get("_client")
        sys.modules["_client"] = shim
        try:
            spec.loader.exec_module(module)
        finally:
            if saved is None:
                sys.modules.pop("_client", None)
            else:
                sys.modules["_client"] = saved
        _SCRIPTS[filename] = module
    return _SCRIPTS[filename]


def run_script(filename: str, env: Env, observation: dict[str, Any]) -> None:
    """Play one episode with the decision code of policies/<filename> (its main())."""
    module = load_script(filename)
    session = EnvSession(env, observation)
    vars(module)["Session"] = lambda: session  # the script's Session() now opens this episode
    module.main()
