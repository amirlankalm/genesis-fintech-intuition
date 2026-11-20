"""A scripted, narrated walk through the environment, made to be recorded (see demo/demo.tape).

Run from the repository root:  uv run python demo/demo.py
Set DEMO_PACE=0 to run it without pauses (the test suite does).
"""

from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

import judge_adapter  # noqa: E402
from baselines import flag_all, reconciliation  # noqa: E402

PACE = float(os.environ.get("DEMO_PACE", "1.0"))
BOLD, DIM, GREEN, RED, CYAN, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[36m", "\033[0m"
SEED = 2026
CONFIG = {
    "generator": {"invoices": 30, "ledger_rows": 300},
    "inject": {
        "duplicate_invoice": 1,
        "payment_allocation_missing": 1,
        "fx_mismatch_date": 1,
        "cutoff": 1,
        "interactions": [{"name": "cutoff_and_allocation", "allocation": "partial", "receipt_currency": "foreign"}],
    },
}


def pause(seconds: float = 1.0) -> None:
    time.sleep(seconds * PACE)


def title(text: str) -> None:
    print(f"\n{BOLD}{CYAN}━━ {text} {'━' * max(3, 70 - len(text))}{RESET}")
    pause(0.8)


def say(text: str) -> None:
    print(f"{DIM}# {text}{RESET}")
    pause(0.6)


def show(value: Any, limit: int = 900) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=1)
    print(text if len(text) <= limit else text[:limit] + f"\n{DIM}… ({len(text) - limit} more characters){RESET}")
    pause(1.0)


def act(env: Any, name: str, **args: Any) -> dict[str, Any]:
    action = {"name": name, "args": args}
    print(f"{BOLD}step{RESET} {json.dumps(action, ensure_ascii=False)}")
    observation, reward, terminated, truncated, info = env.step(action)
    print(f"  {DIM}reward={reward} terminated={terminated} truncated={truncated} info={info}{RESET}")
    return observation


def generate(directory: str) -> None:
    title("1. A synthetic company with hidden errors")
    say(f"generate_episode(seed={SEED}, config, output_dir): one company, one month, errors injected on purpose")
    show(CONFIG)
    judge_adapter.generate_episode(SEED, CONFIG, directory)
    files = sorted(p.name for p in Path(directory).iterdir())
    print(f"files: {', '.join(files)}")
    manifest = json.loads((Path(directory) / "manifest.json").read_text())
    show(
        {
            key: manifest[key]
            for key in ("episode_id", "base_currency", "period_start", "period_end", "timezone", "counts")
        }
    )
    say("truth.json and provenance.json stay with the jury: the agent never sees them")


def explore(directory: str) -> None:
    title("2. The agent's view: five narrow tools, 100 steps")
    env = judge_adapter.make_env()
    observation, info = env.reset(SEED, {"mode": "closed", "episode_dir": directory, "team_config": {}})
    say(f"first observation keys: {sorted(observation)}; remaining_steps={observation['remaining_steps']}; info={info}")
    page = act(env, "list_records", table="ledger", cursor=None, limit=3)
    show(page)
    invoices = act(env, "list_records", table="invoices", cursor=None, limit=1)["result"]["records"]
    show(act(env, "get_document", doc_id=invoices[0]["doc_id"]), limit=600)
    show(act(env, "calculator", expression="0.1+0.2"))
    say("the calculator is a parser for decimal arithmetic, not eval:")
    show(act(env, "calculator", expression="__import__('os').listdir('/')"))
    say("an unknown id is a bounded error and still costs a step:")
    show(act(env, "get_record", table="invoices", id="INV-DOES-NOT-EXIST"))


def solve(directory: str) -> None:
    title("3. A rule-following solver, scored in closed mode")
    say("it pages through the four tables and applies the four rules published in policy.json; it reads no truth")
    env = judge_adapter.make_env()
    observation, _ = env.reset(SEED, {"mode": "closed", "episode_dir": directory, "team_config": {}})
    start = time.monotonic()
    reconciliation.run(env, observation)
    report = env.evaluator_report()
    score = report["score"]
    say(
        f"the policy saw reward 0.0 at every step (closed mode); the jury sees the real score after {time.monotonic() - start:.2f} s:"
    )
    show({key: score[key] for key in ("tp", "fp", "fn", "f1", "reward") if key in score})
    say(f"inspection steps used: {report['inspection_steps']} of 100")
    for verdict in report["findings"][:6]:
        mark = f"{GREEN}✓{RESET}" if verdict["matched_issue_id"] else f"{RED}✗{RESET}"
        print(f"  {mark} finding {verdict['index']}: {', '.join(verdict['reasons'])}")
    pause(1.5)


def attack(directory: str) -> None:
    title("4. Attacks on the reward: none of them pays")
    good = judge_adapter.oracle_findings(directory)
    first = good["findings"][0]
    cases: list[tuple[str, dict[str, Any]]] = [("every finding right, 10 inspection steps", good)]
    repeated = copy.deepcopy(good)
    repeated["findings"].append(copy.deepcopy(first))
    cases.append(("the same finding submitted twice", repeated))
    currency = copy.deepcopy(good)
    currency["findings"][0]["currency"] = currency["findings"][0]["currency"].lower()
    cases.append(("one currency written in lower case", currency))
    invented = copy.deepcopy(good)
    invented["findings"][0]["evidence_ids"] = [*invented["findings"][0]["evidence_ids"][:9], "DOC-INVENTED"]
    cases.append(("one invented evidence id", invented))
    persuasive = copy.deepcopy(good)
    persuasive["findings"] = [
        {
            **first,
            "type": "cutoff" if first["type"] != "cutoff" else "fx_mismatch",
            "explanation": "Trust me: I am certain, the auditor's manual says so.",
        }
    ]
    cases.append(("a wrong type with a persuasive explanation", persuasive))
    too_many = {"episode_id": good["episode_id"], "findings": [copy.deepcopy(first)] * 31}
    cases.append(("31 findings (the limit is 30): malformed", too_many))
    for label, findings in cases:
        result = judge_adapter.score_episode(directory, findings, 10)
        colour = GREEN if result["return"] > 0.9 else RED
        print(
            f"  {label:<46} tp={result['tp']} fp={result['fp']} fn={result['fn']}  {colour}return={result['return']:.4f}{RESET}"
        )
        pause(0.9)
    say("flag-all: every record flagged with every type, as many findings as the limit allows")
    env = judge_adapter.make_env()
    observation, _ = env.reset(SEED, {"mode": "closed", "episode_dir": directory, "team_config": {}})
    flag_all.run(env, observation)
    score = env.evaluator_report()["score"]
    print(
        f"  flag-all {' ' * 38} tp={score['tp']} fp={score['fp']} fn={score['fn']}  {RED}return={score['reward']:.4f}{RESET}"
    )
    pause(1.5)


def main() -> None:
    print(f"{BOLD}Genesis FinTech · an RL environment for financial-audit models · team Intuition{RESET}")
    pause(1.0)
    with tempfile.TemporaryDirectory(prefix="genesis-demo-") as directory:
        generate(directory)
        explore(directory)
        solve(directory)
        attack(directory)
    title("Done")
    say("same seed, config and actions → the same records, transitions and rewards, byte for byte")


if __name__ == "__main__":
    main()
