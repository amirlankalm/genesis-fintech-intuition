"""Features added in the staged build: modes, wall time, evidence rule, logging, hostile in-process input."""

from __future__ import annotations

import json
import math
import random

import pytest
from helpers import CLEAN, EVIDENCE, FAULTY, FAULTY_ID, finding, list_action, submit_action

from genesis_audit import paths
from genesis_audit.env import BRIDGE_REJECT, AuditEnv, DirectorySource
from genesis_audit.errors import POLICY_ERRORS, LifecycleError


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(clock=None) -> AuditEnv:
    source = DirectorySource(paths.PUBLIC_ROOT, paths.PRIVATE_ROOT)
    return AuditEnv(source, clock=clock) if clock else AuditEnv(source)


def test_eval_mode_withholds_reward_and_every_diagnostic(env: AuditEnv) -> None:
    """C19: in closed (eval) mode the reward is a numeric 0 at every step, the terminal one included, and info is empty."""
    observation, info = env.reset(config={"episode": FAULTY, "mode": "eval"})
    assert info == {}
    assert env.step(list_action())[1] == 0.0
    good = env.step(submit_action([finding()]))
    assert good == ({"status": "episode_over", "steps_remaining": 98}, 0.0, True, False, {})
    assert isinstance(good[1], float)
    assert env.evaluator_report()["score"]["reward"] == pytest.approx(0.998)
    env.reset(config={"episode": FAULTY, "mode": "eval"})
    env.step(list_action())
    malformed = env.step({"action": "submit", "args": None})
    assert malformed == good  # the policy cannot tell a perfect answer from a malformed one
    assert env.evaluator_report()["score"]["reward"] == -1.0


def test_train_mode_returns_only_the_scalar(env: AuditEnv) -> None:
    _, info = env.reset(config={"episode": FAULTY})
    assert info["mode"] == "train"
    observation, reward, terminated, truncated, info = env.step(submit_action([finding(), finding()]))
    assert observation == {"status": "episode_over", "steps_remaining": 99} and info == {}
    assert reward == pytest.approx(1 / 3) and (terminated, truncated) == (True, False)


@pytest.mark.parametrize(
    "config",
    [{"mode": "test"}, {"evidence_rule": "trusted"}, {"wall_time_limit_s": 0}, {"wall_time_limit_s": True},
     {"wall_time_limit_s": "60"}, {"wall_time_limit_s": float("inf")}, {"wall_time_limit_s": float("nan")},
     {"wall_time_limit_s": 1e12}, {"perturb": {"rename_ids": True}}, {"perturb": {"rename_ids": 1, "shuffle_rows": 0}},
     {"perturb": {"rename_ids": True, "shuffle_rows": True}}, {"perturb": "all"}, {"secret": "x"}],
)  # fmt: skip
def test_bad_config_is_a_harness_error(env: AuditEnv, config: dict) -> None:
    with pytest.raises(LifecycleError):
        env.reset(config={"episode": FAULTY, **config})  # the valid perturb case fails for lack of a seed


def test_wall_time_truncates_without_executing_the_late_action() -> None:
    clock = FakeClock()
    env = make(clock)
    env.reset(config={"episode": FAULTY, "wall_time_limit_s": 60})
    assert env.seconds_left() == 60.0
    env.step(list_action())
    clock.now += 59.5
    assert env.step(list_action())[3] is False and env.seconds_left() == pytest.approx(0.5)
    clock.now += 1.0
    observation, reward, terminated, truncated, _ = env.step(submit_action([finding()]))  # a perfect answer, too late
    assert observation == {"status": "episode_over", "steps_remaining": 98}
    assert (reward, terminated, truncated) == (-1.0, False, True)
    report = env.evaluator_report()
    assert (report["termination_cause"], report["steps_used"], report["counts"]) == (
        "wall_time",
        2,
        {"tp": 0, "fp": 0, "fn": 1},
    )
    last = env.trajectory()[-1]
    assert (last["event"], last["action"]) == ("forced_truncation", None)  # the late action never joined the episode
    assert env.seconds_left() == 0.0


def test_wall_time_can_be_disabled_and_forced_truncation_is_idempotent() -> None:
    clock = FakeClock()
    env = make(clock)
    env.reset(config={"episode": CLEAN, "wall_time_limit_s": None})
    clock.now += 10_000
    assert env.seconds_left() is None and env.step(list_action())[3] is False
    first = env.truncate("policy_exit")
    assert first[1:4] == (pytest.approx(0.998), False, True)  # clean books, empty submission, one inspection
    assert env.truncate("wall_time") == first and env.evaluator_report()["termination_cause"] == "policy_exit"
    with pytest.raises(LifecycleError):
        env.truncate("because")


def test_observed_evidence_rule_needs_the_records_to_have_been_fetched(env: AuditEnv) -> None:
    strict = {"episode": FAULTY, "evidence_rule": "observed"}
    env.reset(config=strict)
    assert env.step(submit_action([finding()]))[1] == -1.0  # cited, never fetched
    assert env.evaluator_report()["findings"][0]["reasons"] == ["evidence_id_not_observed_in_episode"]
    env.reset(config=strict)
    env.step(list_action("ledger"))
    env.step({"action": "get_document", "args": {"doc_id": "D31"}})
    assert env.step(submit_action([finding()]))[1] == -1.0  # D44 still not fetched
    env.reset(config=strict)
    for evidence_id in EVIDENCE:
        action = {"action": "get_document", "args": {"doc_id": evidence_id}}
        if evidence_id.startswith("L"):
            action = {"action": "get_record", "args": {"table": "ledger", "id": evidence_id}}
        env.step(action)
    assert env.step(submit_action([finding()]))[1] == pytest.approx(0.994)
    env.reset(config={"episode": FAULTY})
    assert env.step(submit_action([finding()]))[1] == 1.0  # the default rule asks only that evidence be accessible


def test_bridge_rejections_are_bounded_errors_that_cost_a_step(env: AuditEnv) -> None:
    env.reset(config={"episode": FAULTY})
    assert env.step({BRIDGE_REJECT: "action_too_large"})[0]["error"]["code"] == "action_too_large"
    assert env.step({BRIDGE_REJECT: "anything else"})[0]["error"]["code"] == "invalid_action"
    assert env.step({BRIDGE_REJECT: ["x"]})[0] == {
        "error": {"code": "invalid_action", "message": POLICY_ERRORS["invalid_action"]}, "steps_remaining": 97,
    }  # fmt: skip


NOT_JSON = [{1, 2}, object(), float("nan"), {"action": "list_records", "args": {"table": float("inf")}}, b"bytes",
            {"action": "get_record", "args": {"table": "ledger", "id": {3}}}, lambda: None, math.inf]  # fmt: skip


@pytest.mark.parametrize("action", NOT_JSON)
def test_non_json_actions_never_raise(env: AuditEnv, action: object) -> None:
    env.reset(config={"episode": FAULTY})
    observation, reward, terminated, truncated, info = env.step(action)
    assert observation["error"]["code"] == "invalid_action" and observation["steps_remaining"] == 99
    assert (reward, terminated, truncated, info) == (0.0, False, False, {})


def test_deeply_nested_action_is_bounded(env: AuditEnv) -> None:
    env.reset(config={"episode": FAULTY})
    nested: list = []
    for _ in range(100_000):
        nested = [nested]
    assert env.step(nested)[0]["error"]["code"] == "invalid_action"
    # an object whose action is "submit" is a submission attempt however unusable the rest is (PC-19)
    assert env.step({"action": "submit", "args": {"findings": nested}})[1:3] == (-1.0, True)


def junk(rng: random.Random, depth: int = 0) -> object:
    atoms = [
        None,
        True,
        0,
        -1,
        2**70,
        1.5,
        "",
        "ledger",
        "L11",
        "submit",
        "list_records",
        "findings",
        "x" * 70,
        "ü",
        "\x00",
    ]
    roll = rng.random()
    if depth > 3 or roll < 0.45:
        return rng.choice(atoms)
    if roll < 0.7:
        return [junk(rng, depth + 1) for _ in range(rng.randrange(0, 4))]
    keys = [
        "action",
        "args",
        "table",
        "id",
        "doc_id",
        "cursor",
        "limit",
        "findings",
        "episode_id",
        "expression",
        "type",
    ]
    return {rng.choice(keys): junk(rng, depth + 1) for _ in range(rng.randrange(0, 4))}


def test_fuzzed_actions_always_give_a_well_formed_transition(env: AuditEnv) -> None:
    rng = random.Random(20261115)
    for episode in range(40):
        env.reset(config={"episode": FAULTY if episode % 2 else CLEAN, "max_steps": 25})
        for _ in range(60):
            action = junk(rng)
            if rng.random() < 0.3:
                action = {"action": rng.choice(["list_records", "get_record", "get_document", "calculator", "submit"]),
                          "args": junk(rng, 2)}  # fmt: skip
            observation, reward, terminated, truncated, info = env.step(action)
            json.dumps([observation, reward, info])
            assert isinstance(observation["steps_remaining"], int) and 0 <= observation["steps_remaining"] <= 25
            assert reward is not None and -1.0 <= reward <= 1.0 and not (terminated and truncated)
            if "error" in observation:
                assert observation["error"]["message"] == POLICY_ERRORS[observation["error"]["code"]]
        assert env.over and env.evaluator_report()["steps_used"] <= 25
        assert env.evaluator_report()["internal_errors"] == []


def test_trajectory_has_the_required_fields_and_a_stable_digest(env: AuditEnv) -> None:
    def play(last: dict) -> tuple[list[dict], str]:
        env.reset(config={"episode": FAULTY})
        env.step(list_action("payments"))
        env.step({"action": "calculator", "args": {"expression": "250000-150000"}})
        env.step(last)
        return env.trajectory(), env.evaluator_report()["trajectory_digest"]

    trajectory, digest = play(submit_action([finding()]))
    assert [record["step"] for record in trajectory] == [0, 1, 2, 3]
    for record in trajectory:
        assert {"episode_id", "step", "action", "observation", "reward", "terminated", "truncated"} <= set(record)
        assert record["episode_id"] == FAULTY_ID
    assert trajectory[0]["action"] is None and trajectory[0]["reward"] is None
    assert [record["event"] for record in trajectory] == ["reset", "step", "step", "step"]
    assert trajectory[-1]["terminated"] is True and trajectory[-1]["reward"] == pytest.approx(0.996)
    assert play(submit_action([finding()])) == (trajectory, digest)  # same actions, same bytes
    assert play(submit_action([]))[1] != digest
    trajectory[1]["observation"]["records"].clear()  # the returned log is a copy
    assert env.trajectory()[1]["observation"]["records"]


def test_nothing_private_is_in_what_the_policy_saw(env: AuditEnv) -> None:
    private = ["truth-", "canary-", "inj-", str(paths.PRIVATE_ROOT), "provenance", "teaching_b", "matched", "issue_id"]
    for mode in ("train", "eval"):
        env.reset(config={"episode": FAULTY, "mode": mode})
        for table in ("ledger", "invoices", "payments", "fx", "truth", "private"):
            env.step(list_action(table))
        env.step({"action": "get_record", "args": {"table": "ledger", "id": "truth-29d7352524bd"}})
        env.step({"action": "get_document", "args": {"doc_id": "../private/teaching_b/truth.json"}})
        env.step(submit_action([finding(evidence_ids=["truth-29d7352524bd"])]))
        visible = json.dumps(env.trajectory())
        # the submitted action echoes the policy's own guess; nothing the environment said may contain private text
        said = json.dumps([[t["observation"], t["reward"], t["info"]] for t in env.trajectory()])
        assert not [token for token in private if token in said], mode
        assert "episode_over" in visible


def test_action_size_is_measured_in_utf8_bytes_like_the_bridge(env: AuditEnv) -> None:
    env.reset(config={"episode": FAULTY})
    two_byte = {"action": "get_document", "args": {"doc_id": "\u00e9" * 50_000}}  # 100 kB, far below the bound
    assert env.step(two_byte)[0]["error"]["code"] == "unknown_id"
    assert (
        env.step({"action": "get_document", "args": {"doc_id": "\u00e9" * 140_000}})[0]["error"]["code"]
        == "action_too_large"
    )
    assert env.step({"action": "get_document", "args": {"doc_id": "\ud800"}})[0]["error"]["code"] == "invalid_action"
    nested: list = []
    for _ in range(17):
        nested = [nested]
    assert env.step(nested)[0]["error"]["code"] == "invalid_action"
    assert (
        env.step({"action": "list_records", "args": {"table": "ledger", "limit": [[[[1]]]]}})[0]["error"]["code"]
        == "bad_limit"
    )


@pytest.mark.parametrize("args", [float("inf"), float("nan"), {1, 2}, object()])
def test_a_submit_with_an_unusable_payload_is_malformed_not_an_inspection(env: AuditEnv, args: object) -> None:
    """Grader, defect 4: on the last step this used to score like a clean abstention instead of -1."""
    env.reset(config={"episode": CLEAN, "max_steps": 1})
    observation, reward, terminated, truncated, _ = env.step({"action": "submit", "args": args})
    assert (reward, terminated, truncated) == (-1.0, True, False)
    assert env.evaluator_report()["termination_cause"] == "malformed_submission"
