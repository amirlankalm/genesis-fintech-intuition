from __future__ import annotations

import json

import pytest
from helpers import CLEAN, CLEAN_ID, FAULTY, FAULTY_ID, finding, list_action, submit_action

from genesis_audit import paths
from genesis_audit.env import AuditEnv
from genesis_audit.errors import EpisodeError, LifecycleError


def start(env: AuditEnv, episode: str = FAULTY, **config):
    return env.reset(config={"episode": episode, **config})


def counts(env: AuditEnv) -> tuple[int, int, int]:
    report = env.evaluator_report()["counts"]
    return report["tp"], report["fp"], report["fn"]


def test_reset_returns_task_manifest_policy_and_budget(env: AuditEnv) -> None:
    observation, info = start(env)
    assert set(observation) == {"task", "manifest", "policy", "steps_remaining"}
    assert observation["steps_remaining"] == 100
    assert observation["manifest"]["episode_id"] == FAULTY_ID
    assert "finding_conventions" in observation["policy"]
    assert set(info) == {"env_version", "mode"}
    json.dumps(observation)  # JSON-compatible


def test_inspection_returns_only_the_request_and_costs_one_step(env: AuditEnv) -> None:
    start(env)
    observation, reward, terminated, truncated, info = env.step(list_action("payments"))
    assert set(observation) == {"records", "next_cursor", "steps_remaining"}
    assert (len(observation["records"]), observation["steps_remaining"]) == (3, 99)
    assert (reward, terminated, truncated, info) == (0.0, False, False, {})
    observation, reward, *_ = env.step({"action": "get_document", "args": {"doc_id": "D44"}})
    assert set(observation) == {"record", "steps_remaining"} and reward == 0.0
    observation, *_ = env.step({"action": "get_record", "args": {"table": "ledger", "id": "L11"}})
    assert observation["record"]["credit_minor"] == 150_000 and observation["steps_remaining"] == 97


@pytest.mark.parametrize(
    ("action", "code"),
    [
        ({"action": "get_record", "args": {"table": "ledger", "id": "L99"}}, "unknown_id"),
        ({"action": "run_sql", "args": {"query": "select * from truth"}}, "unknown_action"),
        ({"action": "list_records", "args": {"table": "truth"}}, "unknown_table"),
        ({"action": "list_records", "args": {"table": "ledger", "limit": 500}}, "bad_limit"),
        ("submit", "invalid_action"),
        (None, "invalid_action"),
    ],
)
def test_invalid_inspection_costs_a_step_and_does_not_end_the_episode(env: AuditEnv, action: object, code: str) -> None:
    start(env)
    observation, reward, terminated, truncated, _ = env.step(action)
    assert observation == {
        "error": {"code": code, "message": observation["error"]["message"]},
        "steps_remaining": 99,
    }
    assert len(observation["error"]["message"]) < 120
    assert (reward, terminated, truncated) == (0.0, False, False)
    env.step(submit_action([finding()]))
    assert env.evaluator_report()["inspection_steps"] == 1  # the failed call was charged as an inspection


def test_correct_supported_submission(env: AuditEnv) -> None:
    start(env)
    env.step(list_action("ledger"))
    observation, _, terminated, truncated, _ = env.step(submit_action([finding()]))
    assert observation == {"status": "episode_over", "steps_remaining": 98}
    assert (terminated, truncated) == (True, False)
    assert counts(env) == (1, 0, 0)
    report = env.evaluator_report()
    assert (report["termination_cause"], report["steps_used"], report["inspection_steps"]) == ("submitted", 2, 1)


@pytest.mark.parametrize(
    ("findings", "expected"),
    [
        ([], (0, 0, 1)),  # abstaining on faulty books misses the issue
        ([finding(claimed_amount_minor=1000)], (0, 1, 1)),  # major units
        ([finding(claimed_amount_minor=260_000)], (0, 1, 1)),  # the whole receipt
        ([finding(claimed_amount_minor=110_000)], (0, 1, 1)),  # everything parked as unapplied, not just the shortfall
        ([finding(currency="USD")], (0, 1, 1)),
        ([finding(evidence_ids=["D31", "D44", "L19", "L13"])], (0, 1, 1)),  # the allocation row L11 is missing
        ([finding(evidence_ids=["D31", "D44", "L11", "L19", "L13"])], (1, 0, 0)),  # extra record ids are fine
        ([finding(evidence_ids=["D31", "D44", "L11", "L19", "L13", "L77"])], (0, 1, 1)),  # one invented id
        ([finding(affected_ids=["I7"])], (0, 1, 1)),
        ([finding(), finding()], (1, 1, 0)),
        ([finding(), finding(affected_ids=["I3", "P5"], claimed_amount_minor=20_000,
                             evidence_ids=["D12", "D36", "L09", "L23", "L06"])], (1, 1, 0)),  # the overpayment decoy
        ([finding(type="duplicate_invoice")], (0, 1, 1)),
    ],
)  # fmt: skip
def test_strict_scoring_on_the_faulty_episode(env: AuditEnv, findings: list, expected: tuple[int, int, int]) -> None:
    start(env)
    env.step(submit_action(findings))
    assert counts(env) == expected


def test_clean_episode(env: AuditEnv) -> None:
    start(env, CLEAN)
    env.step(submit_action([], CLEAN_ID))
    assert counts(env) == (0, 0, 0)
    start(env, CLEAN)
    env.step(submit_action([finding()], CLEAN_ID))  # the faulty twin's answer is a false alarm here
    assert counts(env) == (0, 1, 0)


@pytest.mark.parametrize(
    "args",
    [None, {"findings": {"episode_id": "ep-other", "findings": []}}, {"findings": {"episode_id": FAULTY_ID, "findings": "x"}},
     {"findings": {"episode_id": FAULTY_ID, "findings": [finding()] * 31}},
     {"findings": {"episode_id": FAULTY_ID, "findings": [finding(evidence_ids=["E"] * 11)]}}],
)  # fmt: skip
def test_malformed_submission_ends_the_episode_and_logs_privately(env: AuditEnv, args: object) -> None:
    start(env)
    observation, _, terminated, truncated, info = env.step({"action": "submit", "args": args})
    assert observation == {"status": "episode_over", "steps_remaining": 99} and info == {}
    assert (terminated, truncated) == (True, False)
    report = env.evaluator_report()
    assert report["termination_cause"] == "malformed_submission" and report["valid_submission"] is False
    assert report["validation_error"] and "counts" not in report


def test_submit_on_the_last_allowed_step_is_accepted(env: AuditEnv) -> None:
    start(env, max_steps=3)
    env.step(list_action())
    env.step(list_action())
    observation, _, terminated, truncated, _ = env.step(submit_action([finding()]))
    assert (observation["steps_remaining"], terminated, truncated) == (0, True, False)
    assert counts(env) == (1, 0, 0)


def test_inspection_that_exhausts_the_budget_truncates_with_an_empty_submission(env: AuditEnv) -> None:
    start(env, max_steps=3)
    env.step(list_action())
    env.step(list_action())
    observation, _, terminated, truncated, _ = env.step(list_action("payments"))
    assert len(observation["records"]) == 3  # the last inspection is still answered
    assert (observation["status"], observation["steps_remaining"]) == ("episode_over", 0)
    assert (terminated, truncated) == (False, True)
    report = env.evaluator_report()
    assert (report["termination_cause"], report["inspection_steps"]) == ("step_limit", 3)
    assert counts(env) == (0, 0, 1)


def test_truncation_also_applies_to_an_invalid_last_action(env: AuditEnv) -> None:
    start(env, max_steps=1)
    observation, _, terminated, truncated, _ = env.step({"action": "nope", "args": {}})
    assert observation["error"]["code"] == "unknown_action" and (terminated, truncated) == (False, True)


def test_no_action_is_accepted_after_the_end(env: AuditEnv) -> None:
    start(env)
    env.step(submit_action([]))
    before = env.evaluator_report()
    for action in (submit_action([finding()]), list_action(), None):
        observation, reward, terminated, truncated, _ = env.step(action)
        assert observation == {
            "status": "episode_over", "steps_remaining": 99,
            "error": {"code": "episode_over", "message": observation["error"]["message"]},
        }  # fmt: skip
        assert "records" not in observation and (reward, terminated, truncated) == (0.0, True, False)
    after = env.evaluator_report()
    assert after["actions_after_end"] == 3
    assert {**after, "actions_after_end": 0} == before  # a second submission cannot improve the score


def test_lifecycle_misuse_is_a_harness_error(env: AuditEnv) -> None:
    with pytest.raises(LifecycleError):
        env.step(list_action())
    with pytest.raises(LifecycleError):
        env.evaluator_report()
    start(env)
    with pytest.raises(LifecycleError):
        env.evaluator_report()  # no scoring detail while the episode is live
    for config in (
        {},
        {"episode": FAULTY, "debug": True},
        {"episode": FAULTY, "max_steps": 0},
        {"episode": FAULTY, "max_steps": "9"},
    ):
        with pytest.raises(LifecycleError):
            env.reset(config=config)
    with pytest.raises(LifecycleError):
        env.reset(seed="7", config={"episode": FAULTY})  # type: ignore[arg-type]
    for name in ("../private/teaching_b", "Teaching_B", "", "missing_episode"):
        with pytest.raises(EpisodeError):
            env.reset(config={"episode": name})


def test_reset_gives_isolated_state(env: AuditEnv) -> None:
    start(env)
    env.step(list_action())
    env.step(submit_action([finding()]))
    observation, _ = start(env)
    assert observation["steps_remaining"] == 100
    env.step(submit_action([]))
    report = env.evaluator_report()
    assert (report["steps_used"], report["counts"]) == (1, {"tp": 0, "fp": 0, "fn": 1})


def test_observations_are_copies_of_evaluator_state(env: AuditEnv) -> None:
    observation, _ = start(env)
    observation["manifest"]["amount_tolerance_minor"]["KZT"] = 10**9
    observation["policy"]["allocation"]["policy"] = "anything goes"
    page, *_ = env.step(list_action())
    page["records"][5]["credit_minor"] = 250_000
    env.step(submit_action([finding(claimed_amount_minor=1)]))
    assert counts(env) == (0, 1, 1)


def test_internal_errors_are_bounded_for_the_policy_and_kept_for_the_evaluator(env: AuditEnv, monkeypatch) -> None:
    start(env)

    def explode(*args: object) -> None:
        raise RuntimeError(f"cannot read {paths.PRIVATE_ROOT}/teaching_b/truth.json")

    monkeypatch.setattr(type(env._state.loaded.public), "list_page", explode)
    observation, reward, terminated, truncated, _ = env.step(list_action())
    assert observation["error"]["code"] == "internal_error" and "truth" not in json.dumps(observation)
    assert str(paths.PRIVATE_ROOT) not in json.dumps(observation)
    assert (reward, terminated, truncated) == (0.0, False, False)
    env.step(submit_action([]))
    assert "truth.json" in env.evaluator_report()["internal_errors"][0]


def test_a_failed_reset_leaves_no_live_episode(env: AuditEnv) -> None:
    """Review E, row 26."""
    start(env)
    env.step(list_action())
    for bad in ({"episode": "missing_episode"}, {"episode": FAULTY, "mode": "nope"}, {}):
        with pytest.raises((EpisodeError, LifecycleError)):
            env.reset(config=bad)
        with pytest.raises(LifecycleError):
            env.step(list_action())  # the earlier episode is gone, not silently resumed


def test_no_action_is_accepted_after_truncation(env: AuditEnv) -> None:
    """Review E, row 23."""
    start(env, max_steps=2)
    env.step(list_action())
    env.step(list_action())
    before = env.evaluator_report()
    for action in (submit_action([finding()]), list_action()):
        observation, reward, terminated, truncated, _ = env.step(action)
        assert observation["error"]["code"] == "episode_over" and (reward, terminated, truncated) == (0.0, False, True)
    after = env.evaluator_report()
    assert after["score"] == before["score"] and after["trajectory_digest"] == before["trajectory_digest"]


def test_oversized_in_process_action_gets_the_same_bound_as_the_bridge(env: AuditEnv) -> None:
    """Review E, row 21: a 50 MB id used to be accepted and looked up."""
    start(env)
    observation, *_ = env.step({"action": "get_record", "args": {"table": "ledger", "id": "x" * 300_000}})
    assert observation["error"]["code"] == "action_too_large"
    assert len(json.dumps(env.trajectory())) < 20_000  # and it is not stored


def test_environment_randomness_is_local(env: AuditEnv) -> None:
    """Review E, hypothesis S8: nothing here depends on the global random module."""
    import random

    def perturbed(seed_global: int) -> str:
        random.seed(seed_global)
        env.reset(5, {"episode": FAULTY, "perturb": {"rename_ids": True, "shuffle_rows": True}})
        return json.dumps(env.trajectory()[0]["observation"], sort_keys=True) + json.dumps(env.step(list_action())[0])

    assert perturbed(1) == perturbed(2)
