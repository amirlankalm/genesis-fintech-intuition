"""Policy side of the tool bridge: JSON lines on stdin/stdout, standard library only.

A policy process never touches episode files. Everything it knows arrives here.
"""

from __future__ import annotations

import json
import sys
from typing import Any


class Session:
    """One episode as seen by a policy."""

    def __init__(self) -> None:
        first = self._receive()
        if first is None or first.get("type") != "reset":
            raise SystemExit("bridge closed before the episode started")
        self.observation: dict[str, Any] = first["observation"]
        self.manifest: dict[str, Any] = self.observation["manifest"]
        self.policy: dict[str, Any] = self.observation["policy"]
        self.steps_remaining: int = self.observation["steps_remaining"]
        self.done = False
        self.reward: float | None = None

    @staticmethod
    def _receive() -> dict[str, Any] | None:
        line = sys.stdin.readline()
        return json.loads(line) if line else None

    def act(self, name: str, **args: Any) -> dict[str, Any]:
        """Send one action and return the observation. Marks the session done at the end."""
        sys.stdout.write(json.dumps({"action": name, "args": args}, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        reply = self._receive()
        if reply is None:
            self.done = True
            return {}
        observation = reply["observation"]
        self.steps_remaining = observation.get("steps_remaining", 0)
        if reply["terminated"] or reply["truncated"]:
            self.done, self.reward = True, reply["reward"]
        return observation

    def list_all(self, table: str) -> list[dict[str, Any]]:
        """Page through a whole table, always keeping one step in reserve for the submit."""
        records: list[dict[str, Any]] = []
        cursor = None
        while not self.done and self.steps_remaining > 1:
            observation = self.act("list_records", table=table, cursor=cursor)
            records.extend(observation.get("records", []))
            cursor = observation.get("next_cursor")
            if cursor is None:
                break
        return records

    def submit(self, findings: list[dict[str, Any]]) -> None:
        if not self.done:
            self.act("submit", findings={"episode_id": self.manifest["episode_id"], "findings": findings})
