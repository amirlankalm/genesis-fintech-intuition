"""Structural validation of actions and of the final submission.

Two different failures live here and must never be confused:

* an invalid *inspection* action -> PolicyVisibleError: bounded error, costs a step,
  the episode continues;
* a malformed *final submission* -> MalformedSubmission: the episode ends with -1.
  A submission is any action object whose `action` is "submit".

A submission is malformed only for the three reasons the official matcher conventions
list: a value of the wrong JSON type, a missing required key, or an exceeded limit
(30 findings, 10 evidence ids in the list as sent, 1,000 explanation code points).
Everything else is scored. A well-typed finding with an unknown type, any currency
string, any id strings, an empty or long affected_ids list or a huge integer amount
is unmatched by the verifier and counts as a false positive. Unknown extra keys in
the findings document and in a finding are ignored. episode_id may be omitted; if
present it must be the episode's id string.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import MalformedSubmission, PolicyVisibleError

ACTIONS: dict[str, tuple[str, ...]] = {
    "list_records": ("table", "cursor", "limit"),
    "get_record": ("table", "id"),
    "get_document": ("doc_id",),
    "calculator": ("expression",),
    "submit": ("findings",),
}
FINDING_KEYS = ("type", "affected_ids", "claimed_amount_minor", "currency", "evidence_ids", "explanation")


@dataclass(frozen=True)
class Finding:
    """One submitted claim in canonical form: id lists are sorted, de-duplicated tuples."""

    type: str
    affected_ids: tuple[str, ...]
    claimed_amount_minor: int
    currency: str
    evidence_ids: tuple[str, ...]
    explanation: str

    def key(self) -> tuple[Any, ...]:
        """Sort key over the scored fields. The explanation is deliberately excluded."""
        return (self.type, self.affected_ids, self.claimed_amount_minor, self.currency, self.evidence_ids)


def parse_action(action: object) -> tuple[str, Any]:
    """Check the action envelope and return (name, args).

    Any object whose `action` is exactly "submit" is a submission attempt, however
    broken the rest of the envelope is: it raises MalformedSubmission and ends the
    episode. Otherwise a policy could dodge the -1 by breaking the envelope on purpose.
    """
    if isinstance(action, dict) and action.get("action") == "submit":
        if set(action) != {"action", "args"}:
            raise MalformedSubmission("submit envelope must have exactly the keys 'action' and 'args'")
        return "submit", action["args"]  # the payload is validated by parse_submission
    if not isinstance(action, dict) or set(action) != {"action", "args"}:
        raise PolicyVisibleError("invalid_action")
    name, args = action["action"], action["args"]
    if not isinstance(name, str) or name not in ACTIONS:
        raise PolicyVisibleError("unknown_action")
    if not isinstance(args, dict) or not set(args) <= set(ACTIONS[name]):
        raise PolicyVisibleError("bad_arguments")
    required = {"list_records": {"table"}, "get_record": {"table", "id"}}.get(name, set(ACTIONS[name]))
    if not required <= set(args):
        raise PolicyVisibleError("bad_arguments")
    return name, args


def _fail(detail: str) -> MalformedSubmission:
    return MalformedSubmission(detail)


def _id_list(value: object, where: str, maximum: int | None = None) -> tuple[str, ...]:
    """A list of strings, capped as sent (before repeats are removed), as a sorted set."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _fail(f"{where}: must be a list of strings")
    if maximum is not None and len(value) > maximum:
        raise _fail(f"{where}: must be a list of at most {maximum} ids as sent, repeats included")
    return tuple(sorted(set(value)))


def parse_submission(args: object, episode_id: str, limits: Mapping[str, int]) -> tuple[Finding, ...]:
    """Validate submit args {"findings": <findings.json object>}, or raise MalformedSubmission."""
    if not isinstance(args, dict) or set(args) != {"findings"}:
        raise _fail("submit args must be an object with exactly the key 'findings'")
    return parse_findings_document(args["findings"], episode_id, limits)


def parse_findings_document(document: object, episode_id: str, limits: Mapping[str, int]) -> tuple[Finding, ...]:
    """Validate a findings.json object {"episode_id"?: str, "findings": [...]}; unknown keys are ignored."""
    if not isinstance(document, dict) or "findings" not in document:
        raise _fail("findings document must be an object with the key 'findings'")
    if "episode_id" in document and not (
        isinstance(document["episode_id"], str) and document["episode_id"] == episode_id
    ):
        raise _fail("findings.episode_id, when present, must be this episode's id")
    items = document["findings"]
    if not isinstance(items, list) or len(items) > limits["max_findings"]:
        raise _fail(f"findings must be a list of at most {limits['max_findings']} items")
    return tuple(_parse_finding(item, index, limits) for index, item in enumerate(items))


def _parse_finding(item: object, index: int, limits: Mapping[str, int]) -> Finding:
    where = f"findings[{index}]"
    if not isinstance(item, dict):
        raise _fail(f"{where}: must be an object")
    missing = [key for key in FINDING_KEYS if key not in item]
    if missing:
        raise _fail(f"{where}: missing required keys: {', '.join(missing)}")
    kind, currency, amount, explanation = (
        item["type"], item["currency"], item["claimed_amount_minor"], item["explanation"],
    )  # fmt: skip
    if not isinstance(kind, str):
        raise _fail(f"{where}.type: must be a string")
    if not isinstance(currency, str):
        raise _fail(f"{where}.currency: must be a string")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise _fail(f"{where}.claimed_amount_minor: must be a JSON integer, not a bool, string or fraction")
    max_chars = limits["max_explanation_chars"]
    if not isinstance(explanation, str) or len(explanation) > max_chars:
        raise _fail(f"{where}.explanation: must be a string of at most {max_chars} characters (code points)")
    return Finding(
        type=kind,
        affected_ids=_id_list(item["affected_ids"], f"{where}.affected_ids"),
        claimed_amount_minor=amount,
        currency=currency,
        evidence_ids=_id_list(item["evidence_ids"], f"{where}.evidence_ids", limits["max_evidence_ids"]),
        explanation=explanation,
    )
