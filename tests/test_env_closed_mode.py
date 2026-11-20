"""Closed (eval) mode, the step and time budgets, and oversized submissions (Block 1: C16-C19, ADP-time-limit,
CRIT-oversize-submit), on an environment built in memory from a loaded episode (the adapter's path)."""

from __future__ import annotations

import io
import json
import queue
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from genesis_audit import paths
from genesis_audit.bridge import _read_actions, decode_action
from genesis_audit.env import BRIDGE_REJECT, BROKEN_SUBMIT, MAX_ACTION_BYTES, AuditEnv
from genesis_audit.episodes import InMemorySource, LoadedEpisode, load_episode_dir
from genesis_audit.errors import LifecycleError
from genesis_audit.store import is_valid_id

NAME = "fixture_duplicate"  # one duplicate_invoice issue
CONFIG = {"episode": "episode"}


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> LoadedEpisode:
    directory = tmp_path_factory.mktemp("jury") / NAME
    directory.mkdir()
    for root in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT):
        for entry in (root / NAME).iterdir():
            shutil.copy(entry, directory / entry.name)
    return load_episode_dir(directory, strict=False)


def oracle_submit(loaded: LoadedEpisode) -> dict[str, Any]:
    findings = [
        {"type": issue.type, "affected_ids": sorted(issue.affected_ids),
         "claimed_amount_minor": issue.expected_amount_minor, "currency": issue.currency,
         "evidence_ids": sorted(min(issue.acceptable_evidence_sets, key=len)), "explanation": "oracle"}
        for issue in loaded.truth
    ]  # fmt: skip
    document = {"episode_id": loaded.public.manifest["episode_id"], "findings": findings}
    return {"action": "submit", "args": {"findings": document}}


CALC = {"action": "calculator", "args": {"expression": "0.1+0.2"}}
UNKNOWN_ID = {"action": "get_record", "args": {"table": "ledger", "id": "no such row"}}


def test_adp_make_env_from_a_loaded_episode_and_repeated_reset_restarts(loaded: LoadedEpisode) -> None:
    env = AuditEnv.from_episode(loaded)
    first, _ = env.reset(config=CONFIG)
    env.step(CALC)
    again, _ = env.reset(seed=123, config={**CONFIG, "mode": "eval"})  # a seed is accepted and ignored
    assert again == first and again["steps_remaining"] == 100
    assert env.evaluator_view() is loaded
    assert InMemorySource(loaded).load("anything") is loaded


def test_c19_closed_reward_is_numeric_zero_at_every_step_and_info_is_empty(loaded: LoadedEpisode) -> None:
    env = AuditEnv.from_episode(loaded)
    _, info = env.reset(config={**CONFIG, "mode": "eval"})
    assert info == {}
    transitions = [env.step(action) for action in (CALC, UNKNOWN_ID, {"action": "nope", "args": {}})]
    transitions.append(env.step(oracle_submit(loaded)))
    transitions.append(env.step(CALC))  # after the end
    for _, reward, _, _, step_info in transitions:
        assert type(reward) is float and reward == 0.0 and step_info == {}
    assert transitions[3][2] is True  # the submit terminated the episode
    report = env.evaluator_report()
    assert report["score"]["reward"] == pytest.approx(0.994, abs=1e-9)
    assert report["counts"] == {"tp": 1, "fp": 0, "fn": 0}
    said = json.dumps([t["reward"] for t in env.trajectory()[1:]] + [t["info"] for t in env.trajectory()])
    assert "0.994" not in said and "withheld" not in said


@pytest.mark.parametrize("ending", ["malformed", "step_limit", "wall_time", "forced"])
def test_c19_every_closed_ending_reports_zero(loaded: LoadedEpisode, ending: str) -> None:
    clock = FakeClock()
    env = AuditEnv.from_episode(loaded, clock=clock)
    env.reset(config={**CONFIG, "mode": "eval"})
    if ending == "malformed":
        last = env.step({"action": "submit", "args": None})
    elif ending == "step_limit":
        last = [env.step(CALC) for _ in range(100)][-1]
    elif ending == "wall_time":
        clock.now += 61
        last = env.step(oracle_submit(loaded))
    else:
        last = env.truncate("policy_exit")
    assert last[1] == 0.0 and type(last[1]) is float and last[4] == {}
    assert env.evaluator_report()["score"]["reward"] == -1.0  # the true reward stays with the evaluator


def submit_of(loaded: LoadedEpisode, findings: list[dict[str, Any]]) -> dict[str, Any]:
    document = {"episode_id": loaded.public.manifest["episode_id"], "findings": findings}
    return {"action": "submit", "args": {"findings": document}}


def test_c19_closed_mode_cannot_tell_a_perfect_submission_from_a_wrong_or_empty_one(loaded: LoadedEpisode) -> None:
    """C19, both directions: the true rewards differ, yet everything the policy receives (reset info, every
    observation, reward, flag and info, and the recorded transitions apart from its own action) is identical."""
    perfect = oracle_submit(loaded)["args"]["findings"]["findings"]
    wrong = [dict(perfect[0], claimed_amount_minor=perfect[0]["claimed_amount_minor"] + 1)]
    seen, true_rewards = {}, {}
    for label, findings in (("perfect", perfect), ("wrong", wrong), ("empty", [])):
        env = AuditEnv.from_episode(loaded)
        _, info = env.reset(config={**CONFIG, "mode": "eval"})
        steps = [env.step(CALC), env.step(UNKNOWN_ID), env.step(submit_of(loaded, findings)), env.step(CALC)]
        recorded = [{key: value for key, value in t.items() if key != "action"} for t in env.trajectory()]
        seen[label] = (info, steps, recorded)
        true_rewards[label] = env.evaluator_report()["score"]["reward"]
    assert seen["perfect"] == seen["wrong"] == seen["empty"]
    assert true_rewards["perfect"] == pytest.approx(1 - 0.002 * 2, abs=1e-9)
    assert true_rewards["wrong"] == true_rewards["empty"] == -1.0


def test_p01_replaying_the_same_actions_on_a_loaded_directory_reproduces_every_transition(
    loaded: LoadedEpisode, tmp_path: Path
) -> None:
    """Block 4 pass condition 1: the same actions on the same episode reproduce records, transitions and rewards
    exactly, whether the environment is reused (reset keeps nothing) or the directory is loaded afresh."""
    directory = tmp_path / NAME
    directory.mkdir()
    for root in (paths.PUBLIC_ROOT, paths.PRIVATE_ROOT):
        for entry in (root / NAME).iterdir():
            shutil.copy(entry, directory / entry.name)

    def run(env: AuditEnv, mode: str) -> tuple[list[Any], list[dict[str, Any]], dict[str, Any]]:
        env.reset(seed=5, config={**CONFIG, "mode": mode})
        transitions, cursor = [], None
        while True:  # walk every ledger page through the issued cursors
            step = env.step({"action": "list_records", "args": {"table": "ledger", "cursor": cursor, "limit": 7}})
            transitions.append(step)
            cursor = step[0]["next_cursor"]
            if cursor is None:
                break
        transitions += [env.step(UNKNOWN_ID), env.step(CALC), env.step(oracle_submit(loaded)), env.step(CALC)]
        report = env.evaluator_report()
        report.pop("nondeterministic")
        return transitions, env.trajectory(), report

    for mode in ("train", "eval"):
        reused = AuditEnv.from_episode(loaded)
        first, second = run(reused, mode), run(reused, mode)
        fresh = run(AuditEnv.from_episode(load_episode_dir(directory, strict=False)), mode)
        assert first == second == fresh
        assert first[2]["counts"] == {"tp": 1, "fp": 0, "fn": 0}


def test_c16_submit_as_action_100_is_accepted(loaded: LoadedEpisode) -> None:
    env = AuditEnv.from_episode(loaded)
    env.reset(config=CONFIG)
    for _ in range(99):
        assert env.step(CALC)[2:4] == (False, False)
    observation, reward, terminated, truncated, _ = env.step(oracle_submit(loaded))
    assert (terminated, truncated, observation["steps_remaining"]) == (True, False, 0)
    report = env.evaluator_report()
    assert (report["termination_cause"], report["inspection_steps"], report["steps_used"]) == ("submitted", 99, 100)
    assert reward == pytest.approx(2 * 1 - 1 - 0.002 * 99, abs=1e-9)


def test_c17_one_hundred_inspections_truncate_with_empty_findings(loaded: LoadedEpisode) -> None:
    env = AuditEnv.from_episode(loaded)
    env.reset(config=CONFIG)
    for step in range(1, 101):
        _, _, terminated, truncated, _ = env.step(CALC)
        assert (terminated, truncated) == (False, step == 100)
    late = env.step(oracle_submit(loaded))  # nothing is added afterwards
    assert late[0]["error"]["code"] == "episode_over"
    report = env.evaluator_report()
    assert report["termination_cause"] == "step_limit" and report["findings"] == []
    assert report["counts"] == {"tp": 0, "fp": 0, "fn": 1} and report["inspection_steps"] == 100


def test_adp_inspection_steps_counts_every_step_before_submit_including_errors(loaded: LoadedEpisode) -> None:
    env = AuditEnv.from_episode(loaded)
    env.reset(config=CONFIG)
    actions: list[object] = [CALC, UNKNOWN_ID, {"action": "nope", "args": {}}, "not an object", None,
                             {"action": "get_document", "args": {}}, {BRIDGE_REJECT: "action_too_large"}]  # fmt: skip
    for action in actions:
        env.step(action)
    env.step(oracle_submit(loaded))
    report = env.evaluator_report()
    assert (report["inspection_steps"], report["steps_used"]) == (len(actions), len(actions) + 1)
    assert report["score"]["reward"] == pytest.approx(1 - 0.002 * len(actions), abs=1e-9)


class SlowSource:
    """A source whose loading takes 30 seconds of the injected clock."""

    def __init__(self, loaded: LoadedEpisode, clock: FakeClock) -> None:
        self.loaded, self.clock = loaded, clock

    def load(self, name: str) -> LoadedEpisode:
        self.clock.now += 30.0
        return self.loaded


def test_c18_the_time_limit_runs_from_the_top_of_reset(loaded: LoadedEpisode) -> None:
    clock = FakeClock()
    env = AuditEnv(SlowSource(loaded, clock), clock=clock)
    env.reset(config={**CONFIG, "mode": "eval"})
    assert env.seconds_left() == pytest.approx(30.0)  # loading already spent half of the 60 s
    clock.now += 30.5
    observation, reward, terminated, truncated, info = env.step(oracle_submit(loaded))
    assert (reward, terminated, truncated, info) == (0.0, False, True, {})
    report = env.evaluator_report()
    assert report["termination_cause"] == "wall_time" and report["counts"] == {"tp": 0, "fp": 0, "fn": 1}


def test_adp_time_limit_accepts_an_earlier_start_from_the_caller(loaded: LoadedEpisode) -> None:
    clock = FakeClock()
    env = AuditEnv.from_episode(loaded, clock=clock)
    started = clock.now
    clock.now += 50.0  # e.g. the adapter generated the episode first
    env.reset(config=CONFIG, started_at=started)
    assert env.seconds_left() == pytest.approx(10.0)
    for bad in (clock.now + 1, float("nan"), True, "0"):
        with pytest.raises(LifecycleError):
            env.reset(config=CONFIG, started_at=bad)  # type: ignore[arg-type]


def oversized_submit(loaded: LoadedEpisode) -> dict[str, Any]:
    """31 findings with 9000-character explanations: over the byte bound and over the official limits."""
    action = oracle_submit(loaded)
    finding = dict(action["args"]["findings"]["findings"][0], explanation="x" * 9000)
    action["args"]["findings"]["findings"] = [finding] * 31
    assert len(json.dumps(action).encode()) > MAX_ACTION_BYTES
    return action


@pytest.mark.parametrize(("mode", "expected"), [("train", -1.0), ("eval", 0.0)])
def test_crit_oversize_submit_is_a_malformed_submit(loaded: LoadedEpisode, mode: str, expected: float) -> None:
    env = AuditEnv.from_episode(loaded)
    env.reset(config={**CONFIG, "mode": mode})
    _, reward, terminated, truncated, _ = env.step(oversized_submit(loaded))
    assert (reward, terminated, truncated) == (expected, True, False)
    report = env.evaluator_report()
    assert report["termination_cause"] == "malformed_submission" and report["score"]["reward"] == -1.0
    env.reset(config={**CONFIG, "mode": mode})  # an oversized inspection stays a bounded error
    big = {"action": "get_record", "args": {"table": "ledger", "id": "x" * MAX_ACTION_BYTES}}
    observation, _, terminated, _, _ = env.step(big)
    assert observation["error"]["code"] == "action_too_large" and terminated is False


def _bridge_items(data: bytes) -> list[object]:
    inbox: queue.Queue = queue.Queue(maxsize=100)
    _read_actions(io.BytesIO(data), inbox, threading.Event())
    return [decode_action(item) for item in list(inbox.queue)[:-1]]  # the last item is end-of-file


def test_crit_oversize_submit_through_the_bridge(loaded: LoadedEpisode) -> None:
    submit = oversized_submit(loaded)
    tail_first = json.dumps({"args": submit["args"], "action": "submit"}).encode()  # the name comes last
    inspection = json.dumps({"action": "get_record", "args": {"table": "ledger", "id": "x" * 300_000}}).encode()
    items = _bridge_items(json.dumps(submit).encode() + b"\n" + tail_first + b"\n" + inspection + b"\n" + tail_first)
    assert items == [BROKEN_SUBMIT, BROKEN_SUBMIT, {BRIDGE_REJECT: "action_too_large"}, BROKEN_SUBMIT]
    env = AuditEnv.from_episode(loaded)
    env.reset(config=CONFIG)
    assert env.step(items[0])[1:4] == (-1.0, True, False)


def test_trf_id_shape_any_string_without_control_characters() -> None:
    """TRF-id-shape: an id is any string up to 256 characters without control characters."""
    for good in ("led/12", "led 12", "ид-led-1", "x" * 256, "Q-000123", "2026-01-01|USD|KZT", "a,b\"c'"):
        assert is_valid_id(good)
    for bad in ("", "x" * 257, "a\nb", "tab\there", "\x7f", "\u0085", "\ud800", 7, None):
        assert not is_valid_id(bad)
