"""Error types, split by who is allowed to see them."""

from __future__ import annotations

# Every message a policy can receive comes from this table. Messages never echo
# the policy's input and never contain paths, record contents or scoring details.
POLICY_ERRORS: dict[str, str] = {
    "invalid_action": "action must be an object with exactly the keys 'action' and 'args'",
    "unknown_action": "action name is not one of the allowed actions",
    "bad_arguments": "arguments do not match the action's schema",
    "unknown_table": "table is not one of: ledger, invoices, payments, fx",
    "unknown_id": "no record with that id",
    "bad_cursor": "cursor is not valid for this table",
    "bad_limit": "limit must be an integer between 1 and the page limit",
    "action_too_large": "action exceeds the maximum encoded size",
    "calc_syntax": "expression is not valid decimal arithmetic",
    "calc_too_long": "expression is longer than the allowed length",
    "calc_too_deep": "expression is nested more deeply than allowed",
    "calc_div_zero": "division by zero",
    "calc_overflow": "value is outside the allowed range",
    "episode_over": "the episode has ended; no further actions are accepted",
    "internal_error": "the environment could not process this action",
}


class PolicyVisibleError(Exception):
    """An error that is safe to return to the policy: a code from POLICY_ERRORS."""

    def __init__(self, code: str) -> None:
        if code not in POLICY_ERRORS:
            raise ValueError(f"unregistered policy error code: {code}")
        super().__init__(code)
        self.code = code

    def to_observation(self) -> dict[str, str]:
        return {"code": self.code, "message": POLICY_ERRORS[self.code]}


class MalformedSubmission(Exception):
    """A submit action whose payload fails the findings schema.

    The detail goes to the evaluator log only; the episode ends with reward -1.
    """

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class EpisodeError(Exception):
    """An episode's files are invalid. Evaluator-side only; never shown to a policy."""


class LifecycleError(Exception):
    """The harness used the environment out of order (for example step before reset)."""
