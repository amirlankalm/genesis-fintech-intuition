from __future__ import annotations

from typing import Any

import pytest
from helpers import FAULTY_ID, finding

from genesis_audit.errors import MalformedSubmission, PolicyVisibleError
from genesis_audit.schemas import parse_action, parse_submission

LIMITS = {"max_findings": 30, "max_evidence_ids": 10, "max_explanation_chars": 1000}


def parse(findings: Any, episode_id: str = FAULTY_ID):
    return parse_submission({"findings": {"episode_id": episode_id, "findings": findings}}, FAULTY_ID, LIMITS)


def test_valid_actions() -> None:
    assert parse_action({"action": "list_records", "args": {"table": "ledger"}})[0] == "list_records"
    assert parse_action({"action": "get_record", "args": {"table": "ledger", "id": "L1"}})[1]["id"] == "L1"
    assert parse_action({"action": "get_document", "args": {"doc_id": "D1"}})[0] == "get_document"
    assert parse_action({"action": "submit", "args": "anything"}) == ("submit", "anything")


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ("list_records", "invalid_action"),
        ([], "invalid_action"),
        ({"action": "list_records"}, "invalid_action"),
        ({"action": "list_records", "args": {"table": "ledger"}, "extra": 1}, "invalid_action"),
        ({"action": "shell", "args": {}}, "unknown_action"),
        ({"action": 5, "args": {}}, "unknown_action"),
        ({"action": ["submit"], "args": {}}, "unknown_action"),
        ({"action": "list_records", "args": None}, "bad_arguments"),
        ({"action": "list_records", "args": {}}, "bad_arguments"),
        ({"action": "list_records", "args": {"table": "ledger", "sql": "x"}}, "bad_arguments"),
        ({"action": "get_record", "args": {"table": "ledger"}}, "bad_arguments"),
        ({"action": "get_document", "args": {}}, "bad_arguments"),
    ],
)
def test_invalid_inspection_actions_are_bounded_errors(action: object, code: str) -> None:
    with pytest.raises(PolicyVisibleError) as caught:
        parse_action(action)
    assert caught.value.code == code


def test_valid_submission_is_canonicalized() -> None:
    (parsed,) = parse([finding(affected_ids=["P9", "I7", "P9"], evidence_ids=["L13", "D31", "L13"])])
    assert parsed.affected_ids == ("I7", "P9") and parsed.evidence_ids == ("D31", "L13")
    assert parse([]) == ()
    assert len(parse([finding()] * 30)) == 30
    assert parse([finding(evidence_ids=[])])[0].evidence_ids == ()
    assert parse([finding(explanation="x" * 1000, claimed_amount_minor=-(2**53 - 1))])
    assert parse([finding(type="made_up_type", currency="ZZZ", affected_ids=["nope"])])  # wrong, not malformed


def without(key: str) -> dict[str, Any]:
    return {k: v for k, v in finding().items() if k != key}


MALFORMED = [
    ("not a list", "list of at most"),
    ([finding()] * 31, "list of at most"),
    ([[]], "must be an object"),
    ([without("explanation")], "missing required keys: explanation"),
    ([finding(type=7)], "type"),
    ([finding(currency=398)], "currency"),
    ([finding(claimed_amount_minor=100000.0)], "claimed_amount_minor"),
    ([finding(claimed_amount_minor="100000")], "claimed_amount_minor"),
    ([finding(claimed_amount_minor=True)], "claimed_amount_minor"),
    ([finding(explanation="x" * 1001)], "explanation"),
    ([finding(explanation=None)], "explanation"),
    ([finding(evidence_ids=["E"] * 11)], "evidence_ids"),
    ([finding(evidence_ids="D31")], "evidence_ids"),
    ([finding(evidence_ids=["D31", 5])], "evidence_ids"),
    ([finding(affected_ids=[["I7"]])], "affected_ids"),
]


@pytest.mark.parametrize(("findings", "message"), MALFORMED)
def test_malformed_submissions(findings: Any, message: str) -> None:
    with pytest.raises(MalformedSubmission, match=message):
        parse(findings)


# Under the official matcher conventions these are well-typed values: they are scored (as false positives),
# never structural. They were structural under the earlier, stricter id-token/pattern rules.
WELL_TYPED = [
    finding(type="Payment Allocation"), finding(type=""), finding(currency="kzt"), finding(currency="KZTT"),
    finding(claimed_amount_minor=2**53), finding(evidence_ids=["has space"]), finding(evidence_ids=["x" * 65]),
    finding(affected_ids=[]), finding(affected_ids=["I"] * 21), {**finding(), "confidence": 0.9},
]  # fmt: skip


@pytest.mark.parametrize("item", WELL_TYPED)
def test_well_typed_wrong_values_are_not_malformed(item: dict[str, Any]) -> None:
    assert len(parse([item])) == 1


@pytest.mark.parametrize(
    "args",
    [None, [], {}, {"findings": []}, {"findings": {"episode_id": FAULTY_ID}},
     {"findings": {"episode_id": FAULTY_ID, "findings": []}, "extra": 1}],
)  # fmt: skip
def test_malformed_submit_envelopes(args: object) -> None:
    with pytest.raises(MalformedSubmission):
        parse_submission(args, FAULTY_ID, LIMITS)


def test_document_without_episode_id_or_with_extra_keys_is_accepted() -> None:
    assert parse_submission({"findings": {"findings": []}}, FAULTY_ID, LIMITS) == ()
    assert parse_submission({"findings": {"episode_id": FAULTY_ID, "findings": [], "note": 1}}, FAULTY_ID, LIMITS) == ()


@pytest.mark.parametrize("episode_id", ["ep-other", None, 5, ""])
def test_wrong_episode_id_is_malformed(episode_id: object) -> None:
    with pytest.raises(MalformedSubmission, match="episode_id"):
        parse([], episode_id)  # type: ignore[arg-type]
