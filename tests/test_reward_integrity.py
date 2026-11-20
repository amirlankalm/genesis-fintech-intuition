"""The reward behaviours the draft asks teams to publish tests for (section 5), on the real environment."""

from __future__ import annotations

import pytest
from helpers import CLEAN, CLEAN_ID, FAULTY, FAULTY_ID, finding, list_action, submit_action

from genesis_audit.env import AuditEnv

DECOY = finding(
    affected_ids=["I3", "P5"], claimed_amount_minor=20_000, evidence_ids=["D12", "D36", "L09", "L23", "L06"]
)


def run(env: AuditEnv, findings: list | None, *, episode: str = FAULTY, inspections: int = 0, raw_args=None) -> float:
    env.reset(config={"episode": episode})
    for _ in range(inspections):
        _, reward, terminated, truncated, _ = env.step(list_action())
        assert (reward, terminated, truncated) == (0.0, False, False)  # inspection reward is always zero
    episode_id = FAULTY_ID if episode == FAULTY else CLEAN_ID
    action = {"action": "submit", "args": raw_args} if raw_args is not None else submit_action(findings, episode_id)
    _, reward, terminated, truncated, _ = env.step(action)
    assert terminated and not truncated
    assert reward == env.evaluator_report()["score"]["reward"]
    return reward


def test_perfect_supported_findings_beat_abstention_on_faulty_books(env: AuditEnv) -> None:
    assert run(env, [finding()], inspections=3) == pytest.approx(0.994)
    assert run(env, [], inspections=3) == -1.0
    assert run(env, [finding()], inspections=99) > run(env, [], inspections=0)  # even at the maximum step cost


def test_abstention_beats_false_alarms_on_clean_books(env: AuditEnv) -> None:
    assert run(env, [], episode=CLEAN, inspections=3) == pytest.approx(0.994)
    assert run(env, [finding()], episode=CLEAN, inspections=3) == -1.0
    assert run(env, [DECOY], episode=CLEAN) == -1.0


def test_duplicates_add_no_credit(env: AuditEnv) -> None:
    once = run(env, [finding()])
    assert once == 1.0
    assert run(env, [finding(), finding()]) == pytest.approx(2 * (2 / 3) - 1)
    assert run(env, [finding()] * 30) < 0 < once


def test_flagging_everything_performs_poorly(env: AuditEnv) -> None:
    pairs = [("I7", "P9", "D31", "D44"), ("I3", "P2", "D12", "D27"), ("I3", "P5", "D12", "D36")]
    amounts = [250_000, 150_000, 120_000, 100_000, 20_000, 50_000, 125_000, 1_000, 2_500, 130_000]
    rows = ["L11", "L19", "L13", "L05", "L17", "L09", "L23", "L06"]
    accusations = [
        finding(affected_ids=[invoice, payment], claimed_amount_minor=amount, evidence_ids=[doc_a, doc_b, *rows])
        for invoice, payment, doc_a, doc_b in pairs
        for amount in amounts
    ]
    assert len(accusations) == 30  # the cap: a valid, bounded flag-all that does contain the right answer
    reward = run(env, accusations, inspections=3)
    report = env.evaluator_report()
    assert report["counts"] == {"tp": 1, "fp": 29, "fn": 0}
    assert reward == pytest.approx(2 * (2 / 31) - 1 - 0.006) and reward < -0.8


def test_fewer_inspections_separate_equal_results_only_slightly(env: AuditEnv) -> None:
    fast, slow = run(env, [finding()], inspections=2), run(env, [finding()], inspections=12)
    assert fast > slow and fast - slow == pytest.approx(0.02)


@pytest.mark.parametrize(
    "bad",
    [
        [finding(affected_ids=["I1", "P1"])],  # guessed ids
        [finding(evidence_ids=["D31", "D44"])],  # unsupported: incomplete evidence
        [finding(evidence_ids=["D31", "D44", "L11", "ZZ9"])],  # invented evidence id
        [finding(currency="USD")],  # currency error
        [finding(claimed_amount_minor=100_001)],  # one minor unit outside a zero tolerance
        [finding(claimed_amount_minor=-100_000)],  # wrong sign
    ],
)
def test_wrong_or_unsupported_claims_score_like_a_miss_plus_a_false_alarm(env: AuditEnv, bad: list) -> None:
    assert run(env, bad) == -1.0
    assert env.evaluator_report()["counts"] == {"tp": 0, "fp": 1, "fn": 1}


@pytest.mark.parametrize(
    "args", [None, "{", {"findings": None}, {"findings": {"episode_id": FAULTY_ID, "findings": [{}]}}]
)
def test_malformed_final_submission_is_minus_one_on_any_books(env: AuditEnv, args: object) -> None:
    for episode in (FAULTY, CLEAN):
        env.reset(config={"episode": episode})
        _, reward, terminated, truncated, _ = env.step({"action": "submit", "args": args})
        assert (reward, terminated, truncated) == (-1.0, True, False)
        assert env.evaluator_report()["score"]["malformed"] is True


def test_invalid_inspection_is_not_a_malformed_submission(env: AuditEnv) -> None:
    env.reset(config={"episode": FAULTY})
    _, reward, terminated, _, _ = env.step({"action": "submitt", "args": {"findings": []}})
    assert (reward, terminated) == (0.0, False)
    assert run(env, [finding()]) == 1.0


def test_truncation_scores_an_empty_submission(env: AuditEnv) -> None:
    for episode, expected in ((FAULTY, -1.0), (CLEAN, pytest.approx(1 - 0.002 * 5))):
        env.reset(config={"episode": episode, "max_steps": 5})
        for _ in range(4):
            env.step(list_action())
        _, reward, terminated, truncated, _ = env.step(list_action())
        assert (reward, terminated, truncated) == (expected, False, True)


def test_reward_after_the_end_is_zero_and_changes_nothing(env: AuditEnv) -> None:
    first = run(env, [])
    _, again, *_ = env.step(submit_action([finding()]))
    assert (first, again) == (-1.0, 0.0)
    assert env.evaluator_report()["score"]["reward"] == -1.0


# --- From the adversarial review (docs/review/E_adversarial_review.md, section 6) ---


@pytest.mark.parametrize("extra", ["I7", "P9"])
def test_m03_an_extra_invoice_or_payment_id_get_record_returns_keeps_the_tp(env: AuditEnv, extra: str) -> None:
    """M03 / rule 3 ("additional existing accessible evidence is allowed"): get_record returns a record for an
    invoice_id or a payment_id, so citing one on top of a complete set keeps the TP. (Until 20 Nov 2026 this test
    pinned PC-9's narrower rule, under which these ids voided the finding.)"""
    assert run(env, [finding(evidence_ids=[*finding()["evidence_ids"], extra])]) == 1.0
    assert env.evaluator_report()["counts"] == {"tp": 1, "fp": 0, "fn": 0}


@pytest.mark.parametrize("extra", ["E4", "truth-29d7352524bd", "ZZ9"])
def test_extra_id_no_tool_returns_a_record_for_voids_the_finding(env: AuditEnv, extra: str) -> None:
    """An entity_id, a private id or an invented id is not accessible evidence: the finding is unmatched (FP)."""
    from genesis_audit import matching

    assert run(env, [finding(evidence_ids=[*finding()["evidence_ids"], extra])]) == -1.0
    (reason,) = env.evaluator_report()["findings"][0]["reasons"]
    assert reason == matching.REASON_NOT_A_RECORD_ID == "evidence_id_is_not_a_record_id"
    assert "public_records" not in reason  # the old reason string claimed something false about these ids


def test_fx_key_is_a_record_id_and_may_be_cited(env: AuditEnv) -> None:
    assert run(env, [finding(evidence_ids=[*finding()["evidence_ids"], "2026-10-14|USD|KZT"])]) == 1.0


@pytest.mark.parametrize("broken", [{"action": "submit"}, {"action": "submit", "args": None, "extra": 1},
                                    {"action": "submit", "findings": []}])  # fmt: skip
def test_broken_submit_on_the_last_step_is_not_scored_above_a_malformed_one(env: AuditEnv, broken: dict) -> None:
    """Anything whose action is 'submit' is a submission attempt. A broken envelope is malformed, not an inspection."""
    for max_steps in (1, 3):
        env.reset(config={"episode": CLEAN, "max_steps": max_steps})
        _, malformed, *_ = env.step({"action": "submit", "args": None})
        env.reset(config={"episode": CLEAN, "max_steps": max_steps})
        _, reward, terminated, truncated, _ = env.step(broken)
        assert (reward, terminated, truncated) == (malformed, True, False) == (-1.0, True, False)
        assert env.evaluator_report()["termination_cause"] == "malformed_submission"
