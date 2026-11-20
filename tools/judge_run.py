"""Run the benchmark baselines through judge_adapter and measure them.

    uv run python tools/judge_run.py                      # shipped train + dev episodes, closed mode
    uv run python tools/judge_run.py --episode-dir D ...  # any flat episode directories
    uv run python tools/judge_run.py --mode train --summary S.json --trajectories T.jsonl

Shipped episodes are first exported to flat directories (6 public files + truth.json + provenance.json) under
--export-root. Every run: make_env() -> reset(config={"mode", "episode_dir", "team_config": {}}) -> the baseline
plays with {"name", "args"} actions -> score_episode(episode_dir, submitted findings, inspection_steps). It records
tp, fp, fn, precision, recall, f1, return, inspection steps and wall time, and cross-checks score_episode against
the environment's own evaluator report. Writes a JSON summary and a trajectories.jsonl in the official shapes.
Nothing is written under docs/.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # the repo root: judge_adapter and baselines

import judge_adapter
from baselines import flag_all, oracle, random_explorer, reconciliation, simple_reconciliation
from genesis_audit import paths, shipped

ROOT = Path(__file__).resolve().parents[1]
Runner = Callable[[Any, dict[str, Any], str], None]
POLICIES: dict[str, tuple[Runner, dict[str, Any]]] = {
    "random_explorer": (lambda env, obs, _dir: random_explorer.run(env, obs), {"seed": random_explorer.SEED}),
    "simple_reconciliation": (lambda env, obs, _dir: simple_reconciliation.run(env, obs), {}),
    "flag_all": (lambda env, obs, _dir: flag_all.run(env, obs), {}),
    "oracle": (lambda env, obs, directory: oracle.run(env, obs, episode_dir=directory), {"jury_side": True}),
    "reconciliation": (lambda env, obs, _dir: reconciliation.run(env, obs), {"extra": True}),
}
METRICS = ("tp", "fp", "fn", "precision", "recall", "f1", "return", "inspection_steps", "wall_time_s")
DEFAULT_OUT = ROOT / "out" / "judge"


class Recorder:
    """Wraps a JudgeEnv: records what the policy sent and saw, in the official trajectory shape."""

    def __init__(self, env: judge_adapter.JudgeEnv, base: dict[str, Any]) -> None:
        self.env, self.base = env, base
        self.lines: list[dict[str, Any]] = []
        self.inspection_steps = 0
        self.submitted: dict[str, Any] | None = None  # the submit action's args, if the policy submitted
        self.over = False

    def record(self, action: Any, observation: dict, reward: float, terminated: bool, truncated: bool) -> None:
        self.lines.append({**self.base, "step": len(self.lines), "action": action, "observation": observation,
                           "reward": reward, "terminated": terminated, "truncated": truncated})  # fmt: skip

    def step(self, action: dict) -> tuple[dict, float, bool, bool, dict]:
        is_submit = isinstance(action, dict) and action.get("name") == "submit"
        if not self.over:
            if is_submit:
                self.submitted = action.get("args") if isinstance(action.get("args"), dict) else {}
            else:
                self.inspection_steps += 1
        observation, reward, terminated, truncated, info = self.env.step(action)
        self.over = self.over or terminated or truncated
        self.record(json.loads(json.dumps(action)), observation, reward, terminated, truncated)
        return observation, reward, terminated, truncated, info


def export_shipped(names: Iterable[str], root: Path) -> list[tuple[str, Path]]:
    """Copy shipped episodes into flat directories root/<name>/ (8 files)."""
    exported = []
    for name in names:
        directory = root / name
        directory.mkdir(parents=True, exist_ok=True)
        for half in (paths.PUBLIC_ROOT / name, paths.PRIVATE_ROOT / name):
            for entry in sorted(half.iterdir()):
                if entry.name in (*judge_adapter.EPISODE_FILE_NAMES, "truth.json", "provenance.json"):
                    shutil.copyfile(entry, directory / entry.name)
        exported.append((shipped.split_of(name), directory))
    return exported


def run_one(policy: str, split: str, directory: Path, mode: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    play, labels = POLICIES[policy]
    env = judge_adapter.make_env()
    started = time.perf_counter()
    observation, _info = env.reset(seed=None, config={"mode": mode, "episode_dir": str(directory), "team_config": {}})
    episode_id = observation["manifest"]["episode_id"]
    run_id = f"{policy}/{directory.name}/{mode}"
    recorder = Recorder(env, {"run_id": run_id, "policy": policy, "split": split, "mode": mode,
                              "episode_id": episode_id, **({"policy_seed": labels["seed"]} if "seed" in labels else {})})  # fmt: skip
    recorder.record(None, observation, 0.0, False, False)
    play(recorder, observation, str(directory))
    wall_time = time.perf_counter() - started
    # A policy that stops without submitting: the jury counts empty findings (and the env has no report yet).
    report = env.evaluator_report() if recorder.over else None
    cause = report["termination_cause"] if report else "no_submission"
    findings: Any = (recorder.submitted or {}).get("findings") if recorder.submitted is not None else {"findings": []}
    if cause in ("step_limit", "wall_time"):
        findings = {"findings": []}
    score = judge_adapter.score_episode(str(directory), findings, recorder.inspection_steps)
    checks = (
        {}
        if report is None
        else {
            "inspection_steps_match": recorder.inspection_steps == report["inspection_steps"],
            "return_matches": score["return"] == report["score"]["reward"],
            "counts_match": all(score[key] == report["score"].get(key) for key in ("tp", "fp", "fn")),
        }
    )
    row = {"run_id": run_id, "policy": policy, "split": split, "episode_dir": directory.name, "episode_id": episode_id,
           "mode": mode, **{key: score[key] for key in METRICS[:7]}, "inspection_steps": recorder.inspection_steps,
           "wall_time_s": round(wall_time, 6), "termination_cause": cause,
           "checks": checks, **labels}  # fmt: skip
    return row, recorder.lines


def mean(values: list[Any]) -> float | None:
    numbers = [value for value in values if value is not None]
    return sum(numbers) / len(numbers) if numbers else None


def summarise(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for policy in POLICIES:
        mine = [row for row in rows if row["policy"] == policy]
        if mine:
            out[policy] = {"runs": len(mine), **{f"mean_{key}": mean([row[key] for row in mine]) for key in METRICS}}
            out[policy]["max_wall_time_s"] = max(row["wall_time_s"] for row in mine)
    return out


def print_table(means: dict[str, dict[str, Any]]) -> None:
    header = ["policy", "runs", *METRICS]
    print(" | ".join(header))
    for policy, values in means.items():
        cells = [policy, str(values["runs"])]
        cells += ["-" if values[f"mean_{key}"] is None else f"{values[f'mean_{key}']:.4f}" for key in METRICS]
        print(" | ".join(cells))


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--episode-dir", action="append", default=[], help="a flat episode directory (repeatable)")
    parser.add_argument("--splits", nargs="+", default=["train", "dev"], help="shipped splits when no --episode-dir")
    parser.add_argument("--mode", choices=judge_adapter.MODES, default="closed")
    parser.add_argument("--policies", nargs="+", choices=list(POLICIES), default=list(POLICIES))
    parser.add_argument("--export-root", type=Path, default=DEFAULT_OUT / "episodes")
    parser.add_argument("--summary", type=Path, default=DEFAULT_OUT / "summary.json")
    parser.add_argument("--trajectories", type=Path, default=DEFAULT_OUT / "trajectories.jsonl")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    for target in (args.summary, args.trajectories, args.export_root):
        if (ROOT / "docs") in (target.resolve(), *target.resolve().parents):
            raise SystemExit("judge_run never writes under docs/ (pinned artifacts)")
    if args.episode_dir:
        episodes = [("given", Path(directory)) for directory in args.episode_dir]
    else:
        names = [name for split in args.splits for name in shipped.SPLITS[split]]
        episodes = export_shipped(names, args.export_root)
    rows, lines = [], []
    for policy in args.policies:
        for split, directory in episodes:
            row, trajectory = run_one(policy, split, directory, args.mode)
            rows.append(row)
            lines.extend(trajectory)
    means = summarise(rows)
    failed = [row["run_id"] for row in rows if not all(row["checks"].values())]
    summary = {"adapter_version": judge_adapter.ADAPTER_VERSION, "env_version": judge_adapter.ENV_VERSION,
               "mode": args.mode, "episodes": [str(directory) for _, directory in episodes],
               "nondeterministic": ["wall_time_s", "mean_wall_time_s", "max_wall_time_s"],
               "per_policy": means, "runs": rows, "cross_check_failures": failed}  # fmt: skip
    for target in (args.summary, args.trajectories):
        target.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with args.trajectories.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n")
    print_table(means)
    print(f"runs {len(rows)}, trajectory lines {len(lines)}, cross-check failures {len(failed)}")
    print(f"summary -> {args.summary}\ntrajectories -> {args.trajectories}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
