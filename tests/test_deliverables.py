"""The section 09 deliverables that are files: trajectories.jsonl and the scripted demo."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TRAJECTORIES = ROOT / "trajectories.jsonl"
REQUIRED = ("episode_id", "step", "action", "observation", "reward", "terminated", "truncated")


def _lines() -> list[dict]:
    return [json.loads(line) for line in TRAJECTORIES.read_text(encoding="utf-8").splitlines()]


def _private_tokens() -> set[str]:
    tokens: set[str] = set()
    for truth_file in (ROOT / "episodes" / "private").glob("*/truth.json"):
        for issue in json.loads(truth_file.read_text())["issues"]:
            tokens.add(issue["issue_id"])
    return tokens


def test_trajectories_have_every_field_the_case_names() -> None:
    lines = _lines()
    assert len(lines) > 1000
    for line in lines:
        assert all(key in line for key in REQUIRED), line.keys()
        assert isinstance(line["terminated"], bool) and isinstance(line["truncated"], bool)
        assert isinstance(line["reward"], float)
    policies = {line["policy"] for line in lines}
    assert {"random_explorer", "simple_reconciliation", "flag_all", "oracle"} <= policies


def test_trajectories_carry_no_private_truth() -> None:
    text = TRAJECTORIES.read_text(encoding="utf-8")
    for marker in ("acceptable_evidence_sets", "expected_amount_minor", "provenance", "truth.json"):
        assert marker not in text
    leaked = [token for token in _private_tokens() if token in text]
    assert leaked == []


def test_trajectories_regenerate_exactly(tmp_path: Path) -> None:
    out = tmp_path / "trajectories.jsonl"
    done = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "judge_run.py"), "--mode", "train", "--summary", str(tmp_path / "s.json"),
         "--trajectories", str(out), "--export-root", str(tmp_path / "episodes")],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=600,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-2000:]
    assert out.read_bytes() == TRAJECTORIES.read_bytes()


@pytest.mark.skipif(not (ROOT / "demo" / "demo.py").exists(), reason="the demo is not part of this tree")
def test_the_demo_runs_end_to_end() -> None:
    done = subprocess.run(
        [sys.executable, str(ROOT / "demo" / "demo.py")],
        cwd=ROOT, capture_output=True, text=True, check=False, timeout=300, env={**os.environ, "DEMO_PACE": "0"},
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-2000:]
    assert "return=0.9800" in done.stdout and "tp=None" in done.stdout
